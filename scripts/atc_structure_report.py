"""Prepare a closed daily structure report; publish only its exact reviewed files.

This independent report does not change scanners, Stop/TP, calibration or E.
No account session is read and no Telegram request occurs during preparation.
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.delivery.telegram.http_transport import HttpxTelegramTransport
from market_intelligence.market_data.canonicalizer import Canonicalizer
from market_intelligence.market_data.providers import FetchRequest
from market_intelligence.scheduling.xist import ExchangeCalendarsXist
from scripts.atc_ephemeral_morning import vendor_chain
from scripts.atc_pivot_ladder import traditional_pivot_ladder
from scripts.atc_support_resistance import build_support_resistance
from scripts.atc_telegram_briefings import last_closed_session, pivot_levels
from scripts.atc_universe_seed import load_pinned

VERSION = "atc-closed-daily-structure-v2"
IST = ZoneInfo("Europe/Istanbul")
CHAT = -1004439315048
TOPIC = 8
FILES = ("report.json", "report.csv", "summary.txt", "summary.png")
MIN_COVERAGE = 0.90
IMPLEMENTATION_FILES = ("atc_structure_report.py", "atc_support_resistance.py", "atc_telegram_briefings.py", "atc_pivot_ladder.py")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical(value) + "\n", encoding="utf-8")
    temporary.replace(path)


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware_observation_required")
    return value.astimezone(IST)


def expected_session(now):
    now = aware(now)
    return last_closed_session(ExchangeCalendarsXist(), now.date())


def read_structure(symbol, *, previous, now, providers=None):
    """Keep all OHLC, structural pivots and floor pivots within one provider."""
    now = aware(now)
    builder = Canonicalizer()
    _, cutoff = builder.schedule.session_bounds(previous)
    if cutoff > now:
        raise ValueError("previous_session_must_be_closed")
    errors = []
    for vendor in providers if providers is not None else vendor_chain():
        source = getattr(vendor, "name", type(vendor).__name__)
        try:
            raw = vendor.fetch(FetchRequest(
                provider_symbol=symbol, timeframe=Timeframe.D1, bars=150, as_of=cutoff,
            ))
            if raw.provider_symbol != symbol or raw.timeframe is not Timeframe.D1:
                raise ValueError("provider_identity_changed")
            frame = builder.build(instrument_id="atc-report:BIST:" + symbol,
                symbol_at_snapshot=symbol, market="BIST", provider_frame=raw,
                target_timeframe=Timeframe.D1, series_revision=0)
            closed = tuple(bar for bar in frame.bars if bar.close_time <= cutoff)
            if not closed or closed[-1].open_time.astimezone(IST).date() != previous:
                raise ValueError("exact_previous_session_missing")
            if any(not all(math.isfinite(v) and v > 0 for v in
                           (bar.open, bar.high, bar.low, bar.close)) for bar in closed):
                raise ValueError("invalid_positive_history")
            # Canonicalize the selected closed rows again for their own identity;
            # never retain a snapshot hash that includes a removed future bar.
            from market_intelligence.core.identity import stable_hash
            parent_snapshot = frame.snapshot_id
            selected_id = stable_hash({"parent": parent_snapshot, "bars": closed,
                "as_of": cutoff, "method": VERSION})
            frame = replace(frame, bars=closed, snapshot_id=selected_id,
                            is_partial=False, quality="complete")
            context = build_support_resistance(frame, as_of=cutoff)
            bar = closed[-1]
            ladder = traditional_pivot_ladder(bar.high, bar.low, bar.close)
            try:
                s1, s2, p, r1, r2 = pivot_levels(bar.high, bar.low, bar.close)
                floor = {"status": "ready", "S1": s1, "S2": s2,
                         "P": p, "R1": r1, "R2": r2}
            except ValueError:
                floor = {"status": "unavailable_invalid_price_geometry"}
            turnover = bar.close * bar.volume
            return {"symbol": symbol, "status": "fresh_closed_source",
                "session": previous.isoformat(), "as_of": cutoff.isoformat(),
                "received_at": now.isoformat(), "source": frame.source,
                "price_basis": frame.price_basis.value, "snapshot_id": frame.snapshot_id,
                "parent_snapshot_id": parent_snapshot,
                "close": bar.close, "turnover": turnover if math.isfinite(turnover) else None,
                "history_bars": len(closed), "structure": context, "classic_pivot": floor,
                "reference_ohlc": {"high": bar.high, "low": bar.low, "close": bar.close},
                "pivot_ladder": ladder}
        except Exception as error:
            # No provider text, token, cookie or private account data in logs/files.
            errors.append({"source": source, "code": type(error).__name__})
    return {"symbol": symbol, "status": "source_unavailable", "session": previous.isoformat(),
            "source_errors": errors, "structure": {"status": "unavailable_source"},
            "classic_pivot": {"status": "unavailable_source"},
            "pivot_ladder": {"status": "unavailable_source", "method": "traditional_previous_session_hlc"}}


def price(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        return "—"
    return f"{value:.4f}" if value < 2 else f"{value:.2f}"


def levels(row, key):
    return [item["price"] for item in row.get("structure", {}).get(key, [])]


def ranked(rows):
    return sorted((row for row in rows if row["status"] == "fresh_closed_source"),
                  key=lambda row: (-(row.get("turnover") or 0), row["symbol"]))


def render_summary(report):
    counts = report["counts"]
    lines = ["ATC | Günlük 3 destek / 3 direnç ve pivot",
        f"{report['previous_session']} kapanışı · 630 hisse · geçerli {counts['fresh']}/630",
        f"Kaynak eksik {counts['missing']} · D/R hazır {counts['structure_ready']} · "
        f"120 mumdan kısa {counts['short_history']} · klasik pivot geçersiz {counts['invalid_classic']}",
        f"Formül kademesi hazır {counts['ladder_ready']} · düz seans {counts['flat_ladder']} · "
        f"geçersiz kademe {counts['invalid_ladder']}",
        "Ana tablo: önceki kapalı seans H/L/C ile geleneksel pivot S1–S2–S3 / R1–R2–R3.",
        "Geçmişten teyitli D/R ayrı CSV sütunlarında; bu alanlarda 0–3 seviye bulunabilir.",
        "Görselde önceki seans kapanış × hacme göre ilk 20; tüm 630 hisse CSV'de."]
    for row in ranked(report["rows"])[:8]:
        ladder = row["pivot_ladder"]
        lines.append(f"#{row['symbol']} · K {price(row.get('close'))} · "
            f"S1 {price(ladder.get('S1'))} · S3 {price(ladder.get('S3'))} · "
            f"R1 {price(ladder.get('R1'))} · R3 {price(ladder.get('R3'))}")
    lines.extend(["Formül kademeleri hesaplanmış referanstır; geçmişten teyit edilmiş tepki seviyesi değildir.",
        "Düz seansta formül seviyeleri çakışabilir; geçersiz fiyat yerine sayı uydurulmaz.",
        "Bu seviyeler Stop/TP veya emir değildir. Kaynak, fiyat bazı ve teyit zamanları CSV'de."])
    return "\n".join(lines)


def csv_report(report):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(("Hisse", "KapanisTarihi", "Kapanis", "Durum", "Kaynak", "FiyatBazi",
        "KlasikS2", "KlasikS1", "KlasikPivot", "KlasikR1", "KlasikR2", "KlasikDurum",
        "YapisalDestek1", "YapisalDestek2", "YapisalDestek3", "YapisalDirenc1",
        "YapisalDirenc2", "YapisalDirenc3", "YapisalDurum", "KullanilanKapaliMum",
        "KisaGecmis", "GozlemKesimi", "Snapshot", "DestekTeyitZamanlari", "DirencTeyitZamanlari",
        "PivotDestek1", "PivotDestek2", "PivotDestek3", "PivotDirenc1", "PivotDirenc2", "PivotDirenc3",
        "PivotYontemi", "PivotKademeDurumu", "PivotGecersizAlanlar", "YapisalDestekAdet", "YapisalDirencAdet",
        "YapisalDestekAciklamasi", "YapisalDirencAciklamasi", "ReferansYuksek", "ReferansDusuk"))
    for row in report["rows"]:
        context, floor = row["structure"], row["classic_pivot"]
        supports, resistances = levels(row, "supports"), levels(row, "resistances")
        ladder = row["pivot_ladder"]
        def structural_note(values, status=context["status"]):
            if status != "ready":
                return status
            return "uc_teyitli_seviye_var" if len(values) == 3 else "bu_yonde_uc_teyitli_donus_bulunmadi"
        writer.writerow((row["symbol"], row["session"], price(row.get("close")), row["status"],
            row.get("source", ""), row.get("price_basis", ""),
            *(price(floor.get(key)) for key in ("S2", "S1", "P", "R1", "R2")), floor["status"],
            *(price(values[i] if len(values) > i else None)
              for values in (supports, resistances) for i in range(3)), context["status"],
            context.get("lookback_used", 0), context.get("history_is_shorter_than_requested", True),
            row.get("as_of", ""), row.get("snapshot_id", ""),
            "/".join(item["confirmed_at"] for item in context.get("supports", [])),
            "/".join(item["confirmed_at"] for item in context.get("resistances", [])),
            *(price(ladder.get(key)) for key in ("S1", "S2", "S3", "R1", "R2", "R3")),
            ladder["method"], ladder["status"], "/".join(ladder.get("invalid_fields", [])),
            len(supports), len(resistances), structural_note(supports), structural_note(resistances),
            price(row.get("reference_ohlc", {}).get("high")), price(row.get("reference_ohlc", {}).get("low")) ))
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def render_png(report):
    from PIL import Image, ImageDraw

    from scripts.atc_timeframe_visuals import _font
    rows = ranked(report["rows"])[:20]
    image = Image.new("RGB", (1840, 350 + 46 * max(1, len(rows))), "#F1F5F9")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1840, 100), fill="#112E4A")
    draw.text((35, 30), "ATC | 3 DESTEK / 3 DİRENÇ + GELENEKSEL PİVOT", fill="white", font=_font(27, bold=True))
    draw.text((35, 120), f"{report['previous_session']} kapanışı · "
        f"{report['counts']['fresh']}/630 veri · Kapanış × hacimde ilk 20", fill="#112E4A", font=_font(22))
    columns = ((35, "HİSSE"), (240, "KAPANIŞ"), (440, "S1"), (640, "S2"),
        (840, "S3"), (1040, "R1"), (1240, "R2"), (1440, "R3"), (1640, "PİVOT"))
    for x, title in columns:
        draw.text((x, 175), title, fill="#52697F", font=_font(18, bold=True))
    for i, row in enumerate(rows):
        y = 215 + i * 46
        if i % 2 == 0:
            draw.rectangle((24, y, 1816, y + 44), fill="white")
        ladder = row["pivot_ladder"]
        values = [row["symbol"], price(row.get("close"))]
        values += [price(ladder.get(key)) for key in ("S1", "S2", "S3", "R1", "R2", "R3", "P")]
        for (x, _), value in zip(columns, values, strict=True):
            draw.text((x, y + 10), value, fill="#112E4A", font=_font(18, bold=x == 35))
    y = image.height - 105
    draw.text((35, y), "Formül kademeleri: önceki kapalı seans H/L/C. Düz seansta seviyeler çakışabilir.", fill="#52697F", font=_font(19))
    draw.text((35, y + 35), "Tüm 630 hisse ve geçmişten teyitli D/R ayrı sütunlarla CSV'de. Stop/TP değildir.", fill="#52697F", font=_font(19))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def prepare_report(output_dir, *, now=None, workers=2, symbols=None, reader=read_structure,
                   retries=2, retry_delay=2):
    now = aware(now or datetime.now(IST))
    if type(workers) is not int or not 1 <= workers <= 6:
        raise ValueError("workers_must_be_1_to_6")
    if type(retries) is not int or not 0 <= retries <= 3 or not 0 <= retry_delay <= 10:
        raise ValueError("bounded_source_retries_required")
    selected = list(symbols if symbols is not None else load_pinned(Path("config/atc_630_symbols.txt")))
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("unique_symbols_required")
    output_dir = Path(output_dir)
    if (output_dir / "manifest.json").exists():
        raise ValueError("prepared_report_already_exists_use_publish_from")
    previous = expected_session(now)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(executor.map(lambda symbol: reader(symbol, previous=previous, now=now), selected))
    if [row["symbol"] for row in rows] != selected:
        raise ValueError("result_symbol_identity_changed")
    attempts = dict.fromkeys(selected, 1)
    by_symbol = {row["symbol"]: row for row in rows}
    for _ in range(retries):
        pending = [symbol for symbol in selected if by_symbol[symbol]["status"] != "fresh_closed_source"]
        if not pending:
            break
        time.sleep(retry_delay)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            refreshed = list(executor.map(lambda symbol: reader(symbol, previous=previous, now=now), pending))
        if [row["symbol"] for row in refreshed] != pending:
            raise ValueError("retry_result_symbol_identity_changed")
        for row in refreshed:
            by_symbol[row["symbol"]] = row
            attempts[row["symbol"]] += 1
    rows = [{**by_symbol[symbol], "source_attempts": attempts[symbol]} for symbol in selected]
    rows.sort(key=lambda row: row["symbol"])
    counts = {"fresh": sum(row["status"] == "fresh_closed_source" for row in rows),
        "missing": sum(row["status"] != "fresh_closed_source" for row in rows),
        "structure_ready": sum(row["structure"]["status"] == "ready" for row in rows),
        "short_history": sum(row["structure"].get("history_is_shorter_than_requested", False) for row in rows),
        "invalid_classic": sum(row["classic_pivot"]["status"] == "unavailable_invalid_price_geometry" for row in rows),
        "ladder_ready": sum(row["pivot_ladder"]["status"] in {"ready", "flat_session_coincident_levels"} for row in rows),
        "flat_ladder": sum(row["pivot_ladder"]["status"] == "flat_session_coincident_levels" for row in rows),
        "invalid_ladder": sum(row["status"] == "fresh_closed_source" and row["pivot_ladder"]["status"] not in {"ready", "flat_session_coincident_levels"} for row in rows)}
    report = {"version": VERSION, "prepared_at": now.isoformat(), "previous_session": previous.isoformat(),
        "expected_symbols": 630, "symbol_count": len(rows), "counts": counts, "rows": rows,
        "support_method": "confirmed_120_3_3_pivots", "classic_method": "previous_session_HLC_floor",
        "primary_method": "traditional_previous_session_hlc",
        "source_retry_limit": retries, "source_retry_attempts": sum(value - 1 for value in attempts.values()),
        "stop_tp_changed": False, "calibration_used": False, "research_zone_model_used": False,
        "independent_corporate_action_validation": False}
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / "report.json", report)
    (output_dir / "report.csv").write_bytes(csv_report(report))
    (output_dir / "summary.txt").write_text(render_summary(report), encoding="utf-8")
    (output_dir / "summary.png").write_bytes(render_png(report))
    manifest = {"version": VERSION,
        "implementation_files": {name: sha256((Path(__file__).parent / name).read_bytes()).hexdigest() for name in IMPLEMENTATION_FILES},
        "files": {name: sha256((output_dir / name).read_bytes()).hexdigest() for name in FILES}}
    atomic_json(output_dir / "manifest.json", manifest)
    return report


def publish_report(folder, *, now=None, transport=None, environ=None):
    """Send only hash-bound prepared bytes, never download or recalculate prices."""
    env, folder = os.environ if environ is None else environ, Path(folder)
    if int(env.get("TELEGRAM_CHAT_ID", "0")) != CHAT or int(env.get("TELEGRAM_TOPIC_REPORTS", "0")) != TOPIC:
        raise ValueError("existing_reports_destination_required")
    manifest_raw = (folder / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    if manifest.get("version") != VERSION or set(manifest.get("files", {})) != set(FILES):
        raise ValueError("prepared_manifest_contract_changed")
    if manifest.get("implementation_files") != {
        name: sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
        for name in IMPLEMENTATION_FILES
    }:
        raise ValueError("report_implementation_changed_reprepare_required")
    for name in FILES:
        path = folder / name
        if path.is_symlink() or sha256(path.read_bytes()).hexdigest() != manifest["files"][name]:
            raise ValueError("prepared_file_hash_changed")
    report = json.loads((folder / "report.json").read_bytes())
    if (report.get("version") != VERSION or report.get("symbol_count") != 630
            or len(report.get("rows", [])) != 630
            or {row["symbol"] for row in report["rows"]} != set(load_pinned(Path("config/atc_630_symbols.txt")))
            or report.get("previous_session") != expected_session(now or datetime.now(IST)).isoformat()):
        raise ValueError("complete_current_pinned_report_required")
    fresh = sum(row["status"] == "fresh_closed_source" for row in report["rows"])
    if fresh < MIN_COVERAGE * 630 or fresh != report["counts"]["fresh"]:
        raise ValueError("fresh_closed_coverage_below_90_percent")
    packet_hash = sha256(manifest_raw).hexdigest()
    receipt_path = folder / "delivery.json"
    receipt = json.loads(receipt_path.read_bytes()) if receipt_path.exists() else {
        "manifest_sha256": packet_hash, "chat_id": CHAT, "topic_id": TOPIC, "acknowledged": {}}
    if (receipt.get("manifest_sha256") != packet_hash or receipt.get("chat_id") != CHAT
            or receipt.get("topic_id") != TOPIC):
        raise ValueError("delivery_receipt_identity_changed")
    if any(key not in ("text", "photo", "csv") or type(value) is not int or value <= 0
           for key, value in receipt["acknowledged"].items()):
        raise ValueError("invalid_delivery_acknowledgement")
    sender = transport if transport is not None else HttpxTelegramTransport(env["TELEGRAM_BOT_TOKEN"])
    payloads = {
        "text": {"text": (folder / "summary.txt").read_text(encoding="utf-8")},
        "photo": {"_method": "sendPhoto", "photo_base64": base64.b64encode((folder / "summary.png").read_bytes()).decode("ascii"),
            "filename": "ATC_Destek_Direnc_Pivot.png", "caption": "Günlük geleneksel pivot · 3 destek / 3 direnç · görsel ilk 20 · tam 630 hisse CSV'de."},
        "csv": {"_method": "sendDocument", "document_base64": base64.b64encode((folder / "report.csv").read_bytes()).decode("ascii"),
            "filename": f"ATC_630_Destek_Direnc_Pivot_{report['previous_session']}.csv",
            "caption": "630 hissenin tamamı · S1/S2/S3 ve R1/R2/R3 · geçmişten teyitli D/R ayrı sütunlarda · kaynak ve eksik veri durumları dahil."}}
    for key, payload in payloads.items():
        if key in receipt["acknowledged"]:
            continue
        message_id = sender.send(chat_id=CHAT, message_thread_id=TOPIC, payload=payload)
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
    parser.add_argument("--output-dir", type=Path, default=Path("runtime_artifacts/structure"))
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args(argv)
    if args.prepare:
        result = prepare_report(args.output_dir, workers=args.workers)
        print(canonical({"status": "prepared_not_sent", "symbols": result["symbol_count"], "counts": result["counts"]}))
    else:
        result = publish_report(args.publish_from)
        print(canonical({"status": result["status"], "acknowledged": result["acknowledged"],
            "links": {key: f"https://t.me/c/4439315048/8/{value}" for key, value in result["acknowledged"].items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
