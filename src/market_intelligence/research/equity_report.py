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

REPORT_TEMPLATE_VERSION = "equity-research-tr-1.0.0"


@dataclass(frozen=True)
class ReportSection:
    number: int
    title: str
    paragraphs: tuple[str, ...]
    status: str = "AVAILABLE"


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
    critical_conditions: tuple[str, ...]
    invalidation: str
    positive_confirmation: str
    conclusion: str
    evidence_available: int
    evidence_total: int

    @property
    def summary(self) -> str:
        return (
            f"{self.symbol} 24 bölümlü araştırma raporu · "
            f"bar={self.as_of_bar.isoformat()} · "
            f"kanıt={self.evidence_available}/{self.evidence_total}"
        )


def analysis_message(report: EquityResearchReport) -> str:
    section_by_number = {section.number: section for section in report.sections}
    executive = section_by_number[1].paragraphs[0]
    technical = section_by_number[22].paragraphs[0]
    combined = section_by_number[23].paragraphs[0]
    conditions = "\n".join(f"- {item}" for item in report.critical_conditions)
    return (
        f"{report.symbol} · birleşik analiz\n"
        f"Kapalı bar: {report.as_of_bar:%d.%m.%Y}\n\n"
        f"Özet: {executive}\n"
        f"Teknik: {technical}\n"
        f"Temel + teknik: {combined}\n\n"
        f"Kritik koşullar:\n{conditions}\n"
        f"Geçersizleşme: {report.invalidation}\n"
        f"Olumlu teyit: {report.positive_confirmation}\n\n"
        "Bu analiz yatırım tavsiyesi değildir; eksik alanlar UNKNOWN bırakılmıştır."
    )


def _pct(value: float | None) -> str:
    return "UNKNOWN" if value is None else f"%{value:+.2f}"


