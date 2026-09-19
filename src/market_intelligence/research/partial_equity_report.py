"""Explicit partial research when the technical feature graph is unavailable."""

from dataclasses import asdict

from market_intelligence.core.identity import stable_hash
from market_intelligence.research.equity_report_v2 import (
    EquityResearchReport,
    ReportSection,
    ReportTable,
    _financial_score,
    _num,
)

TITLES = {
    1: "Yönetici Özeti",
    2: "Şirket Kartı",
    3: "Yatırım Hikâyesi",
    4: "Son Gelişmeler ve KAP",
    5: "Finansal Analiz",
    6: "Finansal Sağlık",
    7: "Değerleme",
    8: "Katalizörler",
    9: "Riskler",
    10: "Teknik Genel Görünüm",
    11: "Trend",
    12: "Piyasa Yapısı",
    13: "Momentum",
    14: "Hacim",
    15: "Volatilite",
    16: "Çoklu Zaman Dilimi",
    17: "Destek / Direnç Haritası",
    18: "Formasyon",
    19: "Fibonacci",
    20: "Elliott Wave",
    21: "Teknik Confluence",
    22: "Senaryo Haritası",
    23: "Temel + Teknik Birleşik Sonuç",
    24: "Kritik Seviyeler",
    25: "Sonuç",
}


