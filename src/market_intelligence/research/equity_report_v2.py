from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from market_intelligence.application.symbol_commands import SymbolSnapshot
from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.core.identity import stable_hash
from market_intelligence.features.research import (
    RESEARCH_TECHNICAL_SNAPSHOT,
    ResearchTechnicalSnapshot,
)
from market_intelligence.fundamentals.providers import FinancialSnapshot
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.news.text import sentence_excerpt

REPORT_TEMPLATE_VERSION = "equity-research-tr-2.0.0"


@dataclass(frozen=True)
class ReportTable:
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    title: str = ""


@dataclass(frozen=True)
class ReportSection:
    number: int
    title: str
    paragraphs: tuple[str, ...]
    status: str = "AVAILABLE"
    tables: tuple[ReportTable, ...] = ()
    bullets: tuple[str, ...] = ()


@dataclass(frozen=True)
class EquityResearchReport:
    report_id: str
    template_version: str
    symbol: str
    instrument_id: str
    as_of_bar: datetime
    generated_at: datetime
    snapshot_id: str
    series_revision: int
    sections: tuple[ReportSection, ...]
    top_findings: tuple[str, ...]
    key_risks: tuple[str, ...]
    critical_conditions: tuple[str, ...]
    invalidation: str
    positive_confirmation: str
    conclusion: str
    evidence_available: int
    evidence_total: int
    financial_health_score: float | None
    financial_health_coverage: float
    technical_score: float | None
    technical_coverage: float
    valuation_status: str
    confidence_score: float

    @property
    def summary(self) -> str:
        return (
            f"{self.symbol} 25 bölümlü araştırma raporu · bar={self.as_of_bar.isoformat()} · "
            f"kanıt={self.evidence_available}/{self.evidence_total} · güven={self.confidence_score:.0f}/100"
        )


def analysis_message(report: EquityResearchReport) -> str:
    sections = {section.number: section for section in report.sections}
    conditions = "\n".join(f"- {item}" for item in report.critical_conditions)
    return (
        f"{report.symbol} · birleşik analiz\nKapalı bar: {report.as_of_bar:%d.%m.%Y}\n\n"
        f"Özet: {sections[1].paragraphs[0]}\nTeknik: {sections[10].paragraphs[0]}\n"
        f"Temel + teknik: {sections[23].paragraphs[0]}\n\nKritik koşullar:\n{conditions}\n"
        f"Geçersizleşme: {report.invalidation}\nOlumlu teyit: {report.positive_confirmation}\n\n"
        "Bu analiz yatırım tavsiyesi değildir; veri yetersiz alanlar açıkça belirtilmiştir."
    )