def _price(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _list_prices(values: tuple[float, ...]) -> str:
    return ", ".join(_price(value) for value in values) if values else "UNKNOWN"


def _status_counts(snapshot: SymbolSnapshot) -> tuple[int, int, int]:
    match = sum(result.status is EvaluationStatus.MATCH for result in snapshot.results)
    no_match = sum(result.status is EvaluationStatus.NO_MATCH for result in snapshot.results)
    unknown = sum(result.status is EvaluationStatus.UNKNOWN for result in snapshot.results)
    return match, no_match, unknown


def _metric(financial: FinancialSnapshot | None, key: str) -> float | None:
    return financial.metrics.get(key) if financial is not None else None


def _financial_value(financial: FinancialSnapshot | None, key: str, *, percent: bool = False) -> str:
    value = _metric(financial, key)
    if value is None:
        return "UNKNOWN"
    return _pct(value) if percent else _price(value)


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
    matched, no_match, unknown = _status_counts(stored)
    returns = ", ".join(
        f"{period} {_pct(value)}" for period, value in technical.period_returns.items()
    )
    news_lines = tuple(
        f"{item.published_at:%d.%m.%Y} · {item.headline} · kaynak={item.source}"
        for item in stored.news[:12]
    )
    news_text = news_lines or (
        "UNKNOWN — canonical KAP/haber deposunda bu enstrüman için kayıt bulunamadı.",
    )
    financial_available = financial is not None and financial.coverage > 0
    providers = ", ".join(financial.providers_used) if financial else "yok"
    financial_status = "AVAILABLE" if financial_available else "UNKNOWN"
    fundamental_unknown = (
        "UNKNOWN — birincil BIST/KAP bilanço adapteri ve yfinance fallback zinciri "
        "kullanılabilir point-in-time alan döndürmedi; sayı veya yorum uydurulmadı.",
    )
    financial_summary = (
        (
            f"Şirket={financial.company_name or frame.symbol_at_snapshot}; sektör={financial.sector or 'UNKNOWN'}; "
            f"para birimi={financial.currency or 'UNKNOWN'}; kaynaklar={providers}; "
            f"alan kapsamı=%{financial.coverage * 100:.0f}."
        ),
        (
            f"TTM hasılat={_financial_value(financial, 'revenue_ttm')}; büyüme="
            f"{_financial_value(financial, 'revenue_growth', percent=True)}; "
            f"TTM net kâr={_financial_value(financial, 'net_income_ttm')}; net marj="
            f"{_financial_value(financial, 'net_margin', percent=True)}."
        ),
    ) if financial_available else fundamental_unknown
    balance_summary = (
        (
            f"Varlıklar={_financial_value(financial, 'assets')}; özkaynak="
            f"{_financial_value(financial, 'equity')}; toplam finansal borç="
            f"{_financial_value(financial, 'total_debt')}; net borç="
            f"{_financial_value(financial, 'net_debt')}."
        ),
        (
            f"Cari oran={_financial_value(financial, 'current_ratio')}; borç/özkaynak="
            f"{_financial_value(financial, 'debt_equity')}; ROE="
            f"{_financial_value(financial, 'roe', percent=True)}; ROA="
            f"{_financial_value(financial, 'roa', percent=True)}."
        ),
    ) if financial_available else fundamental_unknown
    valuation_summary = (
        (
            f"Piyasa değeri={_financial_value(financial, 'market_cap')}; F/K="
            f"{_financial_value(financial, 'pe')}; PD/DD={_financial_value(financial, 'pb')}; "
            f"FD/FAVÖK={_financial_value(financial, 'ev_ebitda')}."
        ),
        "Çarpanlar hedef fiyat değildir. Negatif veya eksik payda N/M yerine UNKNOWN bırakılır.",
    ) if financial_available else (
        "UNKNOWN — piyasa değeri ve kârlılık/özkaynak/FAVÖK alanları yeterli olmadığı için "
        "hedef fiyat veya çarpan sonucu üretilmedi.",
    )
    patterns = ", ".join(technical.candlestick_patterns) or "Belirgin kural tabanlı formasyon yok"
    fib = ", ".join(
        f"{label}: {_price(value)}" for label, value in technical.fibonacci_levels.items()
    )
    scanner_summary = (
        f"Saklanmış scanner sonuçları: {matched} eşleşme, {no_match} eşleşme yok, "
        f"{unknown} belirsiz. Bu sayılar ağırlıklı yatırım puanı değildir."
    )
    trend_condition = (
        f"Fiyat SMA20={_price(technical.sma20)}, SMA50={_price(technical.sma50)} ve "
        f"SMA200={_price(technical.sma200)} seviyelerine göre değerlendirilmiştir."
    )
    sections = (
        ReportSection(1, "Yönetici özeti", (
            f"Son kapanış {_price(technical.close)}; günlük değişim {_pct(technical.change_pct)}. "
            f"Teknik yapı={technical.structure_tone}, trend={technical.trend_tone}, "
            f"aktif kurulum={technical.active_setup or 'yok'}.",
            scanner_summary,
        )),
        ReportSection(2, "Şirket kartı", (
            f"Enstrüman={frame.symbol_at_snapshot}; piyasa={frame.market}; timeframe={frame.timeframe.value}; "
            f"kapalı bar={frame.through_bar_time.isoformat()}; fiyat temeli={frame.price_basis.value}.",
            f"52 hafta aralığı {_price(technical.low_52w)}–{_price(technical.high_52w)}; "
            f"zirveye uzaklık {_pct(technical.distance_to_high_pct)}, dipten uzaklık {_pct(technical.distance_to_low_pct)}.",
            f"Dönemsel fiyat performansı: {returns}.",
        )),
        ReportSection(3, "Yatırım hikâyesi", (
            "Yapısal yatırım hikâyesi için şirket faaliyetleri, segmentler, siparişler ve finansal tablolar gerekir.",
            *financial_summary,
        ), status=financial_status),
        ReportSection(4, "Gelişmeler ve KAP", news_text, status="AVAILABLE" if stored.news else "UNKNOWN"),
        ReportSection(5, "Finansal analiz", financial_summary, status=financial_status),
        ReportSection(6, "Finansal sağlık", balance_summary, status=financial_status),
        ReportSection(7, "Değerleme", valuation_summary, status=financial_status),
        ReportSection(8, "Riskler", (
            f"Teknik risk göstergesi olarak ATR(14)={_price(technical.atr14)} "
            f"({_pct(technical.atr_pct)} fiyat oranı) ve 20 günlük yıllıklandırılmış volatilite "
            f"{_pct(technical.annualized_volatility_20d)} izlenir.",
            (
                f"Bilanço riski: net borç={_financial_value(financial, 'net_debt')}, "
                f"cari oran={_financial_value(financial, 'current_ratio')}."
                if financial_available
                else "Şirkete özgü bilanço riski veri olmadığı için UNKNOWN bırakılmıştır."
            ),
        )),
        ReportSection(9, "Trend analizi", (
            trend_condition,
            f"Ortak teknik context sonucu trend={technical.trend_tone}; ADX(14)={technical.adx14:.2f}. "
            "ADX yön değil, trend kuvveti ölçüsüdür.",
        )),
        ReportSection(10, "Piyasa yapısı", (
            f"Pivot tabanlı yapı tonu={technical.structure_tone}. Kurulum sınıfı={technical.setup_name}; "
            f"koşullu yön={technical.setup_direction}.",
        )),
        ReportSection(11, "Destek ve direnç", (
            f"Yakın pivot destekleri: {_list_prices(technical.support_levels)}.",
            f"Yakın pivot dirençleri: {_list_prices(technical.resistance_levels)}.",
        )),
        ReportSection(12, "Momentum", (
            f"RSI(14)={technical.rsi14:.2f}; MACD={technical.macd_line:.4f}, "
            f"sinyal={technical.macd_signal:.4f}, histogram={technical.macd_histogram:.4f}.",
        )),
        ReportSection(13, "Hacim", (
            f"20 günlük ortalama hacim={technical.average_volume_20d:,.0f}; "
            f"göreli hacim={technical.relative_volume_20d:.2f}x; "
            f"CMF(20)={'UNKNOWN' if technical.cmf20 is None else f'{technical.cmf20:.3f}'}.",
            f"OBV eğilimi={technical.obv_bias}.",
        )),
        ReportSection(14, "Volatilite", (
            f"ATR(14)={_price(technical.atr14)}, ATR/fiyat={_pct(technical.atr_pct)}, "
            f"Bollinger genişlik yüzdeliği={technical.bb_width_percentile:.1f}.",
        )),
        ReportSection(15, "Çoklu zaman dilimi", (
            "UNKNOWN — bu rapor sürümü yalnız kapalı günlük canonical frame üzerinden üretilir. "
            "Haftalık/aylık point-in-time resample doğrulaması tamamlanmadan MTF görüşü verilmez.",
        ), status="UNKNOWN"),
        ReportSection(16, "Formasyonlar", (
            f"Son iki kapalı günlük barda kural tabanlı mum sonucu: {patterns}.",
            "Formasyon tek başına yön tahmini değildir; seviye ve hacim koşuluyla okunmalıdır.",
        )),
        ReportSection(17, "Elliott dalga", (
            "UNKNOWN — güvenilir, deterministik ve parity testi yapılmış Elliott etiketleyicisi yok; "
            "manuel görünüm otomatik gerçek gibi sunulmadı.",
        ), status="UNKNOWN"),
        ReportSection(18, "Fibonacci", (
            f"Son 60 kapalı günlük barın düşük–yüksek aralığından türetilen seviyeler: {fib}.",
        )),
        ReportSection(19, "Confluence", (
            scanner_summary,
            f"Karar paneli kanıtı: skor={technical.decision_score}, giriş olayı={technical.decision_entry}. "
            "Skor yalnız legacy kural setinin iç metriğidir; tavsiye puanı değildir.",
        )),
        ReportSection(20, "Koşullu senaryolar", (
            f"Olumlu senaryo: fiyat {_list_prices(technical.resistance_levels)} dirençlerinden birini "
            "hacim teyidiyle aşar ve kapalı barla korursa yapı güçlenebilir.",
            f"Olumsuz senaryo: fiyat {_list_prices(technical.support_levels)} desteklerinden birinin "
            "altında kapalı bar üretirse teknik yapı zayıflayabilir.",
            "Yatay senaryo: destek–direnç aralığında hacim ve ADX zayıf kalırsa yön teyidi oluşmaz.",
        )),
        ReportSection(21, "Kritik seviyeler", (
            f"Destek={_list_prices(technical.support_levels)}; direnç={_list_prices(technical.resistance_levels)}; "
            f"SMA200={_price(technical.sma200)}; ATR={_price(technical.atr14)}.",
        )),
        ReportSection(22, "Teknik özet", (
            f"Veri → bulgu: kapanış {_price(technical.close)}, yapı {technical.structure_tone}, "
            f"trend {technical.trend_tone}, momentum RSI {technical.rsi14:.2f}.",
            "Anlam → koşul: destek/direnç dışındaki kapalı bar ve hacim teyidi, mevcut görünümün "
            "güçlenmesi veya geçersizleşmesi için izlenir.",
        )),
        ReportSection(23, "Birleşik temel + teknik değerlendirme", (
            (
                f"Finansal kapsam %{financial.coverage * 100:.0f}; teknik trend={technical.trend_tone}, "
                f"yapı={technical.structure_tone}. Bu birliktelik koşullu kanıt özetidir, yatırım hükmü değildir."
                if financial_available and financial is not None
                else "Temel veri UNKNOWN olduğu için birleşik hüküm üretilmedi. Teknik kanıtlar koşullu "
                "sunuldu; eksik temel veri olumlu veya olumsuz varsayımla doldurulmadı."
            ),
        ), status="AVAILABLE" if financial_available else "PARTIAL"),
        ReportSection(24, "Güven ve veri kapsamı", (
            "Güven bir yatırım notu değildir. Kapsam, yalnız rapor bileşenlerinin kanıtla doldurulma oranıdır.",
            f"Teknik frame=AVAILABLE; scanner={len(stored.results)} kayıt; KAP/haber={len(stored.news)} kayıt; "
            f"finansal tablolar={financial_status}; değerleme={financial_status}; "
            "MTF=UNKNOWN; Elliott=UNKNOWN.",
        )),
    )
    top_findings = (
        f"Kapanış {_price(technical.close)} ve günlük değişim {_pct(technical.change_pct)}.",
        f"Trend={technical.trend_tone}; yapı={technical.structure_tone}; ADX={technical.adx14:.2f}.",
        f"RSI(14)={technical.rsi14:.2f}; MACD histogram={technical.macd_histogram:.4f}.",
        f"Göreli hacim={technical.relative_volume_20d:.2f}x; ATR/fiyat={_pct(technical.atr_pct)}.",
        scanner_summary,
    )
    conditions = (
        f"Direnç üstünde kapalı bar: {_list_prices(technical.resistance_levels)}.",
        f"Destek altında kapalı bar: {_list_prices(technical.support_levels)}.",
        "Hacim teyidi ve aynı yönde trend/yapı uyumu.",
    )
    available = sum(section.status == "AVAILABLE" for section in sections)
    conclusion = (
        "Teknik görünüm koşullu ve kanıta dayalıdır; temel veri eksikliği nedeniyle yatırım "
        "önerisi veya hedef fiyat üretilmemiştir. Yeni kapalı bar ve KAP verisiyle rapor yenilenmelidir."
    )
    return EquityResearchReport(
        report_id=report_id,
        template_version=REPORT_TEMPLATE_VERSION,
        symbol=frame.symbol_at_snapshot,
        instrument_id=frame.instrument_id,
        as_of_bar=frame.through_bar_time,
        generated_at=generated_at,
        snapshot_id=frame.snapshot_id,
        series_revision=frame.series_revision,
        sections=sections,
        top_findings=top_findings,
        critical_conditions=conditions,
        invalidation=f"En yakın destek altında kapalı bar: {_list_prices(technical.support_levels[:1])}.",
        positive_confirmation=f"En yakın direnç üstünde hacimli kapalı bar: {_list_prices(technical.resistance_levels[:1])}.",
        conclusion=conclusion,
        evidence_available=available,
        evidence_total=len(sections),
    )