def build_partial_equity_report(*, frame, stored, financial, generated_at, missing):
    if frame.is_partial:
        raise ValueError("Rapor kısmi bar üzerinden üretilemez")
    if stored.instrument_id != frame.instrument_id:
        raise ValueError("Rapor snapshot enstrüman kimliği uyuşmuyor")
    missing_labels = {"decision.panel_v645": "Karar paneli", "research.technical_snapshot": "Birleşik teknik özet"}
    reason = f"Teknik özet hesaplanamadı. Kullanılabilir geçmiş: {len(frame.bars)} kapalı mum. Eksik bileşenler: {', '.join(missing_labels.get(item, item) for item in missing)}."
    summary = "Kısmi rapor: mevcut şirket ve finansal veriler korunmuştur; teknik sonuç, işlem seviyesi ve birleşik puan üretilmemiştir."
    sections = {
        n: ReportSection(n, title, (reason,), status="UNKNOWN") for n, title in TITLES.items()
    }
    sections[1] = ReportSection(1, TITLES[1], (summary, reason), status="PARTIAL")
    sections[2] = ReportSection(
        2,
        TITLES[2],
        (
            f"{financial.company_name or frame.symbol_at_snapshot} | {financial.sector or 'Sektör verisi yok'}"
            if financial
            else frame.symbol_at_snapshot,
        ),
        status="PARTIAL",
        tables=(
            ReportTable(
                ("Alan", "Değer"),
                (
                    ("Kapalı mum", frame.through_bar_time.isoformat()),
                    ("Kaynak / fiyat bazı", f"{frame.source} / {frame.price_basis.value}"),
                    ("Kapanış referansı", _num(frame.bars[-1].close)),
                    ("Kullanılabilir mum", str(len(frame.bars))),
                ),
            ),
        ),
    )
    if stored.news:
        sections[4] = ReportSection(
            4, TITLES[4], tuple(item.headline for item in stored.news[:10]), status="AVAILABLE"
        )
    financial_score, financial_coverage, score_rows, valuation, risks = _financial_score(financial)
    if financial:
        labels = {
            "revenue_ttm": "Hasılat (TTM)",
            "net_income_ttm": "Net kâr (TTM)",
            "assets": "Toplam varlıklar",
            "equity": "Özkaynaklar",
            "cash": "Nakit",
            "total_debt": "Toplam borç",
            "cfo_ttm": "Faaliyet nakit akışı (TTM)",
            "market_cap": "Piyasa değeri",
            "current_ratio": "Cari oran",
            "debt_equity": "Borç / özkaynak",
            "net_debt_equity": "Net borç / özkaynak",
            "pe": "F/K",
            "pb": "PD/DD",
            "revenue_growth": "Hasılat büyümesi (%)",
            "net_income_growth": "Net kâr büyümesi (%)",
        }
        rows = tuple(
            (
                label,
                _num(financial.metrics.get(key)),
                financial.metric_sources.get(key, "Kaynak belirtilmemiş"),
            )
            for key, label in labels.items()
        )
        sections[5] = ReportSection(
            5,
            TITLES[5],
            (
                "Kaynak sağlayıcıların dönem/para birimi kontrollerinden geçmiş mevcut göstergeler. Parasal tutarlar: "
                + str(financial.currency or "Birim doğrulanamadı"),
                "Dönemler: " + ", ".join(financial.statement_periods),
                "Kaynaklar: " + ", ".join(financial.providers_used),
            ),
            status="PARTIAL",
            tables=(ReportTable(("Gösterge", "Değer", "Kaynak"), rows),),
        )
        sections[6] = ReportSection(
            6,
            TITLES[6],
            (
                f"Finansal sağlık: {_num(financial_score)} / 100; veri kapsamı: %{financial_coverage:.0f}. Teknik puan bu değerlendirmeye dahil değildir.",
            ),
            status="PARTIAL",
            tables=(ReportTable(("Bileşen", "Ağırlık", "Katkı", "Açıklama"), score_rows),)
            if score_rows
            else (),
        )
        sections[7] = ReportSection(
            7,
            TITLES[7],
            (
                "Mevcut çarpanlar finansal tabloda gösterilmiştir. Bu kısmi raporda hedef fiyat veya birleşik değerleme kararı üretilmedi.",
            ),
            status="PARTIAL",
        )
    sections[9] = ReportSection(
        9,
        TITLES[9],
        (reason, *tuple(risks), *(financial.errors if financial else ())),
        status="PARTIAL",
    )
    sections[23] = ReportSection(
        23,
        TITLES[23],
        ("Teknik bileşen eksik olduğu için temel + teknik birleşik sonuç hesaplanamadı.",),
        status="UNKNOWN",
    )
    sections[25] = ReportSection(
        25,
        TITLES[25],
        (summary, "Eksik teknik bölümler veri tamamlandığında yeniden hesaplanmalıdır."),
        status="PARTIAL",
    )
    version = "equity-research-partial-1.0.0"
    identity = {
        "template": version,
        "snapshot": frame.snapshot_id,
        "financial": financial,
        "stored": stored,
        "missing": missing,
    }
    machine = {
        "status": "PARTIAL",
        "template_version": version,
        "ticker": frame.symbol_at_snapshot,
        "snapshot_id": frame.snapshot_id,
        "as_of_bar": frame.through_bar_time.isoformat(),
        "generated_at": generated_at.isoformat(),
        "technical": None,
        "technical_score": None,
        "confidence": {"score": None, "missing_data": list(missing)},
        "financial": asdict(financial) if financial else None,
    }
    # Convert datetime-bearing provider metadata to explicit ISO strings for the JSON attachment.
    import json

    machine = json.loads(
        json.dumps(
            machine,
            default=lambda value: value.isoformat() if hasattr(value, "isoformat") else str(value),
        )
    )
    return EquityResearchReport(
        report_id=stable_hash(identity),
        template_version=version,
        symbol=frame.symbol_at_snapshot,
        instrument_id=frame.instrument_id,
        as_of_bar=frame.through_bar_time,
        generated_at=generated_at,
        snapshot_id=frame.snapshot_id,
        series_revision=frame.series_revision,
        sections=tuple(sections[n] for n in sorted(sections)),
        top_findings=(summary, reason),
        key_risks=(reason, *tuple(risks)),
        critical_conditions=(
            "Eksik teknik bileşenler tamamlanmadan birleşik işlem kararı üretilemez.",
        ),
        invalidation="Hesaplanamadı: teknik veri eksik",
        positive_confirmation="Hesaplanamadı: teknik veri eksik",
        conclusion=summary,
        evidence_available=sum(section.status == "AVAILABLE" for section in sections.values()),
        evidence_total=25,
        financial_health_score=financial_score,
        financial_health_coverage=financial_coverage,
        technical_score=None,
        technical_coverage=0.0,
        valuation_status="Hesaplanamadı (kısmi rapor)",
        confidence_score=None,
        machine_readable=machine,
    )
