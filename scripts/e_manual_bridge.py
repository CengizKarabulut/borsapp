"""Local E adapter for an explicitly invoked manual scan.

The frozen scanner modules, findings, plans, locks and Telegram delivery path
are unchanged. Scoped hooks expand the text formatter and attach confirmed
support/resistance from this run's verified frame archives. The adapter neither
activates profiles nor sends messages on import. --preview delegates to the
installed no-scan/no-send preview.
"""
from __future__ import annotations

import argparse
import importlib
import math
import sys
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
from pathlib import Path

sys.dont_write_bytecode = True
VERSION = "e-manual-support-context-20261018-v3"
EXPECTED_MANUAL_BATCH_SHA256 = "e7ad01a0cf2c3ecd7aa1dda7fefdf86a25a45afd0123bf957933a987cee271c1"
EXPECTED_RUNTIME_CODE_IDENTITY = "a97f9342eac134ea81bd0a051efcc84ddb9da2fb69562f895842ecf998171bf5"


def _unavailable_plan_line(item):
    plan = item.get("plan")
    if isinstance(plan, dict) and plan.get("status") == "unavailable":
        return " | Stop/TP: uygulanabilir plan yok"
    return ""


def support_context_line(item):
    """Keep confirmed structure separate from the selected trade scenario."""
    context = item.get("support_resistance")
    if not isinstance(context, dict):
        return ""
    if context.get("status") == "insufficient_history":
        return " | D/R: kapanmış geçmiş yetersiz"
    if context.get("status") != "ready":
        return " | D/R: doğrulanmış görünüm yok"
    levels = []
    for key, label in (("supports", "Destek"), ("resistances", "Direnç")):
        rows = context.get(key, [])
        values = [row.get("price") for row in rows if isinstance(row, dict)]
        values = [value for value in values if _number(value)]
        levels.append(label + (" " + "/".join(format(v, ".8g") for v in values) if values else " —"))
    return " | D/R (kapanmış mum): " + " · ".join(levels)


def enrich_result(result, job, root, *, archive_reader=None, support_builder=None):
    """Use the immutable inputs of this run, never a fresh quote/history fetch.

    Read failures affect only context, never the finding, scenario, calibration
    decision or scan-coverage count. No arbitrary file path is opened here.
    """
    if archive_reader is None:
        from market_intelligence.native.scan_archive import read_frame_archive
        archive_reader = read_frame_archive
    if support_builder is None:
        if __package__:
            from .atc_support_resistance import build_support_resistance
        else:
            from atc_support_resistance import build_support_resistance
        support_builder = build_support_resistance
    observations = {}
    for observed in result.get("observations", []):
        if isinstance(observed, dict):
            key = (observed.get("symbol"), observed.get("snapshot_id"))
            observations.setdefault(key, []).append(observed)
    contexts, frames = {}, {}
    def context_for(item):
        key = item.get("symbol"), item.get("snapshot_id")
        failed = {"status": "unavailable_data_quality", "reason": "exact_archive_unavailable"}
        rows = observations.get(key, [])
        if len(rows) != 1:
            contexts[key] = failed
            return failed
        observed = rows[0]
        # Validate EVERY finding before using a frame-level cache. One malformed
        # finding must neither borrow a ready context nor poison valid siblings.
        if (item.get("timeframe") != job["timeframe"]
                or item.get("observed_at") != observed.get("observed_at")
                or item.get("bar_time") != observed.get("bar_end")
                or item.get("bar_open") != observed.get("bar_open")
                or type(observed.get("partial")) is not bool
                or item.get("preliminary") is not observed["partial"]
                or item.get("bar_confirmed") is not (not observed["partial"])):
            return {**failed, "reason": "finding_archive_identity_mismatch"}
        if key in contexts:
            return contexts[key]
        reference = observed.get("frame_archive")
        try:
            if not isinstance(reference, dict) or reference.get("snapshot_id") != key[1]:
                raise ValueError("snapshot_mismatch")
            digest = reference.get("sha256")
            if digest not in frames:
                frames[digest] = archive_reader(root, job["run_id"], reference)
            frame = frames[digest]
            if (frame.snapshot_id != key[1] or frame.symbol_at_snapshot != key[0]
                    or frame.timeframe.value != job["timeframe"]
                    or item.get("timeframe") != job["timeframe"]
                    or frame.source != observed.get("source")
                    or frame.price_basis.value != observed.get("price_basis")
                    or item.get("observed_at") != observed.get("observed_at")
                    or frame.through_bar_time.isoformat() != observed.get("bar_end")
                    or item.get("bar_time") != observed.get("bar_end")
                    or frame.bars[-1].open_time.isoformat() != observed.get("bar_open")
                    or item.get("bar_open") != observed.get("bar_open")
                    or frame.is_partial is not observed.get("partial")
                    or item.get("preliminary") is not frame.is_partial
                    or item.get("bar_confirmed") is not (not frame.is_partial)):
                raise ValueError("exact_archive_identity_mismatch")
            as_of = datetime.fromisoformat(observed["observed_at"])
            context = support_builder(frame, as_of=as_of)
            contexts[key] = context
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            contexts[key] = failed
        return contexts[key]
    details = [dict(item, support_resistance=context_for(item)) for item in result.get("details", [])]
    enriched = dict(result, details=details, findings=details)
    enriched["support_resistance_context"] = {
        "version": VERSION, "role": "confirmed_structure_context_only",
        "trade_plans_unchanged": True, "snapshots_read": len(frames),
        "ready": sum(c.get("status") == "ready" for c in contexts.values()),
        "unavailable": sum(c.get("status") != "ready" for c in contexts.values()),
        "unavailable_findings": sum(item["support_resistance"].get("status") != "ready" for item in details),
    }
    return enriched