def _num(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "Veri yok"
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(value: float | None) -> str:
    return "Veri yok" if value is None else f"%{value:+.2f}"


def _money(value: float | None, currency: str) -> str:
    if value is None:
        return "Veri yok"
    if abs(value) >= 1_000_000_000:
        return f"{_num(value / 1_000_000_000)} milyar {currency}"
    if abs(value) >= 1_000_000:
        return f"{_num(value / 1_000_000)} milyon {currency}"
    return f"{_num(value)} {currency}"


def _metric(financial: FinancialSnapshot | None, key: str) -> float | None:
    return financial.metrics.get(key) if financial else None


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _higher(value: float | None, bad: float, good: float) -> float | None:
    return None if value is None else _clamp((value - bad) / (good - bad) * 100.0)


def _lower(value: float | None, good: float, bad: float) -> float | None:
    return None if value is None else _clamp((bad - value) / (bad - good) * 100.0)


def _weighted(components: tuple[tuple[str, float, float | None, str], ...]):
    coverage = sum(weight for _, weight, score, _ in components if score is not None)
    earned = sum(
        weight * float(score) / 100.0 for _, weight, score, _ in components if score is not None
    )
    score = earned / coverage * 100.0 if coverage else None
    rows = tuple(
        (
            name,
            f"{weight:.0f}",
            "Veri yok" if value is None else f"{weight * value / 100:.1f}",
            detail,
        )
        for name, weight, value, detail in components
    )
    return score, coverage, rows


def _financial_score(financial: FinancialSnapshot | None):
    if not financial:
        return None, 0.0, (), "Belirsiz", ["Finansal tablolar alınamadı."]
    revenue = _metric(financial, "revenue_growth")
    net_growth = _metric(financial, "net_income_growth")
    fcf_margin = _metric(financial, "fcf_margin")
    leverage = _metric(financial, "net_debt_equity")
    quality = (
        _higher(net_growth - revenue + 15, 0, 40)
        if revenue is not None and net_growth is not None
        else None
    )
    current = _metric(financial, "current_ratio")
    liquidity = (
        None
        if current is None
        else 100.0
        if 1.2 <= current <= 3
        else _higher(current, 0.5, 1.2)
        if current < 1.2
        else _lower(current, 3, 6)
    )
    components = (
        ("Gelir büyümesi", 10.0, _higher(revenue, -10, 30), f"Hasılat {_pct(revenue)}"),
        (
            "Kârlılık",
            15.0,
            _higher(_metric(financial, "net_margin"), 0, 20),
            f"Net marj {_pct(_metric(financial, 'net_margin'))}",
        ),
        (
            "Marj",
            10.0,
            _higher(_metric(financial, "operating_margin"), 0, 25),
            f"Faaliyet marjı {_pct(_metric(financial, 'operating_margin'))}",
        ),
        ("Nakit üretimi", 15.0, _higher(fcf_margin, -10, 15), f"SNA marjı {_pct(fcf_margin)}"),
        ("Borçluluk", 15.0, _lower(leverage, 0, 2), f"Net borç/özkaynak {_num(leverage)}x"),
        ("Finansman yükü", 10.0, None, "Faiz karşılama alanı standart değil"),
        (
            "ROE/ROIC",
            10.0,
            _higher(_metric(financial, "roe"), 0, 30),
            f"ROE {_pct(_metric(financial, 'roe'))}; ROIC veri yok",
        ),
        ("Likidite", 5.0, liquidity, f"Cari oran {_num(current)}x"),
        ("Büyüme kalitesi", 10.0, quality, f"Satış {_pct(revenue)} / net kâr {_pct(net_growth)}"),
    )
    score, coverage, rows = _weighted(components)
    pe, pb, ev = (_metric(financial, key) for key in ("pe", "pb", "ev_ebitda"))
    known = sum(value is not None and value > 0 for value in (pe, pb, ev))
    expensive = sum((value or 0) > limit for value, limit in ((pe, 30), (pb, 5), (ev, 20)))
    cheap = sum(0 < (value or 0) < limit for value, limit in ((pe, 10), (pb, 1.2), (ev, 8)))
    valuation = (
        "Belirsiz"
        if known < 2
        else "Primli"
        if expensive >= 2
        else "İskontolu"
        if cheap >= 2
        else "Makul / karma"
    )
    risks: list[str] = []
    if fcf_margin is not None and fcf_margin < 0:
        risks.append(f"Serbest nakit akımı negatiftir; SNA marjı {_pct(fcf_margin)}.")
    if leverage is not None and leverage > 1:
        risks.append(f"Net borç/özkaynak {_num(leverage)}x ile yüksektir.")
    if revenue is not None and revenue < 0:
        risks.append(f"Hasılat büyümesi {_pct(revenue)} ile negatiftir.")
    if valuation == "Primli":
        risks.append(
            "Güncel çarpanlar yüksek beklentiye ve sonuç sapmalarına duyarlılığa işaret ediyor."
        )
    return score, coverage, rows, valuation, risks


def _technical_score(technical: ResearchTechnicalSnapshot):
    structure = {"positive": 85.0, "negative": 15.0, "warning": 45.0, "neutral": 50.0}.get(
        technical.structure_tone, 50.0
    )
    mas = [technical.moving_averages.get(period) for period in (5, 8, 13, 20, 50, 100, 200)]
    valid = [value for value in mas if value is not None]
    pairs = sum(left > right for left, right in zip(valid, valid[1:], strict=False))
    trend = pairs / max(len(valid) - 1, 1) * 100
    momentum = (
        sum((_higher(technical.rsi14, 30, 70) or 0, 75 if technical.macd_histogram > 0 else 25)) / 2
    )
    volume = (
        sum(
            (
                _higher(technical.relative_volume_20d, 0.5, 1.8) or 0,
                70 if technical.obv_bias == "positive" else 30,
            )
        )
        / 2
    )
    components = (
        (
            "Piyasa yapısı",
            25.0,
            structure,
            f"{technical.high_label}/{technical.low_label} · {technical.structure_tone}",
        ),
        ("Trend", 20.0, trend, f"7 MA diziliminde {pairs} pozitif çift"),
        (
            "Hacim",
            15.0,
            volume,
            f"RVOL {technical.relative_volume_20d:.2f}x; OBV {technical.obv_bias}",
        ),
        (
            "Momentum",
            15.0,
            momentum,
            f"RSI {technical.rsi14:.1f}; MACD hist. {technical.macd_histogram:.3f}",
        ),
        ("Çoklu zaman dilimi", 10.0, None, "Yalnız günlük canonical frame mevcut"),
        (
            "Volatilite/risk",
            5.0,
            _lower(technical.atr_pct, 1, 7),
            f"ATR/fiyat {_pct(technical.atr_pct)}",
        ),
        (
            "Confluence",
            10.0,
            75.0 if technical.near_confluence else 45.0,
            "Yakın bağımsız faktör kümesi" if technical.near_confluence else "Güçlü yakın küme yok",
        ),
    )
    return _weighted(components)


def _tone(score: float | None) -> str:
    if score is None:
        return "Veri yetersiz"
    labels = (
        (80, "Güçlü yükseliş"),
        (65, "Yükseliş"),
        (55, "Pozitif-yatay"),
        (45, "Yatay"),
        (35, "Negatif-yatay"),
        (20, "Düşüş"),
    )
    return next((label for threshold, label in labels if score >= threshold), "Güçlü düşüş")


def _level_rows(technical: ResearchTechnicalSnapshot) -> tuple[tuple[str, ...], ...]:
    levels: list[tuple[float, str, str]] = []
    levels += [
        (value, "Yapı", "Pivot") for value in technical.support_levels + technical.resistance_levels
    ]
    levels += [(value, "MA", f"MA{period}") for period, value in technical.moving_averages.items()]
    for value, label in (
        (technical.profile_poc, "POC"),
        (technical.profile_val, "VAL"),
        (technical.profile_vah, "VAH"),
        (technical.vwap20, "VWAP20"),
        (technical.anchored_vwap, "Anchored VWAP"),
    ):
        if value is not None:
            levels.append((value, "Hacim", label))
    levels += [(value, "Fibonacci", label) for label, value in technical.fibonacci_levels.items()]
    tolerance = max(technical.atr14 * 0.3, technical.close * 0.005)
    clusters: list[list[tuple[float, str, str]]] = []
    for level in sorted(levels):
        center = sum(item[0] for item in clusters[-1]) / len(clusters[-1]) if clusters else None
        if center is None or level[0] - center > tolerance:
            clusters.append([level])
        else:
            clusters[-1].append(level)
    rows: list[tuple[float, tuple[str, ...]]] = []
    for cluster in clusters:
        center = sum(item[0] for item in cluster) / len(cluster)
        if abs(center - technical.close) <= technical.atr14 * 7:
            families = sorted({item[1] for item in cluster})
            labels = list(dict.fromkeys(item[2] for item in cluster))
            strength = min(5, len(families) + int("Yapı" in families))
            row = (
                _num(center),
                "Destek" if center < technical.close else "Direnç",
                "★" * strength,
                ", ".join(labels),
                ", ".join(families),
            )
            rows.append((abs(center - technical.close), row))
    return tuple(row for _, row in sorted(rows, key=lambda item: item[0])[:10])


def build_equity_research_report(
    *,
    frame: CanonicalFrame,
    technical: ResearchTechnicalSnapshot,
    stored: SymbolSnapshot,
    financial: FinancialSnapshot | None,
    generated_at: datetime,
) -> EquityResearchReport:
    if frame.is_partial:
        raise ValueError("Rapor kısmi bar üzerinden üretilemez")
    if stored.instrument_id != frame.instrument_id:
        raise ValueError("Rapor snapshot enstrüman kimliği uyuşmuyor")
    report_id = stable_hash(
        {
            "instrument_id": frame.instrument_id,
            "as_of_bar": frame.through_bar_time,
            "snapshot_id": frame.snapshot_id,
            "series_revision": frame.series_revision,
            "feature": RESEARCH_TECHNICAL_SNAPSHOT.identity_hash,
            "template_version": REPORT_TEMPLATE_VERSION,
        }
    )
    currency = financial.currency if financial and financial.currency else "TL"
    company = (
        financial.company_name if financial and financial.company_name else frame.symbol_at_snapshot
    )
    sector = financial.sector if financial and financial.sector else "Veri yok"
    metadata = financial.metadata if financial else {}
    financial_score, financial_coverage, financial_rows, valuation, risks = _financial_score(
        financial
    )
    technical_score, technical_coverage, technical_rows = _technical_score(technical)
    trend = _tone(technical_score)
    support = technical.swing_low or (
        technical.support_levels[0] if technical.support_levels else None
    )
    resistance = technical.swing_high or (
        technical.resistance_levels[0] if technical.resistance_levels else None
    )
    invalidation = (
        f"{_num(support)} altında kapanış"
        if support is not None
        else "Teyitli swing desteği üretilemedi"
    )
    if support is not None and technical.atr14 > 0:
        invalidation += (
            f"; mevcut fiyata uzaklık {abs(technical.close - support) / technical.atr14:.2f} ATR"
        )
    confirmation = (
        f"{_num(resistance)} üzerinde RVOL ≥ 1,5 ile kalıcı kapanış"
        if resistance is not None
        else "Teyitli swing direnci üretilemedi"
    )
    momentum = (
        "Pozitif"
        if technical.macd_histogram > 0 and technical.rsi14 >= 50
        else "Negatif"
        if technical.macd_histogram < 0 and technical.rsi14 < 50
        else "Karışık"
    )
    volume = (
        "Güçlü katılım"
        if technical.relative_volume_20d >= 1.5
        else "Artan katılım"
        if technical.relative_volume_20d >= 1.2
        else "Normal"
        if technical.relative_volume_20d >= 0.8
        else "Zayıf katılım"
    )
    financial_status = "AVAILABLE" if financial and financial.coverage > 0 else "UNKNOWN"
    news_status = "AVAILABLE" if stored.news else "UNKNOWN"
    if technical.atr_pct >= 4:
        risks.append(f"ATR/fiyat {_pct(technical.atr_pct)} ile volatilite yüksektir.")
    if technical.relative_volume_20d < 0.8:
        risks.append("Fiyat hareketi hacim katılımıyla teyit edilmiyor.")
    while len(risks) < 3:
        risks.append("Çoklu zaman dilimi veya sektör/peer verisi eksik; sonuç kapsamı sınırlıdır.")
    risks = risks[:3]
    matches = sum(item.status is EvaluationStatus.MATCH for item in stored.results)
    no_matches = sum(item.status is EvaluationStatus.NO_MATCH for item in stored.results)
    unknown = sum(item.status is EvaluationStatus.UNKNOWN for item in stored.results)
    scanner_text = f"Canonical taramalar: {matches} eşleşme, {no_matches} eşleşme yok, {unknown} veri yetersiz."
    confidence = _clamp(
        20
        + financial_coverage * 0.2
        + 10
        + 15
        + (10 if stored.news else 0)
        + (5 if technical.profile_poc is not None else 0)
    )
    news_rows = tuple(
        (
            item.published_at.strftime("%d.%m.%Y"),
            item.source.upper(),
            item.headline,
            sentence_excerpt(item.summary, max_chars=480)
            if item.summary
            else "Ayrıntılı özet veri yok",
        )
        for item in stored.news[:15]
    )
    ma_rows = tuple(
        (
            f"MA{period}",
            _num(value),
            _pct(technical.moving_average_slopes.get(period)),
            "Üstünde" if technical.close > value else "Altında",
        )
        for period, value in sorted(technical.moving_averages.items())
    )
    level_rows = _level_rows(technical)
    dashboard = ReportTable(
        ("Alan", "Durum"),
        (
            ("Şirket / Hisse", f"{company} / {frame.symbol_at_snapshot}"),
            ("Fiyat", f"{_num(technical.close)} {currency}"),
            ("Temel görünüm", _tone(financial_score)),
            ("Teknik görünüm", trend),
            (
                "Finansal sağlık",
                f"{_num(financial_score, 0)}/100 · kapsam %{financial_coverage:.0f}",
            ),
            ("Teknik puan", f"{_num(technical_score, 0)}/100 · kapsam %{technical_coverage:.0f}"),
            ("Değerleme", valuation),
            ("Risk", "Yüksek" if technical.atr_pct >= 4 or len(risks) >= 3 else "Orta"),
            ("Analiz güveni", f"{confidence:.0f}/100"),
        ),
    )
    finance_table = ReportTable(
        ("Metrik", "Son değer", "YoY", "Değerlendirme"),
        (
            (
                "Hasılat",
                _money(_metric(financial, "revenue_ttm"), currency),
                _pct(_metric(financial, "revenue_growth")),
                "Reel yorum için enflasyon gerekir",
            ),
            (
                "FAVÖK",
                _money(_metric(financial, "ebitda_ttm"), currency),
                _pct(_metric(financial, "ebitda_growth")),
                f"Marj {_pct(_metric(financial, 'ebitda_margin'))}",
            ),
            (
                "Net kâr",
                _money(_metric(financial, "net_income_ttm"), currency),
                _pct(_metric(financial, "net_income_growth")),
                f"Marj {_pct(_metric(financial, 'net_margin'))}",
            ),
            (
                "Faaliyet nakdi",
                _money(_metric(financial, "cfo_ttm"), currency),
                _pct(_metric(financial, "cfo_growth")),
                f"Nakit/kâr {_num(_metric(financial, 'cfo_net_income'))}x",
            ),
            (
                "Serbest nakit",
                _money(_metric(financial, "fcf_ttm"), currency),
                "—",
                f"SNA marjı {_pct(_metric(financial, 'fcf_margin'))}",
            ),
        ),
    )
    sections = (
        ReportSection(
            1,
            "Yönetici Özeti",
            (
                f"{company} için son kapanış {_num(technical.close)} {currency}. Temel sağlık {_num(financial_score, 0)}/100, teknik görünüm {_num(technical_score, 0)}/100 ({trend}) ve değerleme {valuation.lower()}.",
                f"Yapı {technical.high_label}/{technical.low_label}, momentum {momentum.lower()}, hacim {volume.lower()}. Olumlu teyit: {confirmation}. Geçersizlik: {invalidation}.",
            ),
            tables=(dashboard,),
        ),
        ReportSection(
            2,
            "Şirket Kartı",
            (
                f"Rapor {frame.through_bar_time:%d.%m.%Y} kapalı barına kadarki point-in-time veriyi kullanır.",
            ),
            status=financial_status,
            tables=(
                ReportTable(
                    ("Kalem", "Değer"),
                    (
                        ("Şirket", company),
                        ("Piyasa", str(metadata.get("exchange") or frame.market)),
                        ("Sektör", sector),
                        (
                            "Alt sektör",
                            str(
                                metadata.get("subsector") or metadata.get("industry") or "Veri yok"
                            ),
                        ),
                        ("Piyasa değeri", _money(_metric(financial, "market_cap"), currency)),
                        ("Pay sayısı", _num(_metric(financial, "shares_outstanding"), 0)),
                        ("Günlük hacim", _num(technical.daily_volume, 0)),
                        ("52 hafta", f"{_num(technical.low_52w)} - {_num(technical.high_52w)}"),
                    ),
                ),
            ),
        ),
        ReportSection(
            3,
            "Yatırım Hikâyesi",
            (
                sentence_excerpt(
                    metadata.get("description")
                    or "Şirket faaliyet açıklaması veri sağlayıcısından alınamadı.",
                    max_chars=1500,
                ),
                f"Satış büyümesi {_pct(_metric(financial, 'revenue_growth'))}, net kâr büyümesi {_pct(_metric(financial, 'net_income_growth'))}, serbest nakit akımı {_money(_metric(financial, 'fcf_ttm'), currency)}. Hikâye, büyümenin nakde dönüşmesiyle teyit edilmelidir.",
            ),
            status=financial_status,
        ),
        ReportSection(
            4,
            "Son Gelişmeler ve KAP",
            (
                "Olaylar, finansal etki ve olası hisse etkisi ayrı değerlendirilir; tutar/vade yoksa etki varsayılmaz.",
            )
            if news_rows
            else ("Saklanmış KAP/haber kaydı yok; katalizör yorumu uydurulmadı.",),
            status=news_status,
            tables=(ReportTable(("Tarih", "Kaynak", "Olay", "Açıklama"), news_rows),)
            if news_rows
            else (),
        ),
        ReportSection(
            5,
            "Finansal Analiz",
            (
                "Mutlak değer, büyüme, marj ve nakit dönüşümü birlikte okunur. Kümülatif BIST raporlaması ve TMS-29 etkisi ayrıca dikkate alınmalıdır.",
            ),
            status=financial_status,
            tables=(finance_table,),
        ),
        ReportSection(
            6,
            "Finansal Sağlık",
            (
                f"Puan {_num(financial_score, 1)}/100; kanıt kapsamı %{financial_coverage:.0f}. Eksik bileşenler sıfır sayılmamış, mevcut kanıt normalize edilmiştir.",
            ),
            status=financial_status,
            tables=(ReportTable(("Bileşen", "Ağırlık", "Kazanılan", "Kanıt"), financial_rows),)
            if financial_rows
            else (),
        ),
        ReportSection(
            7,
            "Değerleme",
            (
                f"Güncel çarpan görünümü {valuation.lower()}. Tarihsel seri ve sektör medyanı yoksa bu göreli değer hükmü değildir.",
                "Düşük çarpan otomatik ucuz kabul edilmez; kalite, borç ve nakit üretimiyle birlikte okunur.",
            ),
            status=financial_status,
            tables=(
                ReportTable(
                    ("Çarpan", "Değer"),
                    (
                        ("F/K", _num(_metric(financial, "pe"))),
                        ("İleri F/K", _num(_metric(financial, "forward_pe"))),
                        ("PD/DD", _num(_metric(financial, "pb"))),
                        ("FD/FAVÖK", _num(_metric(financial, "ev_ebitda"))),
                        ("FD/Satış", _num(_metric(financial, "ev_sales"))),
                        ("FCF verimi", _pct(_metric(financial, "fcf_yield"))),
                    ),
                ),
            ),
        ),
        ReportSection(
            8,
            "Katalizörler",
            (
                "Yakın katalizör KAP/haberden, yapısal katalizör büyüme-marj-nakit dönüşümünden türetilir.",
            ),
            status="PARTIAL" if stored.news or financial else "UNKNOWN",
            bullets=tuple(
                [
                    f"{row[0]} - {row[2]}: ölçülebilir etki için tutar ve vade izlenmeli."
                    for row in news_rows[:5]
                ]
                + [
                    f"Net kâr büyümesinin {_pct(_metric(financial, 'net_income_growth'))} seviyesinde nakde dönüşmesi."
                ]
            ),
        ),
        ReportSection(
            9,
            "Riskler",
            ("Riskler gerçekleşmiş zarar değil, izlenecek koşullardır.",),
            tables=(
                ReportTable(
                    ("Risk", "Olasılık", "Etki", "İzlenecek veri", "Kritik eşik"),
                    tuple(
                        (risk, "Ölçülmedi", "Orta/Yüksek", "Bilanço, KAP, hacim", invalidation)
                        for risk in risks
                    ),
                ),
            ),
        ),
        ReportSection(
            10,
            "Teknik Genel Görünüm",
            (
                f"Fiyat ve piyasa yapısı önceliklidir. Teknik puan {_num(technical_score, 1)}/100, kapsam %{technical_coverage:.0f}; sonuç {trend.lower()}.",
                scanner_text,
            ),
            tables=(ReportTable(("Alan", "Ağırlık", "Kazanılan", "Açıklama"), technical_rows),),
        ),
        ReportSection(
            11,
            "Trend",
            (
                f"MA sıralaması, eğim ve fiyat ilişkisi birlikte değerlendirildi. Sonuç: {trend}. Tek kesişim trend hükmü değildir.",
            ),
            tables=(ReportTable(("Ortalama", "Seviye", "5 bar eğim", "Fiyat"), ma_rows),),
        ),
        ReportSection(
            12,
            "Piyasa Yapısı",
            (
                f"Teyitli swing etiketleri {technical.high_label}/{technical.low_label}; son yüksek {_num(resistance)}, son düşük {_num(support)}.",
                "Fitil tek başına BOS sayılmaz. CHOCH kesin dönüş değil, ilk yapısal uyarıdır.",
            ),
        ),
        ReportSection(
            13,
            "Momentum",
            (
                f"Momentum {momentum.lower()}. RSI {technical.rsi14:.2f}; MACD/sinyal/histogram {technical.macd_line:.3f}/{technical.macd_signal:.3f}/{technical.macd_histogram:.3f}; SMI {_num(technical.smi)}/{_num(technical.smi_signal)}.",
                f"ADX {technical.adx14:.2f} yön değil güç ölçer; +DI {_num(technical.plus_di)}, -DI {_num(technical.minus_di)}; güçlü divergence {technical.strong_divergences}.",
            ),
        ),
        ReportSection(
            14,
            "Hacim",
            (
                f"Hacim {_num(technical.daily_volume, 0)}, ortalama {_num(technical.average_volume_20d, 0)}, RVOL {technical.relative_volume_20d:.2f}x: {volume.lower()}.",
                f"OBV {technical.obv_bias}, CMF {_num(technical.cmf20, 3)}, POC {_num(technical.profile_poc)}, VA {_num(technical.profile_val)}-{_num(technical.profile_vah)}, VWAP20 {_num(technical.vwap20)}, anchored VWAP {_num(technical.anchored_vwap)}.",
            ),
        ),
        ReportSection(
            15,
            "Volatilite",
            (
                f"ATR {_num(technical.atr14)} ({_pct(technical.atr_pct)}), yıllıklandırılmış oynaklık {_pct(technical.annualized_volatility_20d)}, Bollinger genişlik yüzdeliği %{technical.bb_width_percentile:.1f}.",
                "Önce yapısal seviye belirlenir; ATR yalnız mesafeyi sınar.",
            ),
        ),
        ReportSection(
            16,
            "Çoklu Zaman Dilimi",
            (
                "Bu çağrıda yalnız günlük canonical frame var. Haftalık/aylık ve gün içi veri aynı snapshot ile sağlanmadığından günlük sonuç diğer periyotlara genellenmedi.",
            ),
            status="UNKNOWN",
            tables=(
                ReportTable(
                    ("TF", "Trend", "Yapı", "Momentum", "Hacim", "Durum"),
                    (
                        (
                            "1D",
                            trend,
                            f"{technical.high_label}/{technical.low_label}",
                            momentum,
                            volume,
                            "Mevcut",
                        ),
                        ("1W/1M", "Veri yok", "Veri yok", "Veri yok", "Veri yok", "Puan dışı"),
                    ),
                ),
            ),
        ),
        ReportSection(
            17,
            "Destek / Direnç Haritası",
            (
                "Pivot, MA, Fibonacci, VWAP ve Volume Profile ATR yakınlığıyla kümelendi; benzer MA'lar bağımsız kanıt sayılmadı.",
            ),
            tables=(ReportTable(("Bölge", "Tip", "Güç", "Confluence", "Kaynak"), level_rows),),
        ),
        ReportSection(
            18,
            "Formasyon",
            (
                f"Son mumlar: {', '.join(technical.candlestick_patterns) or 'belirgin teyitli formasyon yok'}. Yapı sınıfı {technical.setup_name}; yön {technical.setup_direction}.",
                "Kapanış ve hacim teyidi olmadan teorik hedef verilmez.",
            ),
        ),
        ReportSection(
            19,
            "Fibonacci",
            ("Son 60 kapalı bar aralığından türetildi; tek başına sinyal değildir.",),
            tables=(
                ReportTable(
                    ("Oran", "Seviye"),
                    tuple(
                        (label, _num(value)) for label, value in technical.fibonacci_levels.items()
                    ),
                ),
            ),
        ),
        ReportSection(
            20,
            "Elliott Wave",
            (
                f"Ana bağlam: {'yükseliş itkisi/düzeltme' if technical.structure_tone == 'positive' else 'düşüş itkisi/tepki' if technical.structure_tone == 'negative' else 'yatay/kompleks düzeltme'}. Alternatif: karşıt ABC hareketi.",
                f"Kesin 1-5 etiketi zorlanmadı; geçersizlik {invalidation}.",
            ),
            status="PARTIAL",
        ),
        ReportSection(
            21,
            "Teknik Confluence",
            (
                f"Yakın confluence {'var' if technical.near_confluence else 'güçlü teyit edilmedi'}. Karar paneli skoru {technical.decision_score}; bu legacy iç metriği yatırım puanı değildir.",
            ),
            tables=(ReportTable(("Bölge", "Tip", "Güç", "Unsurlar", "Aile"), level_rows[:6]),),
        ),
        ReportSection(
            22,
            "Senaryo Haritası",
            ("Senaryolar tahmin değil, fikrin hangi koşulda değişeceğini tanımlar.",),
            tables=(
                ReportTable(
                    ("Senaryo", "Tetikleyici", "Teyit", "Olası sonuç", "Geçersizlik"),
                    (
                        (
                            "Pozitif",
                            confirmation,
                            "MACD/RSI uyumu",
                            "Sonraki arz bölgesi izlenir",
                            invalidation,
                        ),
                        (
                            "Nötr",
                            f"{_num(support)}-{_num(resistance)} bandı",
                            "Zayıf ADX/hacim",
                            "Konsolidasyon",
                            "Bant dışı kapanış",
                        ),
                        (
                            "Negatif",
                            invalidation,
                            "Artan satış hacmi/-DI",
                            "Alt destekler izlenir",
                            confirmation,
                        ),
                    ),
                ),
            ),
        ),
        ReportSection(
            23,
            "Temel + Teknik Birleşik Sonuç",
            (
                f"Finansal sağlık {_num(financial_score, 0)}/100, teknik {_num(technical_score, 0)}/100, değerleme {valuation.lower()}. Katmanlar çelişiyorsa tek etikete indirgenmez.",
                f"Şu anda yapı {technical.structure_tone}, trend {trend.lower()}, momentum {momentum.lower()}, katılım {volume.lower()}. Fikri değiştirecek koşullar: {confirmation}; {invalidation}.",
            ),
            status="AVAILABLE" if financial else "PARTIAL",
        ),
        ReportSection(
            24,
            "Kritik Seviyeler",
            ("Bölgeler kesin hedef değil, yeniden değerlendirme noktalarıdır.",),
            tables=(
                ReportTable(
                    ("Seviye", "Anlam"),
                    (
                        (_num(resistance), "Ana pozitif teyit"),
                        (_num(technical.profile_vah), "Volume Profile üst değer alanı"),
                        (_num(technical.close), "Güncel kapanış"),
                        (_num(technical.profile_poc), "Hacim denge noktası"),
                        (_num(technical.profile_val), "Alt değer alanı"),
                        (_num(support), "Ana teknik geçersizlik"),
                    ),
                ),
            ),
        ),
        ReportSection(
            25,
            "Sonuç",
            (
                f"Şu anda {frame.symbol_at_snapshot} günlük yapıda {technical.high_label}/{technical.low_label}, {trend.lower()} trend, {momentum.lower()} momentum ve {volume.lower()} hacim gösteriyor.",
                f"Olumlu senaryo {confirmation} koşuluyla güçlenir; görüş {invalidation} koşulunda yeniden değerlendirilir. Temel tez, büyüme kalitesi ve nakit dönüşümü kalıcı bozulursa zayıflar.",
                "Bu rapor AL/SAT sinyali değil, karar destek analizidir.",
            ),
            bullets=tuple(risks),
        ),
    )
    top = (
        f"Yapı {technical.high_label}/{technical.low_label}; teknik görünüm {trend.lower()}.",
        f"Momentum {momentum.lower()}; RSI {technical.rsi14:.1f}, MACD histogram {technical.macd_histogram:.3f}.",
        f"Hacim {volume.lower()}; RVOL {technical.relative_volume_20d:.2f}x, POC {_num(technical.profile_poc)}.",
        f"Finansal sağlık {_num(financial_score, 0)}/100; değerleme {valuation.lower()}.",
        scanner_text,
    )
    conditions = (
        confirmation,
        invalidation,
        "Yeni finansallarda büyüme, marj ve serbest nakit akımın birlikte izlenmesi.",
    )
    available = sum(section.status == "AVAILABLE" for section in sections)
    conclusion = f"{frame.symbol_at_snapshot} için kanıt {trend.lower()} teknik yapı ve {valuation.lower()} değerleme gösteriyor. Karar seviyeleri yeni kapanış ve hacimde görüşü değiştiren referanslardır."
    return EquityResearchReport(
        report_id,
        REPORT_TEMPLATE_VERSION,
        frame.symbol_at_snapshot,
        frame.instrument_id,
        frame.through_bar_time,
        generated_at,
        frame.snapshot_id,
        frame.series_revision,
        sections,
        top,
        tuple(risks),
        conditions,
        invalidation,
        confirmation,
        conclusion,
        available,
        len(sections),
        financial_score,
        financial_coverage,
        technical_score,
        technical_coverage,
        valuation,
        confidence,
    )
