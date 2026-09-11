"""Official KAP financial disclosures, immutable source files and typed facts.

No fuzzy matching is used for accounting facts. Empty/nil cells remain absent.
Comparative periods retain the reporting-date purchasing-power basis.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from bs4 import BeautifulSoup

from market_intelligence.fundamentals.archive import FinancialArchive
from market_intelligence.fundamentals.providers import (
    ALIASES,
    FinancialSnapshot,
    _snapshot_from_frames,
)
from market_intelligence.news.kap import KAP_BASE_URL, KAP_DETAIL_URL, KAP_DISCLOSURES_URL

# Only canonical total concepts; parent/child subtotals are not added together.
CONCEPTS = {
    "revenue": ("ifrs-full_Revenue",),
    "gross_profit": ("ifrs-full_GrossProfit",),
    "operating_profit": ("ifrs-full_ProfitLossFromOperatingActivities",),
    "net_income": ("ifrs-full_ProfitLossAttributableToOwnersOfParent",),
    "cfo": ("ifrs-full_CashFlowsFromUsedInOperatingActivities",),
    "capex": (
        "kap-fr_PurchaseOfPropertyPlantEquipmentAndIntangibleAssetsClassifiedAsInvestingActivities",
    ),
    "depreciation": ("ifrs-full_AdjustmentsForDepreciationAndAmortisationExpense",),
    "cash": ("ifrs-full_CashAndCashEquivalents",),
    "assets": ("ifrs-full_Assets",),
    "liabilities": ("ifrs-full_Liabilities",),
    "current_assets": ("ifrs-full_CurrentAssets",),
    "current_liabilities": ("ifrs-full_CurrentLiabilities",),
    "equity": ("ifrs-full_EquityAttributableToOwnersOfParent",),
    "short_debt": ("kap-fr_CurrentBorowings",),
    "long_debt": ("ifrs-full_LongtermBorrowings",),
    "receivables": ("ifrs-full_CurrentTradeReceivables",),
    "inventory": ("ifrs-full_Inventories",),
    "payables": ("kap-fr_CurrentTradePayables",),
}
FLOW = {"revenue", "gross_profit", "operating_profit", "net_income", "cfo", "capex", "depreciation"}


def decode_kap_pdf(data: bytes) -> bytes:
    # Some official downloads wrap a PDF in Java's serialized byte[] envelope.
    # Decode only that fixed primitive envelope; never deserialize Java objects.
    prefix = bytes.fromhex("aced0005757200025b42acf317f8060854e00200007870")
    if data.startswith(prefix):
        offset = len(prefix)
        length = int.from_bytes(data[offset : offset + 4], "big")
        content = data[offset + 4 :]
        if length != len(content):
            raise ValueError("Invalid KAP byte-array length")
        data = content
    if not data.startswith(b"%PDF-"):
        raise ValueError("Attachment is not a PDF")
    return data


def _published(value: str) -> datetime:
    for pattern in ("%Y.%m.%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=ZoneInfo("Europe/Istanbul"))
        except ValueError:
            pass
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("Europe/Istanbul"))


def parse_financial_report(detail: dict) -> dict:
    disclosure = detail.get("disclosure", {})
    basic = disclosure.get("disclosureBasic", {})
    if basic.get("disclosureClass") != "FR":
        raise ValueError("Not a KAP financial report")
    bodies = detail.get("disclosureBody") or []
    soup = BeautifulSoup("".join(bodies) if isinstance(bodies, list) else bodies, "html.parser")
    header = {}
    for row in soup.select(".financial-header-table tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) == 2:
            header[cells[0].get_text(" ", strip=True)] = cells[1].get_text(" ", strip=True)
    raw_unit = header.get("Sunum Para Birimi", "")
    normalized = raw_unit.upper().replace("İ", "I").replace(" ", "")
    unit_map = {
        "TL": ("TRY", 1),
        "TRY": ("TRY", 1),
        "BINTL": ("TRY", 1000),
        "1.000TL": ("TRY", 1000),
        "1.000.000TL": ("TRY", 1000000),
        "MILYONTL": ("TRY", 1000000),
        "USD": ("USD", 1),
        "EUR": ("EUR", 1),
        "ABDDOLARI": ("USD", 1),
    }
    currency, scale = unit_map.get(normalized, (None, None))
    facts = []
    for table in soup.select("table.financial-table"):
        contexts = []
        for cell in table.select("td.context-header"):
            label = cell.select_one(".content-tr") or cell
            dates = re.findall(r"\d{2}\.\d{2}\.\d{4}", label.get_text(" ", strip=True))
            contexts.append(
                [datetime.strptime(value, "%d.%m.%Y").date().isoformat() for value in dates]
            )
        if not contexts:
            continue  # Dimensional equity movement tables require a separate mapping.
        for row in table.select("tr.data-input-row"):
            name = row.select_one(":scope > .taxonomy-field-name-cell .taxonomy-field-name")
            label = row.select_one(":scope > .taxonomy-field-title .content-tr")
            cells = row.select(":scope > .taxonomy-context-value")
            if name is None or len(cells) != len(contexts):
                continue
            concept = name.get_text(strip=True).split("|", 1)[0]
            for context, cell in zip(contexts, cells, strict=True):
                numeric = cell.select_one("[title]")
                if not context or numeric is None:
                    continue
                raw = numeric.get("title", "").strip()
                try:
                    value = Decimal(raw)
                except InvalidOperation:
                    continue
                if not value.is_finite():
                    continue
                facts.append(
                    {
                        "concept": concept,
                        "label": label.get_text(" ", strip=True) if label else concept,
                        "start": context[0] if len(context) == 2 else None,
                        "end": context[-1],
                        "raw_value": raw,
                        "value": float(value * scale) if scale is not None else None,
                        "table": " ".join(table.get("class", [])),
                    }
                )
    end = max(
        (fact["end"] for fact in facts), default=_published(basic["publishDate"]).date().isoformat()
    )
    inflation_codes = {
        "ifrs-full_GainsLossesOnNetMonetaryPosition",
        "kap-fr_InflationEffectOnCashAndCashEquivalents",
    }
    inflation = any(
        fact["concept"] in inflation_codes and fact["value"] not in (None, 0) for fact in facts
    )
    return {
        "disclosure_id": str(basic["disclosureIndex"]),
        "symbol": str(basic.get("stockCode") or "").strip(),
        "company_name": basic.get("companyTitle"),
        "published_at": _published(basic["publishDate"]).isoformat(),
        "report_end": end,
        "currency": currency,
        "unit": raw_unit,
        "scale": scale,
        "consolidation": header.get("Finansal Tablo Niteliği"),
        "correction_of": disclosure.get("disclosureDetail", {}).get("relatedDisclosureIndex"),
        "inflation_basis": "report_end_purchasing_power" if inflation else "unverified",
        "source_url": f"{KAP_BASE_URL}/tr/Bildirim/{basic['disclosureIndex']}",
        "document_title": basic.get("title"),
        "supported_statement": bool(facts),
        "facts": facts,
    }


class KapFinancialArchive:
    def __init__(
        self,
        root: Path,
        *,
        client=None,
        timeout: float = 30,
        request_interval: float = 2.0,
        sleeper=time.sleep,
    ):
        self.archive = FinancialArchive(root)
        if client is None:
            import requests

            client = requests.Session()
        self.client = client
        self.timeout = timeout
        self.request_interval = max(0.0, request_interval)
        self.sleeper = sleeper
        self._last_request_at = None

    def _request(self, method: str, url: str, **kwargs):
        for attempt in range(4):
            if self._last_request_at is not None:
                delay = self.request_interval - (time.monotonic() - self._last_request_at)
                if delay > 0:
                    self.sleeper(delay)
            response = getattr(self.client, method)(url, **kwargs)
            self._last_request_at = time.monotonic()
            if getattr(response, "status_code", 200) not in (429, 503) or attempt == 3:
                return response
            delay = 60.0 * (2**attempt)
            retry_after = getattr(response, "headers", {}).get("Retry-After")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except (ValueError, TypeError):
                    try:
                        retry_at = parsedate_to_datetime(retry_after)
                        delay = max(delay, (retry_at - datetime.now(UTC)).total_seconds())
                    except (ValueError, TypeError, OverflowError):
                        pass
            logging.getLogger(__name__).warning(
                "KAP HTTP %s: retry in %.0f seconds", response.status_code, delay
            )
            close = getattr(response, "close", None)
            if callable(close):
                close()
            self.sleeper(delay)
        raise AssertionError("unreachable")

    def list_reports(self, start: date, end: date) -> list[dict]:
        if start > end:
            raise ValueError("Invalid date range")
        response = self._request(
            "post",
            KAP_DISCLOSURES_URL,
            json={
                "fromDate": start.isoformat(),
                "toDate": end.isoformat(),
                "disclosureClass": "FR",
                "subjectList": [],
                "mkkMemberOidList": [],
                "inactiveMkkMemberOidList": [],
                "bdkMemberOidList": [],
                "fromSrc": False,
                "disclosureIndexList": [],
            },
            headers={
                "Accept": "application/json",
                "Origin": KAP_BASE_URL,
                "Referer": KAP_BASE_URL + "/tr/bildirim-sorgu",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("KAP list response is not a list")
        if len(rows) >= 2000:
            if start == end:
                raise RuntimeError("KAP daily result cap reached; archive would be incomplete")
            midpoint = start + (end - start) // 2
            return self.list_reports(start, midpoint) + self.list_reports(
                midpoint + timedelta(days=1), end
            )
        return rows

    def sync(
        self,
        symbols: tuple[str, ...],
        *,
        start: date,
        end: date,
        download_pdfs: bool = True,
        checkpoint: Path | None = None,
        progress=None,
    ) -> dict:
        wanted = {symbol.upper().removesuffix(".IS") for symbol in symbols}
        if not wanted or any(not re.fullmatch(r"[A-Z0-9]{2,12}", symbol) for symbol in wanted):
            raise ValueError("Canonical symbols required")
        counts = {
            "listed": 0,
            "archived": 0,
            "statements": 0,
            "supplementary_documents": 0,
            "failed": 0,
            "errors": [],
        }
        seen = set()
        cursor = start
        if checkpoint is not None and checkpoint.is_file():
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            next_date = date.fromisoformat(saved["next_date"])
            if (
                saved.get("symbols") == sorted(wanted)
                and saved.get("download_pdfs") == download_pdfs
                and start <= next_date <= end + timedelta(days=1)
            ):
                cursor = next_date
                counts = saved["counts"]
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=30))
            for row in self.list_reports(cursor, chunk_end):
                row_symbols = set(
                    re.findall(r"[A-Z0-9]{2,12}", str(row.get("stockCodes") or "").upper())
                )
                identifier = str(row.get("disclosureIndex", ""))
                if not wanted.intersection(row_symbols) or identifier in seen:
                    continue
                seen.add(identifier)
                counts["listed"] += 1
                try:
                    report = self.archive_report(identifier, download_pdfs=download_pdfs)
                    counts["archived"] += 1
                    counts[
                        "statements" if report["supported_statement"] else "supplementary_documents"
                    ] += 1
                    if report["attachment_errors"]:
                        counts["failed"] += 1
                        counts["errors"].append(
                            {"disclosure_id": identifier, "error": report["attachment_errors"]}
                        )
                except Exception as exc:
                    counts["failed"] += 1
                    counts["errors"].append(
                        {
                            "disclosure_id": identifier,
                            "error": type(exc).__name__ + ": " + str(exc)[:180],
                        }
                    )
            cursor = chunk_end + timedelta(days=1)
            if checkpoint is not None and counts["failed"] == 0:
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                temporary = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
                temporary.write_text(
                    json.dumps(
                        {
                            "next_date": cursor.isoformat(),
                            "symbols": sorted(wanted),
                            "download_pdfs": download_pdfs,
                            "counts": counts,
                            "updated_at": datetime.now(UTC).isoformat(),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                temporary.replace(checkpoint)
            if progress is not None:
                progress(
                    {
                        "through": chunk_end.isoformat(),
                        "archived": counts["archived"],
                        "failed": counts["failed"],
                    }
                )
            if checkpoint is not None and counts["failed"]:
                break  # Never checkpoint past a failed historical interval.
        return counts

    def archive_report(self, identifier: str, *, download_pdfs: bool = True) -> dict:
        if not re.fullmatch(r"[0-9]+", identifier):
            raise ValueError("Invalid KAP disclosure identifier")
        response = self._request("get", f"{KAP_DETAIL_URL}/{identifier}", timeout=self.timeout)
        response.raise_for_status()
        raw = response.json()
        detail = raw[0] if isinstance(raw, list) and raw else None
        if not isinstance(detail, dict):
            raise ValueError("KAP detail is empty")
        report = parse_financial_report(detail)
        if report["disclosure_id"] != identifier:
            raise ValueError("KAP detail ID mismatch")
        stamp = datetime.now(UTC)
        raw_bytes = json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        directory = self.archive.root / "kap" / identifier
        directory.mkdir(parents=True, exist_ok=True)
        raw_path = directory / (digest + ".json")
        if not raw_path.exists():
            raw_path.write_bytes(raw_bytes)
        report["raw_sha256"] = digest
        report["raw_path"] = str(raw_path.relative_to(self.archive.root))
        report["observed_at"] = stamp.isoformat()
        report["attachments"] = []
        report["attachment_errors"] = []
        if download_pdfs:
            for attachment in detail.get("attachments") or []:
                oid = str(attachment.get("objId") or "")
                if str(attachment.get("fileExtension", "")).lower() != "pdf":
                    continue
                if not re.fullmatch(r"[a-fA-F0-9]{16,64}", oid):
                    report["attachment_errors"].append("Invalid attachment identifier")
                    continue
                try:
                    url = f"{KAP_BASE_URL}/tr/api/file/download/{oid}"
                    # No arbitrary attachment URLs or names become local paths.
                    download = self._request(
                        "get", url, timeout=self.timeout, stream=True, allow_redirects=False
                    )
                    download.raise_for_status()
                    data = bytearray()
                    for chunk in download.iter_content(65536):
                        data.extend(chunk)
                        if len(data) > 50 * 1024 * 1024:
                            raise ValueError("Attachment exceeds 50 MiB")
                    transport_digest = hashlib.sha256(data).hexdigest()
                    data = decode_kap_pdf(bytes(data))
                    pdf_digest = hashlib.sha256(data).hexdigest()
                    path = directory / (pdf_digest + ".pdf")
                    if not path.exists():
                        path.write_bytes(data)
                    report["attachments"].append(
                        {
                            "url": url,
                            "sha256": pdf_digest,
                            "path": str(path.relative_to(self.archive.root)),
                            "name": attachment.get("fileName"),
                            "transport_sha256": transport_digest,
                        }
                    )
                except Exception as exc:
                    report["attachment_errors"].append(type(exc).__name__ + ": " + str(exc)[:120])
        self.archive.put(report["symbol"], "kap", "report:" + identifier, report, observed_at=stamp)
        return report

    def reports(self, symbol: str, *, known_at: datetime) -> list[dict]:
        from market_intelligence.fundamentals.archive import utc_stamp

        with self.archive.connect() as db:
            rows = db.execute(
                "SELECT kind, payload FROM observations WHERE symbol=? AND source='kap' AND observed_at<=? ORDER BY observed_at DESC, rowid DESC",
                (symbol, utc_stamp(known_at)),
            ).fetchall()
        seen, reports = set(), []
        for kind, payload in rows:
            if kind in seen or not kind.startswith("report:"):
                continue
            seen.add(kind)
            report = json.loads(payload)
            if report.get("facts") and _published(report["published_at"]) <= known_at:
                reports.append(report)
        return sorted(
            reports, key=lambda item: (item["report_end"], item["published_at"]), reverse=True
        )


class KapArchivedFinancialProvider:
    provider_id = "kap:official_financial_reports"

    def __init__(self, root: Path, *, rebaser=None):
        from market_intelligence.fundamentals.inflation import CpiRebaser

        self.store = KapFinancialArchive(root)
        self.rebaser = rebaser or CpiRebaser(self.store.archive)

    def fetch(self, symbol: str, *, as_of: datetime) -> FinancialSnapshot:
        symbol = symbol.upper().removesuffix(".IS")
        reports = self.store.reports(symbol, known_at=as_of)
        if not reports:
            raise ValueError("No KAP report archived for symbol")
        latest = reports[0]
        if latest["currency"] is None:
            raise ValueError("KAP presentation currency/unit is unsupported")
        data = {"balance": {}, "income": {}, "cashflow": {}}
        normalization = []
        skipped = []
        for report in reports:
            if (
                report["currency"] != latest["currency"]
                or report["consolidation"] != latest["consolidation"]
            ):
                skipped.append(report["disclosure_id"] + ":currency_or_consolidation")
                continue
            factor = 1.0
            if report["report_end"] != latest["report_end"]:
                if (
                    report["inflation_basis"] != "report_end_purchasing_power"
                    or latest["inflation_basis"] != "report_end_purchasing_power"
                ):
                    skipped.append(report["disclosure_id"] + ":unverified_monetary_basis")
                    continue
                try:
                    factor = self.rebaser.factor(report["report_end"], latest["report_end"])
                except Exception:
                    skipped.append(report["disclosure_id"] + ":cpi_unavailable")
                    continue
                normalization.append(
                    {
                        "disclosure_id": report["disclosure_id"],
                        "factor": factor,
                        "from": report["report_end"],
                        "to": latest["report_end"],
                    }
                )
            for key, concepts in CONCEPTS.items():
                candidates = [
                    fact
                    for fact in report["facts"]
                    if fact["concept"] in concepts and fact["value"] is not None
                ]
                if key in FLOW:
                    candidates = [
                        fact
                        for fact in candidates
                        if fact["start"] and fact["start"].endswith("-01-01")
                    ]
                    frame = "cashflow" if key in {"cfo", "capex", "depreciation"} else "income"
                else:
                    candidates = [fact for fact in candidates if fact["start"] is None]
                    frame = "balance"
                local = {}
                for fact in candidates:
                    value = fact["value"] * factor
                    if fact["end"] in local and local[fact["end"]] != value:
                        raise ValueError("Ambiguous KAP fact: " + key)
                    local[fact["end"]] = value
                values = data[frame].setdefault(ALIASES[key][0], {})
                for period, value in local.items():
                    values.setdefault(period, value)  # Latest report's restated comparative wins.
        frames = {
            key: pd.DataFrame.from_dict(value, orient="index") if value else None
            for key, value in data.items()
        }
        result = _snapshot_from_frames(
            provider_id=self.provider_id,
            symbol=symbol,
            as_of=as_of,
            **frames,
            info={"currency": latest["currency"], "longName": latest["company_name"]},
            fast={},
            cumulative_flows=True,
            common_purchasing_power=latest["inflation_basis"] == "report_end_purchasing_power",
        )
        metrics = dict(result.metrics)
        if (
            metrics.get("operating_profit_ttm") is not None
            and metrics.get("depreciation_ttm") is not None
        ):
            metrics["ebitda_proxy_ttm"] = (
                metrics["operating_profit_ttm"] + metrics["depreciation_ttm"]
            )
        history = {}
        for key in CONCEPTS:
            frame_name = (
                ("cashflow" if key in {"cfo", "capex", "depreciation"} else "income")
                if key in FLOW
                else "balance"
            )
            history[key] = data[frame_name].get(ALIASES[key][0], {})
        # YTD and same-report comparative growth remain available when a defensible TTM is not.
        for key in FLOW:
            frame = frames["cashflow" if key in {"cfo", "capex", "depreciation"} else "income"]
            if frame is None or ALIASES[key][0] not in frame.index:
                continue
            series = frame.loc[ALIASES[key][0]].dropna().sort_index(ascending=False)
            if not series.empty:
                metrics[key + "_ytd"] = float(series.iloc[0])
                period = str(series.index[0])
                previous = str(int(period[:4]) - 1) + period[4:]
                prior_value = series.get(previous)
                if prior_value is not None and prior_value > 0:
                    metrics[key + "_ytd_growth"] = (
                        float(series.iloc[0]) / float(prior_value) - 1
                    ) * 100
        return replace(
            result,
            metrics=metrics,
            metric_sources={
                key: self.provider_id + ":" + latest["disclosure_id"]
                for key, value in metrics.items()
                if value is not None
            },
            errors=(*result.errors, *("excluded:" + reason for reason in skipped)),
            metadata={
                **result.metadata,
                "statement_source": "KAP",
                "statement_observed_at": latest["observed_at"],
                "statement_published_at": latest["published_at"],
                "statement_digest": latest["raw_sha256"],
                "statement_url": latest["source_url"],
                "historical_publication_verified": "true",
                "consolidation": latest["consolidation"],
                "inflation_basis": latest["inflation_basis"],
                "report_count": len(reports),
                "archive_status": "archived",
                "normalization": json.dumps(normalization),
                "normalization_method": "TCMB rounded monthly CPI compounded; approximate"
                if normalization
                else "same_report_basis",
                "monetary_base_date": latest["report_end"],
                "financial_history": json.dumps(history),
            },
        )