def verify_formatter_source(root):
    """Fail before importing or running an unexpected installed formatter."""
    root = Path(root).resolve(strict=True)
    source = root / "src/market_intelligence/native/manual_batch.py"
    if not source.resolve(strict=True).is_relative_to(root):
        raise ValueError("manual_formatter_outside_runtime")
    if sha256(source.read_bytes()).hexdigest() != EXPECTED_MANUAL_BATCH_SHA256:
        raise ValueError("manual_formatter_identity_mismatch")
    return source.resolve(strict=True)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _price(value):
    rendered = f"{value:.2f}"
    return format(value, ".8g") if float(rendered) == 0 else rendered


def format_plan_line(item, fallback):
    """Expand the nearest existing plan only; never mix or invent targets.

    Select with the original entry/stop/TP1 distance and tie ordering first.
    If that same scenario lacks valid ordered TP2/TP3, preserve the exact legacy
    rendering rather than selecting a farther, different plan.
    """
    direction = item.get("direction")
    if direction not in ("bullish", "bearish"):
        return fallback(item)
    side = "long" if direction == "bullish" else "short"
    plan = item.get("plan")
    scenarios = plan.get("scenarios", []) if isinstance(plan, dict) else []
    if not isinstance(scenarios, (list, tuple)):
        return fallback(item)
    candidates = []
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict) or scenario.get("side") != side:
            continue
        values = tuple(scenario.get(key) for key in ("entry", "stop", "tp1"))
        if not all(_number(value) for value in values):
            continue
        entry, stop, tp1 = values
        if not (stop < entry < tp1 if side == "long" else tp1 < entry < stop):
            continue
        key = (abs(entry - stop) + abs(tp1 - entry), abs(entry - stop), values, index)
        candidates.append((key, scenario))
    if not candidates:
        return _unavailable_plan_line(item) or fallback(item)
    scenario = min(candidates, key=lambda candidate: candidate[0])[1]
    entry, stop, tp1, tp2, tp3 = (
        scenario.get(key) for key in ("entry", "stop", "tp1", "tp2", "tp3")
    )
    if not all(_number(value) for value in (entry, stop, tp1, tp2, tp3)):
        return fallback(item)
    ordered = stop < entry < tp1 < tp2 < tp3 if side == "long" else tp3 < tp2 < tp1 < entry < stop
    if not ordered:
        return fallback(item)
    calibrated = (
        plan.get("status") == "calibrated_reference"
        and scenario.get("stop_basis") == "validated_fixed_atr_multiplier"
        and isinstance(scenario.get("profile_id"), str)
        and bool(scenario["profile_id"])
    )
    label = "Kalibre referans" if calibrated else "Referans"
    distances = (abs(stop - entry) / entry * 100.0, abs(tp3 - entry) / entry * 100.0)
    distance_line = ""
    if all(math.isfinite(value) and value > 0 for value in distances):
        def percentage(value):
            rendered = f"{value:.2f}"
            return format(value, ".4g") if len(rendered) > 11 else rendered
        distance_line = (f" · Stop mesafesi %{percentage(distances[0])}"
                         f" · TP3 mesafesi %{percentage(distances[1])}")
    return (
        f" | Giriş ref. {_price(entry)} · Stop {_price(stop)} · TP1 {_price(tp1)}"
        f" · TP2 {_price(tp2)} · TP3 {_price(tp3)} · {label}{distance_line}"
    )


