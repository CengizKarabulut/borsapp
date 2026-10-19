"""Download corrected, separately versioned E research inputs; never analyze.

The command is inert on import. It loads the explicitly selected installed E
runtime, checks reviewed hashes and the v2 adjustment seam BEFORE writing, then
uses the existing local feed account. The old history store is never opened.
No scanner, backtest, message, order, profile export or activation is called.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import importlib.metadata
import inspect
import json
import re
import sys
import textwrap
from contextlib import nullcontext
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

VERSION = "corrected-e-history-collector-20261019-v2"
OUTPUT_RELATIVE = "results/exit-research-adjusted-v2"
SDK_VERSION = "0.11.0"
CAPTURE_SOURCE = "borsapy-tradingview-adjust-true-0.11.0-v2"
CAPTURE_METHOD = "pinned-sdk-history-explicit-start-v2"
CAPTURE_CONTRACT = "pinned-sdk-adjust-true-auto-adjust-false-v2"
DEFAULT_VINTAGE = "2026-10-19"
INTERVALS = ("1d", "1h")
EXPECTED_PROVENANCE = {
    "price_basis": "split_adjusted", "sdk_version": SDK_VERSION,
    "provider": "borsapy", "adjustment": "splits", "method": CAPTURE_CONTRACT,
    "history_parameters": {"adjust": True, "auto_adjust": False, "actions": False},
}
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,15}$")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value):
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError("reviewed_sha256_required")
    return value


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("canonical_date_required")
    return value


def _safe_path(path):
    path = Path(path).absolute()
    for item in (*reversed(path.parents), path):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("redirected_capture_path")
    return path


def validate_capture_seam(market_data, history_store, *, source=None):
    """Pure contract probe; no provider call, authentication or file write."""
    if _json(market_data._split_history_provenance()) != _json(EXPECTED_PROVENANCE):
        raise ValueError("adjustment_provenance_contract_mismatch")
    accepted = market_data._verified_split_provenance(EXPECTED_PROVENANCE)
    if _json(accepted) != _json(EXPECTED_PROVENANCE):
        raise ValueError("adjustment_validator_contract_mismatch")
    wrong = {**EXPECTED_PROVENANCE,
             "history_parameters": {"adjust": False, "auto_adjust": False, "actions": False}}
    numeric = {**EXPECTED_PROVENANCE,
               "history_parameters": {"adjust": 1, "auto_adjust": 0, "actions": 0}}
    if (market_data._verified_split_provenance(wrong) is not None
            or market_data._verified_split_provenance(numeric) is not None):
        raise ValueError("adjustment_validator_accepts_wrong_contract")
    for name, expected in (("SDK_VERSION", SDK_VERSION), ("CAPTURE_SOURCE", CAPTURE_SOURCE),
                           ("CAPTURE_METHOD", CAPTURE_METHOD), ("CAPTURE_CONTRACT", CAPTURE_CONTRACT)):
        if getattr(history_store, name, None) != expected:
            raise ValueError("history_store_capture_contract_mismatch")
    response = SimpleNamespace(attrs={"atc_price_provenance": EXPECTED_PROVENANCE})
    if _json(history_store._capture_contract(response)) != _json(EXPECTED_PROVENANCE):
        raise ValueError("history_store_drops_capture_provenance")
    # Reviewed whole-file hashes bind the exact implementation. This extra
    # semantic check catches an accidentally pinned nominal-price request seam.
    source = source if source is not None else inspect.getsource(inspect.unwrap(market_data._history))
    tree = ast.parse(textwrap.dedent(source))
    correct = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "kwargs" for target in node.targets):
            continue
        values = {key.value: value for key, value in zip(node.value.keys, node.value.values, strict=True)
                  if isinstance(key, ast.Constant) and isinstance(key.value, str)}
        flags = {key: values.get(key) for key in ("adjust", "auto_adjust", "actions")}
        if all(isinstance(node, ast.Constant) and type(node.value) is bool
               for node in flags.values()):
            correct = {key: node.value for key, node in flags.items()} == EXPECTED_PROVENANCE["history_parameters"]
            if correct:
                break
    if not correct:
        raise ValueError("history_request_not_explicit_adjust_true")
    return dict(EXPECTED_PROVENANCE)


def load_installed_runtime(root, *, expected_identity, expected_market_data, expected_history_store):
    """Explicit E import and read-only attestation before any collection writes."""
    root = _safe_path(root).resolve(strict=True)
    expected = {
        "src/market_intelligence/native/market_data.py": _digest(expected_market_data),
        "src/market_intelligence/research/history_store.py": _digest(expected_history_store),
    }
    _digest(expected_identity)
    actual = {}
    for relative, digest in expected.items():
        path = _safe_path(root / relative)
        actual[relative] = sha256(path.read_bytes()).hexdigest()
        if actual[relative] != digest:
            raise ValueError("installed_capture_file_hash_mismatch")
    package = root / "src/market_intelligence"
    for name, module in tuple(sys.modules.items()):
        if name == "market_intelligence" or name.startswith("market_intelligence."):
            location = getattr(module, "__file__", None)
            if location is not None and not Path(location).resolve().is_relative_to(package):
                raise ValueError("different_runtime_already_imported")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "src"))
    market_data = importlib.import_module("market_intelligence.native.market_data")
    history_store = importlib.import_module("market_intelligence.research.history_store")
    workflow = importlib.import_module("market_intelligence.research.exit_workflow")
    auth = importlib.import_module("market_intelligence.native.manual_feed_auth")
    runtime = importlib.import_module("market_intelligence.native.runtime")
    for module in (market_data, history_store, workflow, auth, runtime):
        if not Path(module.__file__).resolve().is_relative_to(package):
            raise ValueError("installed_module_outside_selected_root")
    if importlib.metadata.version("borsapy") != SDK_VERSION:
        raise ValueError("installed_sdk_version_mismatch")
    identity = workflow.code_identity(root)
    if identity != expected_identity:
        raise ValueError("installed_runtime_identity_mismatch")
    contract = validate_capture_seam(market_data, history_store)
    attestation = {"schema": 1, "version": VERSION, "runtime_identity": identity,
                   "collector_implementation_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                   "source_files": actual, "feed_contract": contract,
                   "capture_source": CAPTURE_SOURCE, "capture_method": CAPTURE_METHOD,
                   "sdk_version": SDK_VERSION,
                   "corporate_action_validation": "request_contract_not_event_by_event",
                   "old_history_store_opened": False,
                   "analysis_enabled": False, "activation_enabled": False}
    return SimpleNamespace(root=root, market_data=market_data, history_store=history_store,
                           workflow=workflow, auth=auth, runtime=runtime, attestation=attestation)


def collection_contract(symbols, attestation, *, vintage=DEFAULT_VINTAGE, start="1985-01-01"):
    selected = list(symbols)
    if (not selected or len(selected) != len(set(selected))
            or not all(isinstance(symbol, str) and _SYMBOL.fullmatch(symbol) for symbol in selected)):
        raise ValueError("unique_valid_capture_symbols_required")
    _day(vintage)
    _day(start)
    if start > vintage:
        raise ValueError("capture_start_after_vintage")
    if (attestation.get("version") != VERSION
            or _json(attestation.get("feed_contract")) != _json(EXPECTED_PROVENANCE)
            or attestation.get("capture_source") != CAPTURE_SOURCE
            or attestation.get("analysis_enabled") is not False
            or attestation.get("activation_enabled") is not False):
        raise ValueError("validated_startup_attestation_required")
    document = {"schema": 1, "version": VERSION, "symbols": selected,
                "symbol_count": len(selected), "intervals": list(INTERVALS),
                "series_count": len(selected)*len(INTERVALS), "workers": 1,
                "requested_start": start, "vintage": vintage,
                "output_relative": OUTPUT_RELATIVE, "runtime": attestation,
                "history_exhaustion": "unproven", "old_history_reuse_allowed": False,
                "research_jobs_started": 0, "profiles_activated": 0,
                "telegram_messages_sent": 0, "real_orders_sent": 0}
    return {**document, "contract_sha256": sha256(_json(document).encode()).hexdigest()}


def validate_store_namespace(store):
    """A new directory alone is insufficient if someone copied old objects in."""
    histories = store.manifest.get("histories", [])
    requests = store.manifest.get("requests", {})
    if any(reference.get("source") != CAPTURE_SOURCE for reference in histories):
        raise ValueError("legacy_history_in_corrected_namespace")
    if any(":contract-"+CAPTURE_CONTRACT+":vintage-" not in key for key in requests):
        raise ValueError("legacy_request_in_corrected_namespace")


def collect_series(store, *, symbols, fetcher, contract, persist, should_stop,
                   now=lambda: datetime.now(UTC), progress=None, failure_limit=3,
                   account_context=nullcontext):
    """Sequential resumable capture loop with injected, testable dependencies.

    Each request is attempted once in a run. A later run of the same vintage
    revalidates/reuses successful corrected objects and retries failed ones via
    HistoryStore.capture. Three consecutive failures halt the account requests.
    Exceptions are recorded as fixed types; provider messages are never emitted.
    """
    if failure_limit != 3:
        raise ValueError("three_failure_guard_required")
    selected = list(symbols)
    if selected != contract.get("symbols") or contract.get("version") != VERSION:
        raise ValueError("collection_contract_symbols_mismatch")
    payload = {key: value for key, value in contract.items() if key != "contract_sha256"}
    if sha256(_json(payload).encode()).hexdigest() != contract.get("contract_sha256"):
        raise ValueError("collection_contract_hash_mismatch")
    validate_store_namespace(store)
    state = {"schema": 1, "version": VERSION, "status": "running", "phase": "download_only",
             "started_at": now().isoformat(), "updated_at": now().isoformat(),
             "contract_sha256": contract["contract_sha256"],
             "symbol_count": len(selected), "intervals": list(INTERVALS),
             "expected_series": len(selected)*len(INTERVALS),
             "completed_series": 0, "failed_series": 0, "reused_series": 0,
             "attempted_series": 0, "remaining_series": len(selected)*len(INTERVALS),
             "consecutive_failures": 0, "download_results": [],
             "vintage": contract["vintage"], "requested_start": contract["requested_start"],
             "feed_contract": EXPECTED_PROVENANCE,
             "history_exhaustion": "unproven", "research_jobs_started": 0,
             "profiles_activated": 0, "telegram_messages_sent": 0, "real_orders_sent": 0}

    def save():
        state["updated_at"] = now().isoformat()
        persist(state)

    try:
        save()
        if should_stop():
            raise InterruptedError("capture_stop_marker")
        with account_context():
            for symbol in selected:
                for interval in INTERVALS:
                    if should_stop():
                        raise InterruptedError("capture_stop_marker")
                    state["current_request"] = {"symbol": symbol, "interval": interval}
                    save()
                    if progress:
                        progress(f"{state['attempted_series']+1}/{state['expected_series']} {symbol} {interval}")
                    result = store.capture(symbol, interval, fetcher,
                                           requested_start=contract["requested_start"], vintage=contract["vintage"])
                    # HistoryStore emits only fixed public error codes. Never
                    # copy arbitrary exception text into collector output.
                    if result.get("status") not in ("completed", "failed", "paused"):
                        raise ValueError("unsupported_capture_result")
                    if result.get("status") == "completed" and result.get("reference", {}).get("source") != CAPTURE_SOURCE:
                        raise ValueError("wrong_capture_source_returned")
                    if result.get("status") == "paused":
                        raise InterruptedError("history_store_paused")
                    state["download_results"].append(result)
                    state["attempted_series"] += 1
                    state["remaining_series"] = state["expected_series"]-state["attempted_series"]
                    if result["status"] == "completed":
                        state["completed_series"] += 1
                        state["reused_series"] += bool(result.get("reused"))
                        state["consecutive_failures"] = 0
                    else:
                        state["failed_series"] += 1
                        state["consecutive_failures"] += 1
                    save()
                    if state["consecutive_failures"] >= failure_limit:
                        state["stop_reason"] = "three_consecutive_provider_failures"
                        state["status"] = "incomplete"
                        return state
        state["status"] = "completed" if state["failed_series"] == 0 else "incomplete"
        state.pop("current_request", None)
    except (KeyboardInterrupt, InterruptedError):
        state["status"] = "paused"
        state["stop_reason"] = "cooperative_stop_or_interrupt"
    except Exception as error:
        state["status"] = "incomplete"
        state["failure_code"] = type(error).__name__
    finally:
        try:
            save()
        except OSError:
            state["status"] = "incomplete"
            state["summary_write_failed"] = True
    return state


def _write_json(path, value):
    """Atomic own-file update; no fixed shared temporary filename."""
    path = _safe_path(path)
    temporary = path.with_name(path.name+"."+uuid4().hex+".tmp")
    try:
        temporary.write_text(_json(value)+"\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def run_installed(runtime, *, vintage=DEFAULT_VINTAGE, start="1985-01-01", symbols=None):
    """Only CLI entry after explicit hash/seam verification; owns one lock."""
    root = runtime.root
    selected = runtime.workflow.read_symbols(root, symbols)
    if symbols is None and len(selected) != 631:
        raise ValueError("expected_frozen_631_symbol_universe")
    contract = collection_contract(selected, runtime.attestation, vintage=vintage, start=start)
    output = _safe_path(root / OUTPUT_RELATIVE)
    if not output.is_relative_to(root) or output == root / "results/exit-research":
        raise ValueError("separate_corrected_output_required")
    _safe_path(root / "data").mkdir(parents=True, exist_ok=True)
    with runtime.runtime.process_lock(root, "exit-research"):
        output.mkdir(parents=True, exist_ok=True)
        contract_path = _safe_path(output / "collector-contract.json")
        if contract_path.exists():
            previous = json.loads(contract_path.read_text(encoding="utf-8"))
            if previous != contract:
                raise ValueError("corrected_collection_contract_changed")
        else:
            _write_json(contract_path, contract)
        store = runtime.history_store.HistoryStore(_safe_path(output / "history"))
        validate_store_namespace(store)
        stop_file = _safe_path(output / "capture.stop")
        return collect_series(
            store, symbols=selected, contract=contract,
            fetcher=lambda symbol, interval, began: runtime.market_data._history(
                "borsapy", symbol, interval, start=began, bars=100000, cache_root=None),
            persist=lambda state: _write_json(output / "capture-summary.json", state),
            should_stop=stop_file.exists, progress=print,
            account_context=lambda: runtime.auth.feed_auth_context(root))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-runtime-identity", required=True)
    parser.add_argument("--expected-market-data-sha256", required=True)
    parser.add_argument("--expected-history-store-sha256", required=True)
    parser.add_argument("--vintage", default=DEFAULT_VINTAGE)
    parser.add_argument("--start", default="1985-01-01")
    parser.add_argument("--symbols", help="Optional explicitly bounded trial; default frozen 631 symbols")
    arguments = parser.parse_args(argv)
    try:
        runtime = load_installed_runtime(
            arguments.root, expected_identity=arguments.expected_runtime_identity,
            expected_market_data=arguments.expected_market_data_sha256,
            expected_history_store=arguments.expected_history_store_sha256)
        state = run_installed(runtime, vintage=arguments.vintage, start=arguments.start,
                              symbols=arguments.symbols)
    except Exception as error:
        print("Capture did not start:", type(error).__name__)
        return 1
    print("Corrected history capture:", state["status"])
    print("Completed:", state["completed_series"], "/", state["expected_series"])
    return 0 if state["status"] == "completed" else 2 if state["status"] == "paused" else 1


if __name__ == "__main__":
    raise SystemExit(main())
