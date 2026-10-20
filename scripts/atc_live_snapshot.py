"""Manual, unpersisted latest-candle scans; publish only the prepared snapshot.

Actual mutable OHLCV is evaluated as if it closed now. This never writes bars,
evaluations, outcomes or calibrations to confirmed stores and never places orders.
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.core.timeframes import parse_timeframe
from market_intelligence.delivery.telegram.http_transport import HttpxTelegramTransport
from market_intelligence.features.atc_native import AtcNativePacketProvider
from market_intelligence.features.decision import DecisionPanelV645Provider
from market_intelligence.features.ma import QualifiedMaResearchProvider
from market_intelligence.features.momentum import (
    LegacyRsi7Provider,
    LegacyRsi14Provider,
    MacdProvider,
    RsiProvider,
    SmiProvider,
)
from market_intelligence.features.registry import FeatureEngine, FeatureRegistry
from market_intelligence.features.research import ResearchTechnicalSnapshotProvider
from market_intelligence.features.technical import TechnicalMarketContextProvider
from market_intelligence.features.trend import (
    InclusiveVolumeSma10Provider,
    InclusiveVolumeSma20Provider,
    LegacyTrendMaProvider,
)
from market_intelligence.features.volatility import WilderAtr14Provider
from market_intelligence.features.volume import RelativeVolume20Provider
from market_intelligence.scanning.catalog import load_scanner_catalog
from market_intelligence.scanning.contracts import ScanContext
from market_intelligence.scanning.display_codes import (
    SCANNER_ORDER,
    direction_display,
    scanner_code,
)
from market_intelligence.scanning.pipeline import ScanPipeline
from market_intelligence.scheduling.xist import ExchangeCalendarsXist
from scripts.atc_ephemeral_morning import vendor_chain
from scripts.atc_export_dashboard import status_label
from scripts.atc_live_snapshot_frames import prepare_frame
from scripts.atc_saved_scan_plans import validate_reference_plan
from scripts.atc_structure_report import atomic_json, canonical
from scripts.atc_timeframe_visuals import _font
from scripts.atc_universe_seed import load_pinned

IST = ZoneInfo("Europe/Istanbul")
VERSION = "atc-unpersisted-latest-candle-v1"
CHAT = -1004439315048
TOPICS = {"15m": 6, "30m": 11, "45m": 9, "1h": 28326,
          "2h": 10, "4h": 28327, "1d": 28328}
FILES = ("live-snapshot.json", "live-snapshot.csv", "live-snapshot.txt", "live-snapshot.png")
MAX_AGE = timedelta(minutes=30)
MIN_COVERAGE = 0.90
# Only fixed validation messages defined by this application's frame adapter
# may be exposed. Provider exception text can contain URLs or credentials.
SAFE_SOURCE_ERROR_REASONS = frozenset({
    "Latest derived candle has missing native OHLCV; no gap filling",
})


class NoQualification:
    """A new RAM snapshot has no independently qualified Rule18 history."""

    def load(self, frame):
        return ()


def ram_pipeline():
    registry = FeatureRegistry()
    for provider in (
        AtcNativePacketProvider(), RelativeVolume20Provider(), MacdProvider(),
        RsiProvider(), SmiProvider(), LegacyRsi7Provider(), LegacyRsi14Provider(),
        LegacyTrendMaProvider(), InclusiveVolumeSma10Provider(),
        InclusiveVolumeSma20Provider(), WilderAtr14Provider(), DecisionPanelV645Provider(),
        TechnicalMarketContextProvider(), ResearchTechnicalSnapshotProvider(),
        QualifiedMaResearchProvider(NoQualification()),
    ):
        registry.register(provider)
    return ScanPipeline(FeatureEngine(registry))


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware_observation_required")
    return value.astimezone(IST)


def implementation_hashes():
    root = Path(__file__).resolve().parents[1]
    files = [*sorted((root / "src/market_intelligence").rglob("*.py")),
        *sorted((root / "scripts").glob("*.py")),
        root / "config/scanners.toml", root / "config/atc_630_symbols.txt"]
    return {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in files}


def evaluate_frame(frame, metadata, *, bindings, calendar_version):
    if frame.is_partial or frame.quality != "PROVISIONAL_WHAT_IF_NOT_PERSISTED":
        raise ValueError("isolated_what_if_frame_required")
    pipeline = ram_pipeline()
    observed = aware(datetime.fromisoformat(metadata["received_at"]))
    evaluations = []
    by_id = {binding.scanner.id: binding for binding in bindings}
    if set(by_id) != set(SCANNER_ORDER):
        raise ValueError("exact_18_scanner_catalog_required")
    for number, scanner_id in enumerate(SCANNER_ORDER, 1):
        binding = by_id[scanner_id]
        context = ScanContext(evaluation_time=observed, bar_close_time=frame.through_bar_time,
            market_session_id=f"BIST:{observed.date()}", calendar_version=calendar_version,
            ruleset_hash=binding.ruleset_hash)
        scan = pipeline.run(cycle_id="UNPERSISTED_LATEST_CANDLE_ONLY", frame=frame,
            scanner=binding.scanner, context=context).scan
        findings = []
        for finding in scan.findings:
            plan = validate_reference_plan(dict(finding.metrics),
                direction=finding.direction.value, timeframe=frame.timeframe.value,
                close=frame.through_bar_time, snapshot_id=frame.snapshot_id) if number <= 16 else None
            source_plan = finding.metrics.get("trade_plan", {})
            findings.append({"direction": finding.direction.value,
                "plan": dict(plan._asdict()) if plan else None,
                "plan_status": "reference" if plan else "unavailable",
                "plan_reason": source_plan.get("reason", "validated_same_snapshot_reference" if plan else "no_standalone_plan")})
        evaluations.append({"number": number, "code": scanner_code(number),
            "scanner_id": scanner_id, "version": binding.scanner.version,
            "ruleset_hash": binding.ruleset_hash, "status": scan.evaluation.status.value,
            "error_code": scan.evaluation.error_code, "findings": findings})
    return evaluations


def read_symbol(symbol, *, timeframe, bindings, calendar_version, clock=None, providers=None):
    clock = clock or (lambda: datetime.now(IST))
    errors, best = [], None
    member = SimpleNamespace(instrument_id="atc-live:BIST:" + symbol,
        symbol=symbol, provider_symbol=symbol, market="BIST")
    for provider in providers if providers is not None else vendor_chain():
        try:
            frame, meta = prepare_frame(provider, member, timeframe, now=clock, bars=600)
            row = {"symbol": symbol, "status": "available", "source": frame.source,
                "price_basis": frame.price_basis.value, "snapshot_id": frame.snapshot_id,
                "history_bars": len(frame.bars), "close": frame.bars[-1].close,
                "metadata": meta}
            if best is None:
                best = (row, frame)
            if meta.get("usable_latest"):
                best = (row, frame)
                break
        except Exception as error:
            detail = {"source": getattr(provider, "name", type(provider).__name__),
                      "code": type(error).__name__}
            if isinstance(error, ValueError) and str(error) in SAFE_SOURCE_ERROR_REASONS:
                detail["reason"] = str(error)
            errors.append(detail)
    if best is None:
        return {"symbol": symbol, "status": "source_unavailable", "source_errors": errors,
                "evaluations": []}
    row, frame = best
    row["source_errors"] = errors
    row["evaluations"] = evaluate_frame(frame, row["metadata"], bindings=bindings,
                                         calendar_version=calendar_version)
    return row


def matches(report):
    for row in report["rows"]:
        # Retain stale scans in JSON/CSV, but never put them in the current signal summary.
        if not row.get("metadata", {}).get("usable_latest"):
            continue
        for scan in row["evaluations"]:
            if scan["status"] != EvaluationStatus.MATCH.value:
                continue
            for finding in scan["findings"]:
                state = status_label("match", (finding["direction"],))
                yield row, scan, finding, direction_display(state)


def render_summary(report):
    counts = report["counts"]
    lines = [f"ATC | {report['timeframe']} | CANLI / TEYİTSİZ",
        f"Gözlem: {report['observation_start']} → {report['observation_end']}",
        f"Kapsam {report['symbol_count']}/630 · kullanılabilir son mum {counts['usable']} · güncel aralık {counts['current']} · "
        f"eski mum {counts['stale']} · veri yok {counts['missing']}",
        f"Eksik son aralık: {counts.get('incomplete_latest', 0)} · yalnız gözlenen kesintisiz kaynak bölümü kullanıldı.",
        "Son gerçek mum o an kapansaydı: koşullar ve referans Stop/TP değişebilir."]
    grouped = {}
    for row, scan, _, direction in matches(report):
        grouped.setdefault((scan["number"], direction), []).append(row["symbol"])
    for (number, direction), symbols in sorted(grouped.items()):
        unique = sorted(set(symbols))
        lines.append(f"{scanner_code(number)} {direction} · {len(unique)} · "
            + ", ".join("#" + symbol for symbol in unique[:3])
            + (" …" if len(unique) > 3 else ""))
    if not grouped:
        lines.append("Kullanılabilir son mumlarda eşleşme bulunmadı.")
    lines.extend(["Görsel ilk 20 eşleşme; tüm hisseler ve 18 tarama CSV'de.",
        "Fiyat/hacim kaynağının anlık olduğu doğrulanmadı. GitHub taraması tek anlık akış değildir.",
        "18: geçmiş yeterlilik kaydı yoksa HESAPLANAMADI. CANLI / TEYİTSİZ · YTD"])
    text = "\n".join(lines)
    if len(text) > 4000:
        raise ValueError("summary_exceeds_single_telegram_message")
    return text


def csv_report(report):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(("Hisse", "ZamanDilimi", "Tarama", "Durum", "Yon", "KaynakDurumu",
        "KullanilabilirSonMum", "GuncelMum", "MumAcik", "Gozlem", "AlinmaZamani", "MumBaslangici", "MumSonu",
        "SonFiyat", "Giris", "Stop", "TP1", "TP2", "TP3", "PlanDurumu", "PlanNedeni",
        "Kaynak", "FiyatBazi", "Snapshot", "Hata", "Teyit", "SonMumDurumu",
        "SonKaynakMumBaslangici", "SonKaynakMumSonu", "KaynakMumBitisYasiSaniye",
        "KullanimYasSiniriDakika", "AtlananEksikGecmisAralik", "GecmisKisaSeansTarihleri",
        "GecmisKisaSeansKapanisSaatiNominal", "SonHedefAralikTam", "GozlenenOnEkSonu", "KaynakHatalari"))
    for row in report["rows"]:
        meta = row.get("metadata", {})
        scans = row["evaluations"] or [{"number": n, "status": "unknown", "findings": [],
            "error_code": "source_unavailable"} for n in range(1, 19)]
        for scan in scans:
            for finding in scan["findings"] or [{}]:
                plan = finding.get("plan") or {}
                writer.writerow((row["symbol"], report["timeframe"], scanner_code(scan["number"]),
                    scan["status"], finding.get("direction", ""), row["status"],
                    meta.get("usable_latest", False), meta.get("current_bucket", False), meta.get("actual_bar_is_open", ""),
                    meta.get("observed_at", ""), meta.get("received_at", ""),
                    meta.get("last_bar_open", ""), meta.get("last_bar_close", ""), row.get("close", ""),
                    *(plan.get(key, "") for key in ("entry", "stop", "tp1", "tp2", "tp3")),
                    finding.get("plan_status", ""), finding.get("plan_reason", ""),
                    row.get("source", ""), row.get("price_basis", ""), row.get("snapshot_id", ""),
                    scan.get("error_code") or "", "CANLI / TEYITSIZ", meta.get("status", ""),
                    meta.get("last_actual_native_open", ""), meta.get("last_actual_native_close", ""),
                    meta.get("latest_native_close_age_seconds", ""),
                    meta.get("latest_native_age_limit_minutes", ""),
                    meta.get("dropped_incomplete_history_buckets", ""),
                    "/".join(meta.get("nonregular_history_dates", [])),
                    meta.get("historical_nonregular_close_times_nominal", ""),
                    meta.get("latest_target_complete", ""), meta.get("observed_prefix_end", ""),
                    canonical([{**{key: error[key] for key in ("source", "code") if key in error},
                                **({"reason": error["reason"]} if error.get("reason") in SAFE_SOURCE_ERROR_REASONS else {})}
                               for error in row.get("source_errors", [])])))
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def render_png(report):
    from PIL import Image, ImageDraw
    rows = list(matches(report))
    shown = rows[:20]
    image = Image.new("RGB", (1840, 350 + max(1, len(shown)) * 46), "#F1F5F9")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1840, 100), fill="#112E4A")
    draw.text((35, 30), f"ATC | {report['timeframe']} | CANLI / TEYİTSİZ", fill="white", font=_font(28, bold=True))
    start = datetime.fromisoformat(report["observation_start"]).astimezone(IST)
    end = datetime.fromisoformat(report["observation_end"]).astimezone(IST)
    draw.text((35, 72), f"Gözlem {start:%d.%m.%Y %H:%M:%S} – {end:%d.%m.%Y %H:%M:%S} TSİ · Kaynak mum zamanları CSV'de", fill="white", font=_font(17))
    draw.text((35, 120), f"Son mum {report['counts']['usable']}/{report['symbol_count']} · güncel aralık {report['counts']['current']} · "
        f"{len(rows)} eşleşmeden ilk {len(shown)} · tam liste CSV'de", fill="#112E4A", font=_font(22))
    draw.text((35, 150), f"Eksik son aralık: {report['counts'].get('incomplete_latest', 0)} · "
        "yalnız gözlenen kaynak bölümü; tam aralık OHLCV'si değildir.", fill="#52697F", font=_font(17))
    columns = ((35, "HİSSE"), (260, "KOD / YÖN"), (600, "GİRİŞ"), (830, "STOP"),
               (1060, "TP1"), (1290, "TP2"), (1520, "TP3"))
    for x, title in columns:
        draw.text((x, 175), title, fill="#52697F", font=_font(20, bold=True))
    for i, (row, scan, finding, direction) in enumerate(shown):
        y = 215 + i * 46
        draw.rectangle((24, y, 1816, y + 44), fill="white" if i % 2 == 0 else "#EDF2F7")
        plan = finding["plan"] or {}
        vals = [row["symbol"], f"{scan['code']} / {direction}",
                *(f"{plan[key]:.4f}" if key in plan else "—"
                  for key in ("entry", "stop", "tp1", "tp2", "tp3"))]
        for (x, _), value in zip(columns, vals, strict=True):
            draw.text((x, y + 9), value, fill="#112E4A", font=_font(20, bold=x == 35))
    draw.text((35, image.height - 100), "Son gerçek mum o an kapansaydı · değişebilir · Stop/TP referanstır, emir değildir.",
              fill="#52697F", font=_font(22))
    draw.text((35, image.height - 60), "Hisseler farklı anlarda gözlenir; kaynak gecikmesi CSV'de doğrulanmış sayılmaz.",
              fill="#52697F", font=_font(20))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def prepare_report(folder, *, timeframe="15m", workers=2, symbols=None, reader=read_symbol, clock=None):
    clock = clock or (lambda: datetime.now(IST))
    started = aware(clock())
    tf = parse_timeframe(timeframe)
    if tf.value not in TOPICS or type(workers) is not int or not 1 <= workers <= 6:
        raise ValueError("supported_timeframe_and_1_to_6_workers_required")
    pinned = load_pinned(Path("config/atc_630_symbols.txt"))
    selected = list(symbols if symbols is not None else pinned)
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(pinned):
        raise ValueError("unique_pinned_symbols_required")
    folder = Path(folder)
    if (folder / "prepared-packet.json").exists():
        raise ValueError("prepared_packet_exists_use_publish_from")
    calendar = ExchangeCalendarsXist()
    bindings = load_scanner_catalog(Path("config/scanners.toml"), calendar_version=calendar.version)
    def read(symbol):
        return reader(symbol, timeframe=tf, bindings=bindings, calendar_version=calendar.version, clock=clock)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(executor.map(read, selected))
    if [row["symbol"] for row in rows] != selected:
        raise ValueError("result_symbol_identity_changed")
    finished = aware(clock())
    observations = [aware(datetime.fromisoformat(row["metadata"][key])) for row in rows
                    if row["status"] == "available" for key in ("observed_at", "received_at")]
    counts = Counter(row["status"] for row in rows)
    current = sum(row.get("metadata", {}).get("current_bucket", False) for row in rows)
    usable = sum(row.get("metadata", {}).get("usable_latest", False) for row in rows)
    incomplete_latest = sum(row.get("metadata", {}).get("status") == "incomplete_latest_native_prefix"
                            for row in rows)
    report = {"version": VERSION, "timeframe": tf.value, "started_at": started.isoformat(),
        "finished_at": finished.isoformat(), "observation_start": min(observations, default=started).isoformat(),
        "observation_end": max(observations, default=finished).isoformat(), "symbol_count": len(rows),
        "counts": {"usable": usable, "current": current, "stale": counts["available"] - usable,
                   "missing": counts["source_unavailable"], "incomplete_latest": incomplete_latest},
        "rows": sorted(rows, key=lambda row: row["symbol"]),
        "provisional": True, "confirmed_store_writes": 0, "orders_sent": 0,
        "feed_latency_verified": False, "calibration_used": False}
    folder.mkdir(parents=True, exist_ok=True)
    atomic_json(folder / FILES[0], report)
    (folder / FILES[1]).write_bytes(csv_report(report))
    (folder / FILES[2]).write_text(render_summary(report), encoding="utf-8")
    (folder / FILES[3]).write_bytes(render_png(report))
    atomic_json(folder / "prepared-packet.json", {"version": VERSION,
        "implementation_files": implementation_hashes(),
        "files": {name: sha256((folder / name).read_bytes()).hexdigest() for name in FILES}})
    return report


def publish_report(folder, *, now=None, transport=None, environ=None):
    env, folder = os.environ if environ is None else environ, Path(folder)
    now = aware(now or datetime.now(IST))
    raw = (folder / "prepared-packet.json").read_bytes()
    manifest = json.loads(raw)
    if (manifest.get("version") != VERSION or set(manifest.get("files", {})) != set(FILES)
            or manifest.get("implementation_files") != implementation_hashes()):
        raise ValueError("implementation_changed_reprepare_required")
    for name in FILES:
        path = folder / name
        if path.is_symlink() or sha256(path.read_bytes()).hexdigest() != manifest["files"][name]:
            raise ValueError("prepared_file_hash_changed")
    report = json.loads((folder / FILES[0]).read_bytes())
    tf = report.get("timeframe")
    topic = TOPICS.get(tf)
    if int(env.get("TELEGRAM_CHAT_ID", "0")) != CHAT or topic is None:
        raise ValueError("existing_timeframe_destination_required")
    from market_intelligence.delivery.telegram.timeframe_topics import timeframe_topic_ids
    if timeframe_topic_ids(env).get(parse_timeframe(tf)) != topic:
        raise ValueError("existing_timeframe_destination_required")
    rows = report.get("rows", [])
    if (report.get("version") != VERSION or report.get("symbol_count") != 630 or len(rows) != 630
            or {row["symbol"] for row in rows} != set(load_pinned(Path("config/atc_630_symbols.txt")))
            or not report.get("provisional") or report.get("confirmed_store_writes") != 0):
        raise ValueError("complete_pinned_provisional_packet_required")
    start = aware(datetime.fromisoformat(report["observation_start"]))
    end = aware(datetime.fromisoformat(report["observation_end"]))
    if not start <= end <= now or now - start > MAX_AGE:
        raise ValueError("snapshot_expired_reprepare_required")
    usable = sum(row.get("metadata", {}).get("usable_latest", False) for row in rows)
    if usable < MIN_COVERAGE * 630 or usable != report["counts"]["usable"]:
        raise ValueError("latest_actual_source_coverage_below_90_percent")
    packet_hash = sha256(raw).hexdigest()
    receipt_path = folder / "publication-receipt.json"
    receipt = json.loads(receipt_path.read_bytes()) if receipt_path.exists() else {
        "packet_sha256": packet_hash, "chat_id": CHAT, "topic_id": topic, "acknowledged": {}}
    if (receipt.get("packet_sha256") != packet_hash or receipt.get("chat_id") != CHAT
            or receipt.get("topic_id") != topic or any(key not in ("text", "photo", "csv")
                or type(value) is not int or value <= 0 for key, value in receipt["acknowledged"].items())):
        raise ValueError("delivery_receipt_identity_changed")
    sender = transport if transport is not None else HttpxTelegramTransport(env["TELEGRAM_BOT_TOKEN"])
    payloads = {
        "text": {"text": (folder / FILES[2]).read_text(encoding="utf-8")},
        "photo": {"_method": "sendPhoto", "photo_base64": base64.b64encode((folder / FILES[3]).read_bytes()).decode("ascii"),
            "filename": f"ATC_{tf}_CANLI_TEYITSIZ.png", "caption": "CANLI / TEYİTSİZ · ilk 20 eşleşme · tüm sonuçlar CSV'de · emir değildir."},
        "csv": {"_method": "sendDocument", "document_base64": base64.b64encode((folder / FILES[1]).read_bytes()).decode("ascii"),
            "filename": f"ATC_630_{tf}_CANLI_TEYITSIZ.csv", "caption": "630 hisse × 18 tarama · son gerçek mum anlık görüntüsü · eksikler ayrı · CANLI / TEYİTSİZ."}}
    for key, payload in payloads.items():
        if key in receipt["acknowledged"]:
            continue
        message_id = sender.send(chat_id=CHAT, message_thread_id=topic, payload=payload)
        if type(message_id) is not int or message_id <= 0:
            raise ValueError("telegram_acknowledgement_required")
        receipt["acknowledged"][key] = message_id
        receipt["updated_at"] = datetime.now(IST).isoformat()
        atomic_json(receipt_path, receipt)
    receipt["status"] = "sent"
    atomic_json(receipt_path, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--publish-from", type=Path)
    parser.add_argument("--timeframe", default="15m", choices=tuple(TOPICS))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--symbols", help="Preview only: comma-separated pinned symbols")
    parser.add_argument("--output-dir", type=Path, default=Path("runtime_artifacts/live"))
    args = parser.parse_args(argv)
    if args.prepare:
        result = prepare_report(args.output_dir, timeframe=args.timeframe, workers=args.workers,
            symbols=args.symbols.split(",") if args.symbols else None)
        print(canonical({"status": "prepared_not_sent", "symbols": result["symbol_count"], "counts": result["counts"]}))
    else:
        result = publish_report(args.publish_from)
        print(canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