@contextmanager
def presentation_adapter(module, *, root=None):
    """Restore both hooks even on cancellation; the native core stays frozen."""
    original = module._plan_line
    original_run = module.run_once if root is not None else None

    def expanded(item):
        return format_plan_line(item, original) + support_context_line(item)

    def with_context(*args, **kwargs):
        if kwargs.get("preview"):
            return original_run(*args, **kwargs)
        from market_intelligence.native.engine import execute_scan
        executor = kwargs.get("executor") or execute_scan
        def enriched(job, scan_root, **execution_options):
            result = executor(job, scan_root, **execution_options)
            return enrich_result(result, job, scan_root)
        return original_run(*args, **dict(kwargs, executor=enriched))

    module._plan_line = expanded
    if original_run is not None:
        module.run_once = with_context
    try:
        yield
    finally:
        module._plan_line = original
        if original_run is not None:
            module.run_once = original_run


def run_installed(root, arguments):
    """Delegate only manual-batch; no controller, queue or order action added."""
    root = Path(root).resolve(strict=True)
    source = verify_formatter_source(root)
    source_root = str(root / "src")
    sys.path.insert(0, source_root)
    try:
        batch = importlib.import_module("market_intelligence.native.manual_batch")
        manual = importlib.import_module("market_intelligence.manual")
        if Path(batch.__file__).resolve() != source:
            raise ValueError("manual_formatter_import_origin_mismatch")
        if Path(manual.__file__).resolve() != root / "src/market_intelligence/manual.py":
            raise ValueError("manual_entrypoint_import_origin_mismatch")
        from market_intelligence.research.exit_workflow import code_identity
        if code_identity(root) != EXPECTED_RUNTIME_CODE_IDENTITY:
            raise ValueError("manual_runtime_identity_mismatch")
        # Check again after import so a concurrent deployment cannot replace the
        # formatter between the first preflight and the scoped presentation use.
        verify_formatter_source(root)
        with presentation_adapter(batch, root=root):
            return manual.main(["--root", str(root), "manual-batch", *arguments])
    finally:
        sys.path.remove(source_root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("action", choices=("manual-batch",))
    arguments, forwarded = parser.parse_known_args(argv)
    try:
        return run_installed(arguments.root, forwarded)
    except (OSError, ValueError) as error:
        known = {
            "manual_formatter_identity_mismatch",
            "manual_formatter_import_origin_mismatch",
            "manual_entrypoint_import_origin_mismatch",
            "manual_formatter_outside_runtime",
            "manual_runtime_identity_mismatch",
        }
        reason = str(error) if str(error) in known else "manual_presentation_preflight_failed"
        print("Manuel Stop/TP gösterimi başlatılamadı: " + reason, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
