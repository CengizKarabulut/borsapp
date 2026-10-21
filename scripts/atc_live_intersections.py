"""Latest-known provisional intersections; hash-bound TEXT, all PNG pages and CSV.

The workflow supplies GitHub API-verified main-run provenance and acknowledged
source packets. This module rechecks packet bytes, receipts and current rules.
It never downloads prices, mixes Stop/TP plans or writes confirmed scan state.
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import re
import textwrap
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

from market_intelligence.application.scan_intersections import cross_timeframe_intersections
from market_intelligence.scanning.catalog import load_scanner_catalog
from market_intelligence.scanning.display_codes import SCANNER_ORDER, scanner_code_from_id
from market_intelligence.scheduling.xist import ExchangeCalendarsXist
from scripts import atc_live_snapshot as live
from scripts.atc_live_snapshot_frames import NATIVE_45M_GRID
from scripts.atc_structure_report import atomic_json, canonical
from scripts.atc_timeframe_visuals import _font
from scripts.atc_universe_seed import load_pinned

VERSION = "atc-latest-known-provisional-intersections-v1"
TOPIC = 28330
REPOSITORY = "CengizKarabulut/borsapp"
WORKFLOW = ".github/workflows/atc-scheduled-snapshots.yml"
CADENCE_MINUTES = {"15m": 15, "30m": 30, "45m": 45, "1h": 60,
                   "2h": 120, "4h": 240, "1d": 1440}
PAGE_SIZE = 20
BASE_FILES = ("intersections.json", "intersections.txt", "intersections.csv")


def expected_session(now):
    days = ExchangeCalendarsXist().sessions(now.date() - timedelta(days=14), now.date())
    if now.date() in days and now >= now.replace(hour=9, minute=45, second=0, microsecond=0):
        return now.date()
    return max(day for day in days if day < now.date())


def _read(path):
    if path.is_symlink():
        raise ValueError("symlinked_source_packet")
    return json.loads(path.read_bytes())


def validate_source(source, tf):
    if (not isinstance(source, dict) or source.get("head_branch") != "main"
            or source.get("event") not in ("schedule", "workflow_dispatch")
            or source.get("head_repository") != REPOSITORY
            or source.get("artifact_name") != "atc-scheduled-snapshot-" + tf
            or type(source.get("run_id")) is not int or source["run_id"] <= 0
            or not re.fullmatch(r"[0-9a-f]{40}", str(source.get("head_sha", "")))):
        raise ValueError("trusted_main_source_run_required")


def validate_packet(folder, tf, source, *, now, session, pinned, bindings, hashes):
    """Validate one lane independently; mismatches never poison other lanes."""
    validate_source(source, tf)
    if folder.is_symlink():
        raise ValueError("symlinked_source_packet")
    manifest_raw = (folder / "prepared-packet.json").read_bytes()
    manifest = _read(folder / "prepared-packet.json")
    if (manifest.get("version") != live.VERSION
            or set(manifest.get("files", {})) != set(live.FILES)
            or manifest.get("implementation_files") != hashes):
        raise ValueError("source_implementation_changed_refresh_timeframe")
    for name in live.FILES:
        path = folder / name
        if path.is_symlink() or sha256(path.read_bytes()).hexdigest() != manifest["files"][name]:
            raise ValueError("source_packet_file_hash_changed")
    packet_hash = sha256(manifest_raw).hexdigest()
    receipt = _read(folder / "publication-receipt.json")
    acknowledged = receipt.get("acknowledged", {})
    if (receipt.get("status") != "sent" or receipt.get("packet_sha256") != packet_hash
            or receipt.get("chat_id") != live.CHAT or receipt.get("topic_id") != live.TOPICS[tf]
            or set(acknowledged) != {"text", "photo", "csv"}
            or any(type(value) is not int or value <= 0 for value in acknowledged.values())):
        raise ValueError("acknowledged_source_packet_required")
    report = _read(folder / "live-snapshot.json")
    rows = report.get("rows", [])
    if (report.get("version") != live.VERSION or report.get("timeframe") != tf
            or report.get("provisional") is not True or report.get("confirmed_store_writes") != 0
            or report.get("symbol_count") != 630 or len(rows) != 630
            or {row.get("symbol") for row in rows} != pinned):
        raise ValueError("complete_pinned_provisional_source_required")
    start = live.aware(datetime.fromisoformat(report["observation_start"]))
    end = live.aware(datetime.fromisoformat(report["observation_end"]))
    limit = CADENCE_MINUTES[tf] + 30
    # Receipt dates can be the next calendar day before the exchange opens.
    # The actual source-bar session is checked per usable symbol below.
    if not start <= end <= now or now - start > timedelta(minutes=limit):
        raise ValueError("source_observation_expired_or_wrong_session")
    usable = sum(row.get("metadata", {}).get("usable_latest") is True for row in rows)
    if usable < live.MIN_COVERAGE * 630 or usable != report["counts"]["usable"]:
        raise ValueError("source_coverage_below_90_percent")
    details, states = [], []
    for row in rows:
        meta = row.get("metadata", {})
        states.append({"symbol": row["symbol"], "source_status": row.get("status"),
            "usable_latest": meta.get("usable_latest") is True,
            "observed_at": meta.get("observed_at"), "received_at": meta.get("received_at"),
            "bar_open": meta.get("last_bar_open"), "bar_nominal_end": meta.get("last_bar_close"),
            "source_grid": meta.get("source_grid"), "source": row.get("source"),
            "market_event": row.get("market_event", meta.get("market_event")),
            "market_status": row.get("market_status", meta.get("market_status"))})
        if row.get("status") != "available":
            continue
        if tf == "45m" and meta.get("source_grid") != NATIVE_45M_GRID:
            raise ValueError("native_45m_source_grid_required")
        scans = row.get("evaluations", [])
        if (len(scans) != 18 or {scan.get("scanner_id") for scan in scans} != set(bindings)
                or {scan.get("number") for scan in scans} != set(range(1, 19))):
            raise ValueError("exact_current_scanner_catalog_required")
        for scan in scans:
            binding = bindings[scan["scanner_id"]]
            number = SCANNER_ORDER.index(scan["scanner_id"]) + 1
            if (scan.get("number") != number or scan.get("version") != binding.scanner.version
                    or scan.get("ruleset_hash") != binding.ruleset_hash
                    or scan.get("status") not in {"match", "no_match", "unknown"}):
                raise ValueError("source_scanner_identity_changed")
        if meta.get("usable_latest") is not True:
            continue
        # Both field names are accepted because market events and account/feed
        # status are distinct producers. A known halt wins over a stale flag.
        statuses = (row.get("market_event"), meta.get("market_event"),
                    row.get("market_status"), meta.get("market_status"))
        if any(isinstance(status, dict) and status.get("status") in
               {"halted", "official_halt", "trading_halted"} for status in statuses):
            continue
        if meta.get("eligible_for_current_signals") is False:
            continue
        observed = live.aware(datetime.fromisoformat(meta["received_at"]))
        actual_open = live.aware(datetime.fromisoformat(meta["last_actual_native_open"]))
        if not start <= observed <= end or actual_open.date() != session:
            raise ValueError("source_symbol_observation_identity_changed")
        for scan in scans:
            if scan["status"] != "match":
                continue
            directions = {finding.get("direction") for finding in scan.get("findings", [])}
            for direction in sorted(directions & {"bullish", "bearish"}):
                details.append({"symbol": row["symbol"], "scanner": scan["scanner_id"],
                    "direction": direction, "plan": {"scenarios": [], "price_basis": "unknown"}})
    return details, states, {"status": "included", "timeframe": tf,
        "run_id": source["run_id"], "head_sha": source["head_sha"],
        "packet_sha256": packet_hash, "observation_start": start.isoformat(),
        "observation_end": end.isoformat(), "maximum_age_minutes": limit,
        "usable_symbols": usable, "unavailable_symbols": 630 - usable}


def _codes(scanners):
    return ",".join(scanner_code_from_id(value) for value in scanners)


def _frame_codes(item):
    return "; ".join(tf + ":" + _codes(part["scanners"])
                     for tf, part in item["timeframes"].items())


def render_text(report):
    lines = ["ATC KESİŞİM | CANLI / TEYİTSİZ",
        "Son bilinen durumların ortak görünümü; kapanış zamanlarının aynı olması aranmaz.",
        "Her zaman diliminde ≥2 farklı aynı yönlü tarama ve ≥2 zaman dilimi gerekir.",
        f"Üretim: {report['prepared_at']} · Seans: {report['session']}"]
    for tf, lane in report["inputs"].items():
        if lane["status"] == "included":
            lines.append(f"{tf}: {lane['usable_symbols']}/630 · gözlem {lane['observation_end']} · "
                         f"yaş sınırı {lane['maximum_age_minutes']} dk")
        else:
            lines.append(tf + ": hariç · " + lane["reason"])
    if len([lane for lane in report["inputs"].values() if lane["status"] == "included"]) < 2:
        lines.append("Kesişim hesabı için yeterli güncel zaman dilimi yok.")
    elif not report["intersections"]:
        lines.append("Bu görüntüde koşulları sağlayan kesişim bulunmadı.")
    else:
        lines.append(f"{len(report['intersections'])} hisse · tamamı {report['image_pages']} görselde ve CSV'de.")
    lines.append("Açık mum koşulları değişebilir. Kesişim sayısı başarı olasılığı değildir; emir veya ortak Stop/TP planı üretilmez.")
    text = "\n".join(lines)
    if len(text) > 4000:
        raise ValueError("intersection_text_exceeds_telegram_limit")
    return text


def render_csv(report):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(("Hisse", "Yon", "ZamanDilimiSayisi", "FarkliTaramaSayisi", "ZamanDilimleri",
                     "ZamanDilimindeTaramaKodlari", "ZitYonZamanDilimleri", "KaynakGozlemleri",
                     "HisseKaynakDurumlari", "Teyit"))
    states = {tf: {row["symbol"]: row for row in rows} for tf, rows in report["source_states"].items()}
    for item in report["intersections"]:
        observations = "; ".join(tf + "=" + report["inputs"][tf]["observation_end"]
                                 for tf in item["timeframes"])
        writer.writerow((item["symbol"], "LONG" if item["direction"] == "bullish" else "SHORT",
            item["timeframe_count"], item["count"], ",".join(item["timeframes"]), _frame_codes(item),
            ",".join(item["opposing_timeframes"]), observations,
            canonical({tf: states[tf][item["symbol"]] for tf in item["timeframes"]}), "CANLI / TEYITSIZ"))
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def render_pages(report):
    from PIL import Image, ImageDraw

    items = report["intersections"]
    pages = []
    for offset in range(0, len(items), PAGE_SIZE):
        group = items[offset:offset + PAGE_SIZE]
        wrapped = [textwrap.wrap(_frame_codes(item), width=95, break_long_words=False) or [""] for item in group]
        heights = [max(66, 26 * len(lines) + 24) for lines in wrapped]
        image = Image.new("RGB", (1840, 270 + sum(heights)), "#F1F5F9")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 1840, 95), fill="#112E4A")
        draw.text((30, 22), "ATC KESİŞİM · CANLI / TEYİTSİZ", font=_font(29, bold=True), fill="white")
        draw.text((30, 65), f"{report['session']} · Son bilinen durumlar · {len(items)} hisse · "
                  f"Sayfa {offset // PAGE_SIZE + 1}/{report['image_pages']}", font=_font(18), fill="white")
        for x, title in ((30, "HİSSE"), (190, "YÖN"), (330, "ZAMAN DİLİMLERİ"), (770, "HER DİLİMDE TARAMA KODLARI")):
            draw.text((x, 125), title, font=_font(19, bold=True), fill="#52697F")
        y = 165
        for index, (item, lines, height) in enumerate(zip(group, wrapped, heights, strict=True)):
            draw.rectangle((20, y, 1820, y + height), fill="white" if index % 2 == 0 else "#E5EDF5")
            draw.text((30, y + 16), item["symbol"], font=_font(22, bold=True), fill="#112E4A")
            draw.text((190, y + 16), "LONG" if item["direction"] == "bullish" else "SHORT",
                      font=_font(21, bold=True), fill="#087F5B" if item["direction"] == "bullish" else "#B42318")
            tf_lines = textwrap.wrap(", ".join(item["timeframes"]), width=34) or [""]
            draw.multiline_text((330, y + 16), "\n".join(tf_lines), font=_font(18), fill="#112E4A", spacing=5)
            draw.multiline_text((770, y + 14), "\n".join(lines), font=_font(17), fill="#112E4A", spacing=5)
            y += height
        draw.text((30, image.height - 74), "Her dilimde ≥2 aynı yönlü tarama · ≥2 dilim · eşit kapanış zamanı gerekmez.",
                  font=_font(19), fill="#52697F")
        draw.text((30, image.height - 42), "Tüm hisseler görsellerde ve CSV'de. Başarı olasılığı, emir veya Stop/TP planı değildir.",
                  font=_font(18), fill="#52697F")
        output = io.BytesIO()
        image.save(output, format="PNG")
        pages.append(output.getvalue())
    return pages


def prepare_report(packets_dir, sources_manifest, output_dir, *, now=None, bindings=None, hashes=None):
    now = live.aware(now or datetime.now(live.IST))
    sources = _read(Path(sources_manifest))
    if (sources.get("schema") != 1 or sources.get("repository") != REPOSITORY
            or sources.get("workflow") != WORKFLOW or not isinstance(sources.get("sources"), dict)
            or set(sources["sources"]) - set(CADENCE_MINUTES)):
        raise ValueError("trusted_source_manifest_required")
    output_dir = Path(output_dir)
    if (output_dir / "prepared-intersections.json").exists():
        raise ValueError("prepared_intersections_already_exist")
    hashes = live.implementation_hashes() if hashes is None else hashes
    if bindings is None:
        bindings = load_scanner_catalog(Path("config/scanners.toml"), calendar_version=ExchangeCalendarsXist().version)
    by_id = {binding.scanner.id: binding for binding in bindings}
    pinned = set(load_pinned(Path("config/atc_630_symbols.txt")))
    session = expected_session(now)
    by_tf, states, inputs = {}, {}, {}
    for tf in CADENCE_MINUTES:
        if tf not in sources["sources"]:
            inputs[tf] = {"status": "excluded", "reason": "no_acknowledged_source_packet"}
            continue
        try:
            details, states[tf], inputs[tf] = validate_packet(Path(packets_dir) / tf, tf,
                sources["sources"][tf], now=now, session=session, pinned=pinned, bindings=by_id, hashes=hashes)
            by_tf[tf] = details
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            known = str(error)
            reason = known if re.fullmatch(r"[a-z][a-z0-9_]{2,90}", known) else "invalid_source_packet"
            inputs[tf] = {"status": "excluded", "reason": reason}
    ranked = cross_timeframe_intersections(by_tf, limit=None) if len(by_tf) >= 2 else []
    report = {"version": VERSION, "prepared_at": now.isoformat(), "session": session.isoformat(),
        "provisional": True, "source_state_semantics": "latest_known_with_per_timeframe_observation_age",
        "criteria": {"same_direction_rules_per_timeframe": 2, "same_direction_timeframes": 2,
                     "equal_close_timestamps_required": False, "direction_ties_excluded": True},
        "inputs": inputs, "source_states": states, "intersections": ranked,
        "image_pages": (len(ranked) + PAGE_SIZE - 1) // PAGE_SIZE,
        "stop_tp_plans_mixed": False, "confirmed_store_writes": 0, "orders_sent": 0}
    report["source_set_sha256"] = sha256(canonical({
        tf: inputs[tf]["packet_sha256"] for tf in sorted(by_tf)}).encode()).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / BASE_FILES[0], report)
    (output_dir / BASE_FILES[1]).write_text(render_text(report), encoding="utf-8")
    (output_dir / BASE_FILES[2]).write_bytes(render_csv(report))
    pages = render_pages(report)
    names = [*BASE_FILES]
    for index, data in enumerate(pages, 1):
        name = f"intersections-{index:03}.png"
        (output_dir / name).write_bytes(data)
        names.append(name)
    atomic_json(output_dir / "prepared-intersections.json", {"version": VERSION,
        "source_set_sha256": report["source_set_sha256"],
        "implementation_files": hashes, "files": {name: sha256((output_dir / name).read_bytes()).hexdigest() for name in names}})
    return report


def publish_report(folder, *, now=None, environ=None, transport=None, previous_receipt=None):
    folder, env = Path(folder), os.environ if environ is None else environ
    now = live.aware(now or datetime.now(live.IST))
    if int(env.get("TELEGRAM_CHAT_ID", "0")) != live.CHAT or int(env.get("TELEGRAM_TOPIC_INTERSECTIONS", "0")) != TOPIC:
        raise ValueError("existing_intersection_destination_required")
    manifest_raw = (folder / "prepared-intersections.json").read_bytes()
    manifest = _read(folder / "prepared-intersections.json")
    if manifest.get("version") != VERSION or manifest.get("implementation_files") != live.implementation_hashes():
        raise ValueError("intersection_implementation_changed")
    report = _read(folder / BASE_FILES[0])
    pages = report.get("image_pages")
    if type(pages) is not int or not 0 <= pages <= 32:
        raise ValueError("invalid_intersection_page_count")
    expected = {*BASE_FILES, *(f"intersections-{index:03}.png" for index in range(1, pages + 1))}
    if set(manifest.get("files", {})) != expected:
        raise ValueError("intersection_file_set_changed")
    for name in expected:
        path = folder / name
        if path.is_symlink() or sha256(path.read_bytes()).hexdigest() != manifest["files"][name]:
            raise ValueError("intersection_file_hash_changed")
    prepared = live.aware(datetime.fromisoformat(report["prepared_at"]))
    if (report.get("version") != VERSION or not report.get("provisional")
            or report.get("session") != expected_session(now).isoformat()
            or not prepared <= now <= prepared + timedelta(minutes=30)):
        raise ValueError("intersection_snapshot_expired")
    packet_hash = sha256(manifest_raw).hexdigest()
    receipt_path = folder / "publication-receipt.json"
    receipt = _read(receipt_path) if receipt_path.exists() else {"packet_sha256": packet_hash,
        "chat_id": live.CHAT, "topic_id": TOPIC, "acknowledged": {}}
    payloads = {"text": {"text": (folder / BASE_FILES[1]).read_text(encoding="utf-8")}}
    for index in range(1, pages + 1):
        name = f"intersections-{index:03}.png"
        payloads[f"photo-{index:03}"] = {"_method": "sendPhoto",
            "photo_base64": base64.b64encode((folder / name).read_bytes()).decode("ascii"),
            "filename": name, "caption": f"CANLI / TEYİTSİZ · {len(report['intersections'])} kesişim hissesi · sayfa {index}/{pages} · tüm liste CSV'de."}
    payloads["csv"] = {"_method": "sendDocument",
        "document_base64": base64.b64encode((folder / BASE_FILES[2]).read_bytes()).decode("ascii"),
        "filename": "ATC_KESISIM_CANLI_TEYITSIZ.csv", "caption": "Tüm uygun hisseler · kaynak gözlemleri · CANLI / TEYİTSİZ · ortak Stop/TP veya emir değildir."}
    source_set = report.get("source_set_sha256")
    if (not re.fullmatch(r"[0-9a-f]{64}", str(source_set))
            or manifest.get("source_set_sha256") != source_set):
        raise ValueError("intersection_source_set_identity_changed")
    previous = _read(Path(previous_receipt)) if previous_receipt is not None else (
        receipt if receipt.get("status") == "already_sent" else None)
    if previous is not None and previous.get("source_set_sha256") == source_set:
        if (previous.get("version") != VERSION or previous.get("chat_id") != live.CHAT
                or previous.get("topic_id") != TOPIC or previous.get("status") not in {"sent", "already_sent"}
                or set(previous.get("acknowledged", {})) != set(payloads)
                or previous.get("expected_acknowledgements") != list(payloads)
                or any(type(value) is not int or value <= 0 for value in previous["acknowledged"].values())):
            raise ValueError("complete_previous_intersection_receipt_required")
        skipped = {**previous, "status": "already_sent", "prepared_packet_skipped_sha256": packet_hash}
        atomic_json(receipt_path, skipped)
        return skipped
    if (receipt.get("packet_sha256") != packet_hash or receipt.get("chat_id") != live.CHAT
            or receipt.get("topic_id") != TOPIC or not isinstance(receipt.get("acknowledged"), dict)
            or set(receipt["acknowledged"]) - set(payloads)
            or any(type(value) is not int or value <= 0 for value in receipt["acknowledged"].values())):
        raise ValueError("intersection_receipt_identity_changed")
    sender = transport if transport is not None else live.HttpxTelegramTransport(env["TELEGRAM_BOT_TOKEN"])
    receipt.update(version=VERSION, source_set_sha256=source_set, expected_acknowledgements=list(payloads))
    for key, payload in payloads.items():
        if key in receipt["acknowledged"]:
            continue
        message_id = sender.send(chat_id=live.CHAT, message_thread_id=TOPIC, payload=payload)
        if type(message_id) is not int or message_id <= 0:
            raise ValueError("telegram_acknowledgement_required")
        receipt["acknowledged"][key] = message_id
        receipt["updated_at"] = now.isoformat()
        atomic_json(receipt_path, receipt)
    receipt["status"] = "sent"
    atomic_json(receipt_path, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--publish-from", type=Path)
    parser.add_argument("--packets-dir", type=Path)
    parser.add_argument("--sources-manifest", type=Path)
    parser.add_argument("--previous-receipt", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("runtime_artifacts/intersections"))
    args = parser.parse_args(argv)
    if args.prepare:
        if args.packets_dir is None or args.sources_manifest is None:
            parser.error("--packets-dir and --sources-manifest are required for preparation")
        report = prepare_report(args.packets_dir, args.sources_manifest, args.output_dir)
        print(canonical({"status": "prepared_not_sent", "intersections": len(report["intersections"]),
                         "image_pages": report["image_pages"], "inputs": report["inputs"]}))
    else:
        print(canonical(publish_report(args.publish_from, previous_receipt=args.previous_receipt)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
