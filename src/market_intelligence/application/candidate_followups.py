"""Durable selected-symbol work for analysis, chart and report topics."""

from __future__ import annotations

from market_intelligence.core.identity import canonical_json, stable_hash

FOLLOWUP_TIMEFRAMES = frozenset({"1h", "4h", "1d", "1wk"})


def enqueue_candidate_followups(connection, timeframe, target, ranked, topic_id):
    if timeframe not in FOLLOWUP_TIMEFRAMES:
        return 0
    count = 0
    for item in ranked[:20]:
        for command in ("analiz", "grafik", "rapor"):
            # Financial reports are daily documents: deduplicate across candidate timeframes.
            identity = {
                "kind": "scan_candidate_v1",
                "symbol": item["symbol"],
                "command": command,
                "target": target.date().isoformat() if command == "rapor" else target.isoformat(),
            }
            if command != "rapor":
                identity["timeframe"] = timeframe
            context = {
                "automatic": True,
                "trigger_timeframe": timeframe,
                "trigger_bar": target.isoformat(),
                "scanners": item["scanners"],
                "direction": item["direction"],
            }
            row = connection.execute(
                "INSERT INTO command_jobs(command_name,instrument_id,symbol_at_request,requested_by,requested_topic,request_key,context) "
                "SELECT %s,s.instrument_id,%s,0,%s,%s,%s::jsonb FROM instrument_symbols s "
                "WHERE upper(s.symbol)=upper(%s) AND s.valid_from<=%s AND (s.valid_to IS NULL OR s.valid_to>=%s) "
                "ORDER BY s.valid_from DESC LIMIT 1 ON CONFLICT DO NOTHING RETURNING job_id",
                (
                    command,
                    item["symbol"],
                    topic_id,
                    stable_hash(identity),
                    canonical_json(context),
                    item["symbol"],
                    target.date(),
                    target.date(),
                ),
            ).fetchone()
            count += row is not None
    return count


def candidate_label(context):
    if not context.get("automatic") or not context.get("trigger_timeframe"):
        return ""
    from market_intelligence.application.live_scans import LABELS

    names = ", ".join(LABELS.get(x, x) for x in context.get("scanners", []))
    return f"{context['trigger_timeframe']} kesişim adayı | {context['trigger_bar']}\nTaramalar: {names}\n"
