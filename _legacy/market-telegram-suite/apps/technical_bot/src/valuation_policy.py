"""Evidence-bound company-type valuation policy for the research report.

Model suitability is decided before any target value is produced. The module
separates economic applicability from data availability and never invents WACC,
growth, appraisal or profitability assumptions. Relative multiples are kept as
secondary market context rather than promoted to intrinsic value.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from src import valuation_models as vm

STATUS_SUITABLE = "UYGUN"
STATUS_CONDITIONAL = "KOŞULLU"
STATUS_UNSUITABLE = "UYGUN DEĞİL"
STATUS_MISSING = "VERİ EKSİK"


@dataclass(frozen=True)
class ModelAssessment:
    model: str
    status: str
    role: str
    reason: str
    value_per_share: float | None = None
    confidence: float = 0.0
    assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _profile(profile: str, sector: str) -> str:
    raw = f"{profile} {sector}".casefold()
    if "bank" in raw or "banka" in raw:
        return "BANK"
    if profile.upper() == "GYO" or "gyo" in raw or "reit" in raw or "gayrimenkul" in raw:
        return "GYO"
    if "holding" in raw or "yatırım ortak" in raw or "yatirim ortak" in raw:
        return "HOLDING"
    cyclical_terms = (
        "cyclical",
        "dongusel",
        "döngüsel",
        "airline",
        "havac",
        "steel",
        "çelik",
        "celik",
        "chemical",
        "kimya",
        "automotive",
        "otomotiv",
    )
    if any(term in raw for term in cyclical_terms):
        return "CYCLICAL"
    return "GENERIC"


def _model(model: str, status: str, role: str, reason: str, **kwargs: Any) -> ModelAssessment:
    return ModelAssessment(model=model, status=status, role=role, reason=reason, **kwargs)


def _relative_assessment(peer: dict[str, Any]) -> ModelAssessment:
    score = _finite(peer.get("score"))
    coverage = _finite(peer.get("coverage")) or 0.0
    if score is None or coverage < 0.35:
        return _model(
            "Göreli Çarpanlar",
            STATUS_MISSING,
            "ikincil",
            "Akran evreni veya karşılaştırılabilir çarpan kapsamı yeterli değil.",
            confidence=coverage,
        )
    return _model(
        "Göreli Çarpanlar",
        STATUS_SUITABLE,
        "ikincil",
        "Sektör/akran konumunu gösterir; tek başına içsel değer veya şirket kalitesi sayılmaz.",
        confidence=coverage,
    )


def _equity_support_status(metrics: dict[str, Any]) -> tuple[str, float]:
    """Measure readiness of equity models without manufacturing missing inputs."""
    roe = _finite(metrics.get("roe"))
    equity = _finite(metrics.get("equity"))
    ke = _finite(metrics.get("cost_of_equity"))
    growth = _finite(metrics.get("long_term_growth"))
    if roe is None or equity is None:
        return STATUS_MISSING, 0.0
    if ke is None or growth is None:
        return STATUS_MISSING, 0.25
    if ke <= growth:
        return STATUS_UNSUITABLE, 0.0
    return STATUS_CONDITIONAL, 0.55


def _gyo_models(metrics: dict[str, Any], peer: dict[str, Any]) -> list[ModelAssessment]:
    equity_status, equity_confidence = _equity_support_status(metrics)
    equity_reason = (
        "GYO'da özkaynak modelleri destek/çapraz kontrol rolündedir. Sürdürülebilir ROE, "
        "TMS-29 ile aynı reel/nominal ölçekte Ke ve uzun dönem g olmadan hedef değer üretilmez."
    )
    assessments = [
        _model(
            "NAD / NAV",
            STATUS_MISSING,
            "birincil",
            "GYO için birincil yöntem ekspertiz bazlı portföy gerçeğe uygun değeridir. "
            "Portföy ekspertiz tablosu, finansal borçlar ve diğer yükümlülükler olmadan gerçek NAD üretilmez.",
            assumptions=("KAP/şirket ekspertiz portföyü", "yükümlülük ayrıntısı", "hisse adedi"),
        ),
        _model(
            "Haklı PD/DD",
            equity_status,
            "destek",
            equity_reason,
            confidence=equity_confidence,
            assumptions=("sürdürülebilir ROE", "özkaynak maliyeti (Ke)", "uzun dönem g"),
        ),
        _model(
            "Residual Income",
            equity_status,
            "destek",
            equity_reason,
            confidence=equity_confidence,
            assumptions=("defter değeri", "ROE yolu", "özkaynak maliyeti (Ke)", "dağıtım/büyüme varsayımı"),
        ),
        _relative_assessment(peer),
    ]

    cfo_ni = _finite(metrics.get("cfo_net_income"))
    fcf_margin = _finite(metrics.get("fcf_margin"))
    if cfo_ni is None or fcf_margin is None:
        dcf_status = STATUS_MISSING
        dcf_reason = "Tekrarlayan nakit akışının kâra dönüşümü yeterince ölçülemiyor; klasik DCF zorlanmadı."
    elif cfo_ni > 0.7 and fcf_margin > 0:
        dcf_status = STATUS_CONDITIONAL
        dcf_reason = (
            "Pozitif nakit dönüşümü FCFF DCF'i yardımcı model yapabilir; GYO'da NAD'ın yerini almaz ve "
            "şirket-spesifik FCFF, WACC ve terminal g ayrıca gerekir."
        )
    else:
        dcf_status = STATUS_UNSUITABLE
        dcf_reason = "Muhasebe kârının nakit karşılığı zayıf/negatif; klasik FCFF DCF bu görünümde güvenilir değil."

    dividend = _finite(metrics.get("dividend_yield"))
    ddm_status = STATUS_CONDITIONAL if dividend is not None and dividend > 0 else STATUS_MISSING
    assessments.extend(
        [
            _model(
                "FCFF DCF",
                dcf_status,
                "yardımcı",
                dcf_reason,
                confidence=0.35 if dcf_status == STATUS_CONDITIONAL else 0.0,
            ),
            _model(
                "Monetizasyon DCF",
                STATUS_MISSING,
                "yardımcı",
                "Arsa/proje satış takvimi, tahsilat planı ve proje bazlı nakit akışı yoksa monetizasyon DCF'i kurulmaz.",
                assumptions=("satış/tahsilat takvimi", "proje nakit akışları", "iskonto oranı"),
            ),
            _model(
                "EPV / Kazanç Gücü",
                STATUS_UNSUITABLE,
                "kontrol",
                "Tekrarlayan faaliyet kârı yoksa veya değer esas olarak varlık stokundan geliyorsa EPV ekonomik taban değer değildir.",
            ),
            _model(
                "Temettü İskonto",
                ddm_status,
                "yardımcı",
                "Düzenli ve nakit karşılığı olan temettü politikası olmadan DDM kurulmaz; muhasebe kârı temettü kapasitesi sayılmaz.",
                assumptions=("sürdürülebilir nakit temettü", "Ke", "uzun dönem g"),
            ),
            _model(
                "F/K",
                STATUS_UNSUITABLE,
                "kontrol",
                "GYO kârı yeniden değerleme ve nakit olmayan kalemlerden etkilenebildiği için F/K birincil değerleme değildir.",
            ),
            _model(
                "FD/FAVÖK",
                STATUS_UNSUITABLE,
                "kontrol",
                "GYO'da ekspertiz/NAD ekonomisi baskınsa ve faaliyet FAVÖK'ü zayıfsa firma değeri/FAVÖK zorlanmaz.",
            ),
            _model(
                "Altman Z",
                STATUS_UNSUITABLE,
                "—",
                "Klasik imalat şirketi iflas modeli GYO bilançosu için güvenilir bir değerleme/risk modeli değildir.",
            ),
        ]
    )
    return assessments


def _bank_models(metrics: dict[str, Any], peer: dict[str, Any]) -> list[ModelAssessment]:
    roe_pct = _finite(metrics.get("roe"))
    pb = _finite(metrics.get("pb"))
    pe = _finite(metrics.get("pe"))
    residual_status = STATUS_CONDITIONAL if roe_pct is not None and pb is not None and pb > 0 else STATUS_MISSING
    pe_status = STATUS_CONDITIONAL if pe is not None and pe > 0 else STATUS_MISSING
    return [
        _model(
            "Residual Income",
            residual_status,
            "birincil",
            "Bankalarda capex/işletme sermayesi FCFF mantığı yerine defter değeri ile ROE'nin özkaynak maliyetini aşan kısmı esastır. "
            "Sayısal değer için sürdürülebilir ROE, Ke ve dağıtım oranı senaryosu gerekir.",
            confidence=0.55 if residual_status == STATUS_CONDITIONAL else 0.0,
        ),
        _model(
            "Haklı PD/DD",
            residual_status,
            "birincil/çapraz kontrol",
            "ROE ile özkaynak maliyeti arasındaki fark PD/DD'nin ekonomik temelidir; Ke ve uzun dönem g verilmeden hedef çarpan uydurulmaz.",
            confidence=0.5 if residual_status == STATUS_CONDITIONAL else 0.0,
        ),
        _model(
            "F/K",
            pe_status,
            "destek",
            "Karşılık politikası ve tek seferlik kalemler normalize edilmek şartıyla banka akran karşılaştırmasında destek çarpanıdır.",
            confidence=0.35 if pe_status == STATUS_CONDITIONAL else 0.0,
        ),
        _relative_assessment(peer),
        _model(
            "Temettü İskonto",
            STATUS_CONDITIONAL,
            "destek",
            "Düzenli ve sürdürülebilir dağıtım politikası varsa kullanılabilir; ileri temettü tahmini gerekir.",
        ),
        _model(
            "FCFF / FD-FAVÖK",
            STATUS_UNSUITABLE,
            "—",
            "Banka bilançosunda borç işletme hammaddesidir; klasik firma değeri/FCFF yaklaşımı uygun değildir.",
        ),
        _model("EPV", STATUS_UNSUITABLE, "—", "EBIT/NOPAT firma değeri yaklaşımı banka ekonomisini doğru temsil etmez."),
        _model("NAD / NAV", STATUS_UNSUITABLE, "—", "Banka değeri basit varlık stoku değil risk ağırlıklı kredi/özkaynak getirisi ekonomisidir."),
        _model("Altman Z", STATUS_UNSUITABLE, "—", "Bankalar için imalat şirketi iflas modeli ekonomik olarak uygun değildir."),
    ]


def _generic_models(metrics: dict[str, Any], peer: dict[str, Any]) -> list[ModelAssessment]:
    cfo_ni = _finite(metrics.get("cfo_net_income"))
    fcf_margin = _finite(metrics.get("fcf_margin"))
    op_growth = _finite(metrics.get("operating_growth"))
    if cfo_ni is None or fcf_margin is None:
        dcf_status = STATUS_MISSING
        dcf_reason = "FCF/nakit dönüşümü yeterli değil; DCF için projeksiyon tabanı doğrulanamıyor."
    elif cfo_ni > 0.7 and fcf_margin > 0:
        dcf_status = STATUS_CONDITIONAL
        dcf_reason = "Nakit dönüşümü DCF'e elverişli; sayısal içsel değer için şirket-spesifik FCFF tahmini, WACC ve terminal büyüme gerekir."
    else:
        dcf_status = STATUS_UNSUITABLE
        dcf_reason = "FCF veya nakit/kâr dönüşümü zayıf; mevcut muhasebe kârından zorla DCF hedefi üretilmedi."
    epv_status = STATUS_CONDITIONAL if op_growth is not None else STATUS_MISSING
    equity_status, equity_confidence = _equity_support_status(metrics)
    dividend = _finite(metrics.get("dividend_yield"))
    ddm_status = STATUS_CONDITIONAL if dividend is not None and dividend > 0 else STATUS_MISSING
    return [
        _model("FCFF DCF", dcf_status, "birincil", dcf_reason, confidence=0.5 if dcf_status == STATUS_CONDITIONAL else 0.0),
        _model(
            "EPV / Kazanç Gücü",
            epv_status,
            "taban değer",
            "Normalize faaliyet kârıyla büyümesiz taban değer üretilebilir; normalize EBIT, idame capex, net borç ve WACC gerekir.",
            confidence=0.4 if epv_status == STATUS_CONDITIONAL else 0.0,
        ),
        _relative_assessment(peer),
        _model(
            "Haklı PD/DD",
            equity_status,
            "çapraz kontrol",
            "ROE > Ke değer yaratımı kontrolüdür; sürdürülebilir ROE, Ke ve g yoksa hedef çarpan üretilmez.",
            confidence=equity_confidence,
        ),
        _model(
            "Residual Income",
            equity_status,
            "çapraz kontrol",
            "Defter değeri ve ROE yolu anlamlıysa yardımcı özkaynak kontrolüdür; operasyonel DCF'in yerini almaz.",
            confidence=equity_confidence,
        ),
        _model(
            "Temettü İskonto",
            ddm_status,
            "yardımcı",
            "Olgun ve düzenli nakit temettü ödeyen şirketlerde yardımcı modeldir; aksi halde devre dışıdır.",
        ),
        _model(
            "Piotroski F-Score",
            STATUS_CONDITIONAL,
            "kalite kontrolü",
            "En az iki karşılaştırılabilir bilanço dönemi ve hisse adedi/temel marj verileriyle finansal sağlamlık kontrolü yapılabilir.",
        ),
        _model(
            "Altman Z",
            STATUS_CONDITIONAL,
            "risk kontrolü",
            "İmalat/operasyonel şirketlerde yardımcı iflas riski göstergesidir; GYO/banka için kullanılmamalıdır.",
        ),
    ]


def _holding_models(metrics: dict[str, Any], peer: dict[str, Any]) -> list[ModelAssessment]:
    dividend = _finite(metrics.get("dividend_yield"))
    ddm_status = STATUS_CONDITIONAL if dividend is not None and dividend > 0 else STATUS_MISSING
    return [
        _model(
            "NAD / SOTP",
            STATUS_MISSING,
            "birincil",
            "Holdinglerde iştirak/varlıkların ayrı gerçeğe uygun değerleri ve holding net borcu olmadan SOTP/NAD üretilmez.",
            assumptions=("iştirak piyasa/gerçeğe uygun değerleri", "holding net borcu"),
        ),
        _model(
            "Holding İskontosu",
            STATUS_MISSING,
            "birincil/çapraz kontrol",
            "NAD'a göre tarihsel holding iskontosu ancak karşılaştırılabilir tarihçe ve güncel SOTP ile hesaplanır.",
            assumptions=("güncel NAD/SOTP", "tarihsel iskonto dağılımı"),
        ),
        _relative_assessment(peer),
        _model(
            "Temettü İskonto",
            ddm_status,
            "yardımcı",
            "İştiraklerden holding seviyesine tekrarlayan ve sürdürülebilir temettü akışı varsa yardımcı olabilir.",
        ),
        _model(
            "FCFF DCF",
            STATUS_UNSUITABLE,
            "—",
            "Konsolide holding nakit akışı iştirak, azınlık payı ve sermaye tahsisi etkileriyle kirlenir; varlık bazlı SOTP önceliklidir.",
        ),
        _model(
            "F/K",
            STATUS_UNSUITABLE,
            "—",
            "Konsolidasyon ve iştirak kârları holding F/K karşılaştırmasını yapısal olarak bozabilir.",
        ),
    ]


def _cyclical_models(metrics: dict[str, Any], peer: dict[str, Any]) -> list[ModelAssessment]:
    """Use mid-cycle earning power instead of extrapolating a peak/trough period."""
    history = metrics.get("ebitda_history") or metrics.get("favok_history")
    normalized: float | None = None
    if isinstance(history, (list, tuple)) and len(history) >= 3:
        try:
            normalized = vm.normalize_ebitda([float(value) for value in history], method="median")
        except (TypeError, ValueError):
            normalized = None
    normalized_status = STATUS_CONDITIONAL if normalized is not None and normalized > 0 else STATUS_MISSING
    equity_status, equity_confidence = _equity_support_status(metrics)
    return [
        _model(
            "Normalize FAVÖK DCF",
            normalized_status,
            "birincil",
            "Döngüsel şirkette tek dönemin zirve/dip kârı ileri taşınmaz; çevrim ortası normalize FAVÖK/EBIT ve şirket-spesifik WACC gerekir.",
            confidence=0.5 if normalized_status == STATUS_CONDITIONAL else 0.0,
            assumptions=("çok dönemli FAVÖK geçmişi", "çevrim ortası marj", "WACC", "idame capex"),
        ),
        _model(
            "Çevrim Ortası FD/FAVÖK",
            normalized_status,
            "birincil/çapraz kontrol",
            "Akran çarpanı yalnız normalize çevrim ortası FAVÖK ile anlamlıdır; cari tepe/dip FAVÖK'e uygulanmaz.",
            confidence=0.4 if normalized_status == STATUS_CONDITIONAL else 0.0,
        ),
        _model(
            "EPV / Kazanç Gücü",
            normalized_status,
            "birincil/taban değer",
            "Normalize faaliyet kârı pozitifse büyümesiz taban değer olarak kullanılabilir.",
            confidence=0.35 if normalized_status == STATUS_CONDITIONAL else 0.0,
        ),
        _model(
            "FCFF DCF",
            normalized_status,
            "yardımcı",
            "Tek bir yıl yerine normalize çevrim ortası nakit akışıyla kurulursa yardımcı model olabilir.",
            confidence=0.3 if normalized_status == STATUS_CONDITIONAL else 0.0,
        ),
        _model(
            "Haklı PD/DD",
            equity_status,
            "yardımcı",
            "Cari ROE yerine çevrim boyu ortalama sürdürülebilir ROE, Ke ve g ile çapraz kontrol yapılabilir.",
            confidence=equity_confidence,
        ),
        _relative_assessment(peer),
        _model(
            "Cari F/K",
            STATUS_UNSUITABLE,
            "kontrol",
            "Döngüsel kârın zirve/dip döneminde cari F/K yapısal olarak yanıltıcı olabilir; çevrim ortası kâr tercih edilir.",
        ),
        _model("NAD / NAV", STATUS_UNSUITABLE, "—", "Değerin ana kaynağı varlık stoku değil normalize faaliyet kazanç gücüdür."),
        _model(
            "Temettü İskonto",
            STATUS_UNSUITABLE,
            "—",
            "Döngüsel temettü akışı sabit büyüme varsayımına uygun değildir; ancak ayrı normalizasyonla incelenebilir.",
        ),
    ]


def build_valuation_policy(
    profile: str,
    sector: str,
    metrics: dict[str, Any],
    peer_valuation: dict[str, Any],
    price: float | None = None,
) -> dict[str, Any]:
    """Return an evidence-bound valuation matrix without fabricating assumptions."""
    kind = _profile(profile, sector)
    if kind == "GYO":
        models = _gyo_models(metrics, peer_valuation)
        primary = "NAD / NAV"
    elif kind == "BANK":
        models = _bank_models(metrics, peer_valuation)
        primary = "Residual Income + Haklı PD/DD"
    elif kind == "HOLDING":
        models = _holding_models(metrics, peer_valuation)
        primary = "NAD / SOTP"
    elif kind == "CYCLICAL":
        models = _cyclical_models(metrics, peer_valuation)
        primary = "Normalize FAVÖK DCF"
    else:
        models = _generic_models(metrics, peer_valuation)
        primary = "FCFF DCF"

    peer_score = _finite(peer_valuation.get("score"))
    peer_coverage = _finite(peer_valuation.get("coverage")) or 0.0
    usable = [item for item in models if item.status in {STATUS_SUITABLE, STATUS_CONDITIONAL}]
    model_coverage = len(usable) / max(len(models), 1)
    confidence = round(min(1.0, 0.6 * peer_coverage + 0.4 * model_coverage), 2)

    result = dict(peer_valuation)
    result.update(
        {
            "score": peer_score,
            "coverage": peer_coverage,
            "profile": kind,
            "primary_model": primary,
            "model_confidence": confidence,
            "model_coverage": round(model_coverage, 2),
            "models": [item.to_dict() for item in models],
            "computed_values": {},
            "price": _finite(price),
            "policy_note": (
                "Model uygunluğu puandan önce gelir. Uygun olmayan veya girdisi eksik model çalıştırılmaz; "
                "hazır sağlayıcı çarpanları yalnız göreli bağlamdır ve içsel hedef fiyat yerine kullanılmaz."
            ),
        }
    )
    return result


def evaluate_nav_if_available(
    valuation: dict[str, Any],
    *,
    portfolio_fair_value: float | None,
    cash: float | None,
    receivables: float | None,
    other_assets: float | None,
    financial_debt: float | None,
    other_liabilities: float | None,
    minority_interest: float | None,
    shares_outstanding: float | None,
    price: float | None,
) -> dict[str, Any]:
    """Optional hook for KAP/appraisal data; leaves valuation untouched when incomplete."""
    required = [portfolio_fair_value, shares_outstanding]
    if any(_finite(value) is None for value in required):
        return valuation
    nav = vm.nav_per_share(
        vm.NAVInputs(
            portfolio_fair_value=float(portfolio_fair_value),
            cash_and_equivalents=float(cash or 0.0),
            receivables=float(receivables or 0.0),
            other_assets=float(other_assets or 0.0),
            financial_debt=float(financial_debt or 0.0),
            other_liabilities=float(other_liabilities or 0.0),
            minority_interest=float(minority_interest or 0.0),
            shares_outstanding=float(shares_outstanding),
        )
    )
    computed = dict(valuation.get("computed_values") or {})
    computed["nav"] = nav
    if _finite(price) is not None:
        computed["nav_market_relation"] = vm.nav_premium(float(price), float(nav["nav_per_share"]))
    result = dict(valuation)
    result["computed_values"] = computed
    result["primary_model"] = "NAD / NAV"
    result["model_confidence"] = max(float(result.get("model_confidence") or 0.0), 0.8)
    models = []
    for item in result.get("models", []):
        updated = dict(item)
        if item.get("model") == "NAD / NAV":
            updated.update(
                {
                    "status": STATUS_SUITABLE,
                    "value_per_share": nav["nav_per_share"],
                    "confidence": 0.9,
                    "reason": "Ekspertiz/gerçeğe uygun portföy değeri ve yükümlülük girdileriyle gerçek NAD hesaplandı.",
                }
            )
        models.append(updated)
    result["models"] = models
    return result
