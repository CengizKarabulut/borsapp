"""Shared deterministic paragraph helpers for the rich /analiz commentary engine.

The commentary is intentionally interpretive rather than a metric dump: each section
states what the evidence means, what cannot be concluded, and which condition would
change the reading. Missing data is never converted into a neutral or negative score.
The single user-facing compose/message path lives in ``research_commentary_rich.py``.
"""

from __future__ import annotations

import math
from typing import Any

from src.research_engine import ResearchDimension, ResearchReport
from src.turkish_text import tr_lower


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _num(value: Any, digits: int = 1) -> str:
    number = _finite(value)
    return "—" if number is None else f"{number:.{digits}f}"


def _pct(value: Any, digits: int = 1) -> str:
    number = _finite(value)
    return "—" if number is None else f"%{number:.{digits}f}"


def _dimension(report: ResearchReport, name: str) -> ResearchDimension | None:
    target = tr_lower(name)
    return next((item for item in report.dimensions if tr_lower(item.name) == target), None)


def _score_phrase(item: ResearchDimension | None) -> str:
    if item is None or item.score is None:
        return "bu başlıkta güvenilir puan üretmek için veri kapsamı yeterli değil"
    return f"{item.score:.0f}/100 puanla {tr_lower(item.label)} görünüm veriyor"


def _coverage_phrase(coverage: float) -> str:
    pct = round(coverage * 100)
    if coverage >= 0.8:
        return f"Veri kapsamı %{pct}; bu nedenle puanın dayanağı geniş."
    if coverage >= 0.6:
        return f"Veri kapsamı %{pct}; sonuç kullanılabilir ancak eksik başlıklar nedeniyle güven tam değil."
    return f"Veri kapsamı yalnız %{pct}; puan yön gösterse de kesin hüküm için veri tabanı dar."


def _company_paragraph(report: ResearchReport) -> str:
    quality = _dimension(report, "Şirket Kalitesi")
    profile = {"BANK": "banka", "GYO": "GYO", "GENERIC": "şirket"}.get(report.profile, "şirket")
    score = None if quality is None else _finite(quality.score)
    if score is None:
        interpretation = (
            "Bu nedenle şirketin faaliyet kalitesini güçlü ya da zayıf diye etiketlemek yerine, eksik finansal veri "
            "tamamlanana kadar hükmü açık bırakmak gerekir."
        )
    elif score >= 70:
        interpretation = (
            "Bu, eldeki faaliyet ve bilanço göstergelerinde yapısal olarak olumlu bir taban bulunduğunu gösterir; "
            "ancak yüksek kalite puanı tek başına hissenin ucuz veya teknik olarak güçlü olduğu anlamına gelmez."
        )
    elif score >= 50:
        interpretation = (
            "Bu seviye belirgin bir kalite üstünlüğünden çok dengeli/karma bir şirket profiline işaret eder; alt "
            "başlıklardaki iyileşme veya bozulma ana resmi hızlı değiştirebilir."
        )
    else:
        interpretation = (
            "Bu seviye faaliyet kalitesinde teyit edilmesi gereken zayıflıklar olduğunu gösterir; değerleme ucuz olsa "
            "bile kalite sorunu çözülmeden yalnız çarpana dayanmak sağlıklı değildir."
        )
    return (
        f"{report.symbol} için şirket kalitesi {_score_phrase(quality)}. Değerlendirme {profile} profiline göre "
        f"kârlılık, büyüme, bilanço/sermaye ve nakit göstergelerini birlikte tartıyor. {interpretation} "
        f"{_coverage_phrase(report.coverage)} Eksik alanlar puanı yapay biçimde yükseltmek veya düşürmek için doldurulmuyor."
    )


def _balance_paragraph(report: ResearchReport) -> str:
    financial = report.financial
    metrics = financial.get("metrics", {})
    label = str(financial.get("balance_label", "VERİ YETERSİZ"))
    score = _finite(financial.get("balance_score"))
    score_text = "" if score is None else f"; puan {score:.0f}/100"
    if report.profile == "BANK":
        assets = _finite(metrics.get("assets_growth"))
        equity = _finite(metrics.get("equity_growth"))
        income = _finite(metrics.get("net_income_growth"))
        interpretation = ""
        if assets is not None and equity is not None:
            if assets > 0 and equity > 0:
                interpretation = " Aktifler ve özkaynak aynı yönde büyüyorsa bilanço genişlemesi sermaye tabanıyla daha dengeli ilerliyor."
            elif assets > 0 and equity <= 0:
                interpretation = " Aktif büyümesine özkaynak eşlik etmiyorsa büyümenin sermaye kalitesi ayrıca izlenmeli."
        if income is not None and income < 0:
            interpretation += " Net kâr geriliyorsa bilanço büyümesi tek başına olumlu okunmamalı."
        return (
            f"Bilanço trendi {tr_lower(label)} olarak sınıflanıyor{score_text}. Aktif büyümesi "
            f"{_pct(assets)}, özkaynak büyümesi {_pct(equity)}, net kâr büyümesi {_pct(income)} ve kredi/mevduat "
            f"oranı {_num(metrics.get('loans_deposits'), 2)}. {interpretation.strip()} Resmî SYR, NPL ve karşılık "
            "oranları yoksa banka riski bu veri setiyle tam ölçülemeyeceği için yorum bunların yerine vekil üretmiyor."
        )

    revenue = _finite(metrics.get("revenue_growth"))
    operating = _finite(metrics.get("operating_growth"))
    margin_change = _finite(metrics.get("operating_margin_yoy_change_pp"))
    current_ratio = _finite(metrics.get("current_ratio"))
    signals: list[str] = []
    if revenue is not None and operating is not None:
        if revenue > 10 and operating < 0:
            signals.append(
                "Ciro büyürken faaliyet kârının gerilemesi, büyümenin kâra dönüşmediğini ve satış büyümesinin kalitesinin zayıf olduğunu gösteriyor."
            )
        elif revenue > 0 and operating > 0:
            if operating >= revenue:
                signals.append("Ciro ve faaliyet kârı birlikte büyüyor; faaliyet kârının daha hızlı artması operasyonel kaldıraç açısından olumlu.")
            else:
                signals.append("Ciro ve faaliyet kârı birlikte büyüyor ancak kâr satıştan daha yavaş ilerlediği için marj tarafı ayrıca izlenmeli.")
        elif revenue < 0 and operating < 0:
            signals.append("Hem satış hem faaliyet kârındaki daralma, zayıflığın yalnız marjdan değil faaliyet hacminden de geldiğine işaret ediyor.")
    if margin_change is not None:
        if abs(margin_change) > 100:
            signals.append(
                "Faaliyet marjı değişimi olağan ekonomik aralığın çok dışında; baz etkisi, sınıflama veya kaynak veri kontrol edilmeden bu sayı tek başına yorumlanmamalı."
            )
        elif margin_change <= -3:
            signals.append("Faaliyet marjındaki belirgin daralma, satış büyümesi varsa bile kârlılık kalitesini aşağı çekiyor.")
        elif margin_change >= 3:
            signals.append("Faaliyet marjındaki belirgin genişleme operasyonel iyileşmeyi destekliyor.")
    if current_ratio is not None:
        if current_ratio >= 1.5:
            signals.append("Cari oran kısa vadeli yükümlülükleri karşılama tarafında rahat bir tampon gösteriyor; bu, kârlılık sorununu tek başına telafi etmez.")
        elif current_ratio < 1.0:
            signals.append("Cari oranın 1'in altında olması kısa vadeli likidite tarafında daha sıkı izleme gerektiriyor.")
    interpretation = " ".join(signals) or "Mevcut metrikler aynı yönde güçlü bir bilanço hikâyesi üretmiyor; ana eğilim puan ve veri kapsamıyla birlikte okunmalı."
    return (
        f"Bilanço trendi {tr_lower(label)}{score_text}. TTM satış büyümesi {_pct(revenue)}, faaliyet kârı büyümesi "
        f"{_pct(operating)}, faaliyet marjı değişimi {_num(margin_change)} puan ve cari oran {_num(current_ratio, 2)}. "
        f"{interpretation} Burada asıl soru satışın büyüyüp büyümediğinden çok, bu büyümenin faaliyet kârına ve nakde dönüşüp dönüşmediğidir."
    )


def _earnings_paragraph(report: ResearchReport) -> str:
    financial = report.financial
    metrics = financial.get("metrics", {})
    quality = _dimension(report, "Kâr Kalitesi")
    if quality is None or quality.score is None:
        return (
            "Kâr kalitesini doğrulayacak veri kapsamı yeterli değil. Bu yüzden muhasebe kârı yüksek görünse bile bunun "
            "nakde dönüştüğü söylenemez; aynı şekilde veri eksikliği kötü kâr kalitesi diye de puanlanmıyor. Özellikle "
            "CFO/net kâr, serbest nakit akışı ve tahakkuk göstergeleri görülmeden 'kâr kaliteli' sonucu çıkarılmamalı. "
            "Bu başlık şu an araştırmanın en önemli belirsizliklerinden biri olarak kalıyor."
        )
    if report.profile == "BANK":
        roe = _finite(metrics.get("roe"))
        net_income = _finite(metrics.get("net_income_growth"))
        expense = _finite(metrics.get("operating_expense_growth"))
        interpretation = ""
        if net_income is not None and expense is not None:
            interpretation = (
                " Net kâr büyümesi gider büyümesinin üzerindeyse operasyonel kalite desteklenir."
                if net_income > expense
                else " Gider büyümesi net kârı yakalıyor veya aşıyorsa kâr kalitesinin devamlılığı daha temkinli okunmalı."
            )
        return (
            f"Kâr kalitesi {quality.score:.0f}/100 ile {tr_lower(quality.label)}. Net faiz geliri büyümesi "
            f"{_pct(metrics.get('net_interest_growth'))}, ROE {_pct(roe)}, faaliyet gideri büyümesi {_pct(expense)} ve "
            f"net kâr büyümesi {_pct(net_income)} birlikte değerlendiriliyor.{interpretation} Bankalarda klasik CFO/net "
            "kâr yaklaşımı yerine faiz geliri, özkaynak kârlılığı ve gider disiplini daha anlamlıdır."
        )

    cfo = _finite(metrics.get("cfo_net_income"))
    fcf = _finite(metrics.get("fcf_margin"))
    accrual = _finite(metrics.get("accrual_ratio"))
    receivable_gap = _finite(metrics.get("receivables_vs_sales_gap"))
    inventory_gap = _finite(metrics.get("inventory_vs_sales_gap"))
    signals: list[str] = []
    if cfo is not None:
        if cfo >= 1:
            signals.append("Faaliyet nakit akımının net kârı karşılaması kârın nakde dönüşümünü destekliyor.")
        elif cfo < 0.5:
            signals.append("Faaliyet nakit akımının net kârın belirgin altında kalması muhasebe kârının nakit kalitesini zayıflatıyor.")
    if fcf is not None and fcf < 0:
        signals.append("Negatif serbest nakit akışı, kârın yatırım ve işletme sermayesi sonrası kasada kalmadığını gösteriyor.")
    if accrual is not None and accrual > 10:
        signals.append("Yüksek tahakkuk oranı kârın nakit dışı kalemlere bağımlılığını artırıyor.")
    if receivable_gap is not None and receivable_gap > 10:
        signals.append("Alacakların satışlardan hızlı büyümesi tahsilat kalitesinde izlenmesi gereken bir işaret.")
    if inventory_gap is not None and inventory_gap > 10:
        signals.append("Stokların satışlardan hızlı büyümesi işletme sermayesi ve talep kalitesi açısından izlenmeli.")
    interpretation = " ".join(signals) or "Nakit dönüşümü, serbest nakit ve işletme sermayesi göstergeleri belirgin bir kırmızı bayrak üretmiyor."
    return (
        f"Kâr kalitesi {quality.score:.0f}/100 ile {tr_lower(quality.label)}. CFO/net kâr {_num(cfo, 2)}x, FCF marjı "
        f"{_pct(fcf)}, tahakkuk oranı {_pct(accrual)}; alacak-satış büyüme farkı {_num(receivable_gap)} puan ve "
        f"stok-satış farkı {_num(inventory_gap)} puan. {interpretation}"
    )


def _debt_paragraph(report: ResearchReport) -> str:
    financial = report.financial
    metrics = financial.get("metrics", {})
    if report.profile == "BANK":
        loans = _finite(metrics.get("loans_deposits"))
        eq_assets = _finite(metrics.get("equity_assets"))
        return (
            "Bankalarda klasik net borç/FAVÖK ekonomik olarak anlamlı olmadığı için borçluluk şirketler gibi "
            f"yorumlanmıyor. Kredi/mevduat {_num(loans, 2)}, özkaynak/aktif {_pct(eq_assets)}. Bu göstergeler fonlama "
            "ve sermaye tamponuna dair bağlam verir; resmî sermaye yeterliliği, NPL ve karşılık verisi olmadan banka "
            "riskinin tamamı ölçülmüş sayılmaz."
        )

    direction = str(financial.get("debt_direction", "VERİ YETERSİZ"))
    nde = _finite(metrics.get("net_debt_ebitda"))
    ndeq = _finite(metrics.get("net_debt_equity"))
    debt_change = _finite(metrics.get("net_debt_yoy_change"))
    coverage = _finite(metrics.get("interest_coverage"))
    available = [value for value in (nde, ndeq, debt_change, coverage) if value is not None]
    if not available:
        return (
            f"Borç ve nakit yönü {tr_lower(direction)}; fakat net borç/FAVÖK, net borç/özkaynak, borç değişimi ve "
            "faiz karşılama için güvenilir değer yok. Bu durum 'borç sorunu yok' anlamına gelmez; tam tersine finansal "
            "kaldıraç konusunda şu an sonuç üretilemediğini gösterir. Teknik veya değerleme tezi kurulurken bu belirsizlik "
            "ayrı bir veri boşluğu olarak tutulmalı."
        )
    signals: list[str] = []
    if nde is not None:
        if nde >= 4:
            signals.append("Net borç/FAVÖK yüksek; borcun faaliyet kârıyla taşınabilirliği baskı altında olabilir.")
        elif nde <= 2:
            signals.append("Net borç/FAVÖK görece kontrollü bir kaldıraç seviyesine işaret ediyor.")
    if debt_change is not None:
        if debt_change > 20:
            signals.append("Net borcun hızlı artması kaldıraç yönünü olumsuzlaştırıyor.")
        elif debt_change < -20:
            signals.append("Net borcun belirgin azalması bilanço riskini hafifletiyor.")
    if coverage is not None:
        if coverage < 2:
            signals.append("Faiz karşılama düşük; finansman giderlerine karşı güvenlik marjı dar.")
        elif coverage >= 4:
            signals.append("Faiz karşılama faaliyet kârının finansman giderlerine karşı daha rahat olduğunu gösteriyor.")
    interpretation = " ".join(signals) or "Borç göstergeleri tek yönde güçlü bir sinyal vermiyor; yön ve nakit yaratımı birlikte izlenmeli."
    return (
        f"Borç ve nakit yönü {tr_lower(direction)}. Net borç/FAVÖK {_num(nde, 2)}x, net borç/özkaynak "
        f"{_num(ndeq, 2)}x, net borç değişimi {_pct(debt_change)} ve faiz karşılama {_num(coverage, 2)}x. "
        f"{interpretation}"
    )


def _valuation_paragraph(report: ResearchReport) -> str:
    valuation = report.valuation
    dimension = _dimension(report, "Değerleme")
    if dimension is None or dimension.score is None:
        return (
            "Değerleme tarafında yeterli karşılaştırılabilir çarpan bulunmadığı için ucuz/pahalı hükmü üretilmiyor. "
            "Bu bir 'adil değer' sonucu değildir; yalnızca mevcut veriyle sağlıklı akran kıyası yapılamadığını gösterir."
        )
    names = {
        "pe": "F/K",
        "pb": "PD/DD",
        "ev_ebitda": "FD/FAVÖK",
        "ev_sales": "FD/Satış",
        "dividend_yield": "Temettü",
    }
    parts: list[str] = []
    percentiles: list[tuple[str, float]] = []
    for key, metric_label in names.items():
        item = valuation.get("metrics", {}).get(key, {})
        value = _finite(item.get("value")) if isinstance(item, dict) else None
        percentile = _finite(item.get("percentile")) if isinstance(item, dict) else None
        if value is not None and percentile is not None:
            parts.append(f"{metric_label} {_num(value, 2)} (yüzdelik %{percentile:.0f})")
            percentiles.append((metric_label, percentile))
    metrics_text = "; ".join(parts[:4]) or "karşılaştırılabilir çarpan sayısı sınırlı"
    premium = [label for label, pct in percentiles if pct >= 70]
    discount = [label for label, pct in percentiles if pct <= 30]
    if premium and not discount:
        interpretation = (
            f"Özellikle {', '.join(premium[:2])} akranların pahalı tarafında; piyasa şirkete prim biçiyor. Bu primin "
            "sürdürülebilmesi için kârlılık/büyüme kalitesinin bunu desteklemesi gerekir."
        )
    elif discount and not premium:
        interpretation = (
            f"{', '.join(discount[:2])} akranların ucuz tarafında. Ancak düşük çarpanın fırsat mı yoksa zayıf "
            "beklentinin fiyatlanması mı olduğu şirket kalitesi ve bilanço trendiyle ayrıştırılmalı."
        )
    elif premium and discount:
        interpretation = "Çarpanlar aynı hikâyeyi anlatmıyor; bazı metriklerde prim, bazılarında iskonto olduğu için tek bir 'ucuz/pahalı' etiketi yanıltıcı olabilir."
    else:
        interpretation = "Çarpanlar akran dağılımının orta bölümünde; değerleme tek başına belirgin bir avantaj veya baskı üretmiyor."
    extra = ""
    if report.profile == "GYO":
        extra = " GYO açısından önemli sınırlama şu: gerçek NAD/NAV olmadan PD/NAD iskontosu veya primi ölçülemiyor; yalnız F/K ve PD/DD ile nihai GYO değerleme hükmü verilmemeli."
    elif report.profile == "BANK":
        extra = " Bankada FD/FAVÖK kullanılmadığı için F/K ve PD/DD daha anlamlı akran çarpanlarıdır."
    return (
        f"Değerleme {dimension.score:.0f}/100 ile {tr_lower(dimension.label)}; karşılaştırma evreni "
        f"{valuation.get('scope', '—')}. Başlıca veriler: {metrics_text}. {interpretation}{extra}"
    )


def _levels_paragraph(report: ResearchReport) -> str:
    price = _finite(report.price)
    if report.supports:
        support = report.supports[0]
        support_text = (
            f"en yakın aktif destek {support.low:.2f}–{support.high:.2f} (Q{support.score:.0f}, "
            f"{support.distance_atr:.1f} ATR, {tr_lower(support.status)})"
        )
    else:
        support_text = "fiyatın altında kalite/yakınlık filtresini geçen aktif destek yok"
    if report.resistances:
        resistance = report.resistances[0]
        resistance_text = (
            f"en yakın aktif direnç {resistance.low:.2f}–{resistance.high:.2f} (Q{resistance.score:.0f}, "
            f"{resistance.distance_atr:.1f} ATR, {tr_lower(resistance.status)})"
        )
    else:
        resistance_text = "fiyatın üstünde kalite/yakınlık filtresini geçen aktif direnç yok"

    scenario: list[str] = []
    if not report.supports:
        scenario.append(
            "Aşağıda doğrulanmış yakın destek bulunmaması, mevcut fiyatın altında eski bir pivotu yapay biçimde destek diye göstermemek içindir; aşağı yönlü riskin seviyesi bu veri setinde net tanımlanamıyor."
        )
    if report.resistances:
        resistance = report.resistances[0]
        status = tr_lower(resistance.status)
        if "kır" in status and "destek" in status:
            scenario.append(
                f"{resistance.low:.2f}–{resistance.high:.2f} bölgesi daha önce destekken kırıldığı için artık rol değiştirerek direnç/reclaim alanı sayılıyor; fiyat bu bölgeyi geri almadan eski desteğin yeniden çalıştığı kabul edilmemeli."
            )
        elif price is not None:
            scenario.append("Yukarı senaryonun güçlenmesi için en yakın direnç bölgesinde yalnız temas değil, kapanışla kabul ve mümkünse retest teyidi aranmalı.")
    if report.supports and price is not None:
        scenario.append("Aşağı senaryoda aktif desteğin kapanışla kaybı mevcut yapının zayıfladığını gösterir; yalnız gün içi fitil kırılımı aynı ağırlıkta değerlendirilmemeli.")
    scenario_text = " ".join(scenario)
    return f"Kritik seviyelerde {support_text}; {resistance_text}. {scenario_text}"


def _risk_paragraph(report: ResearchReport) -> str:
    if report.main_risk is None:
        return (
            "Mevcut kanıt setinde 35/100 eşiğini aşan tek bir baskın risk oluşmuyor. Bu 'risk yok' demek değildir; "
            "risklerin birbirinden belirgin ayrışmadığını veya bazı alanlarda verinin yetersiz olduğunu gösterir."
        )
    others = [item for item in report.risks if item.name != report.main_risk.name][:2]
    secondary = "; ".join(f"{item.name} {item.score:.0f}/100" for item in others)
    main_name = tr_lower(report.main_risk.name)
    if "teknik" in main_name:
        meaning = "Bu durumda temel hikâye iyi olsa bile fiyat yapısı teyit vermeden zamanlama riski yüksek kalır."
    elif "değer" in main_name:
        meaning = "Şirket kalitesi olumlu olsa dahi yüksek beklenti fiyatlandığı için hayal kırıklığına tolerans düşer."
    elif "kaldıraç" in main_name or "borç" in main_name:
        meaning = "Faaliyet performansındaki bozulma borç taşıma kapasitesini hızla zorlayabileceği için nakit yaratımı kritik hale gelir."
    elif "likid" in main_name:
        meaning = "Pozisyon büyüklüğü ve çıkış maliyeti normalden daha önemli hale gelir; teknik seviye çalışsa bile işlem riski yüksek olabilir."
    else:
        meaning = "Bu başlık, olumlu tez kurulmadan önce çözülmesi veya fiyat tarafından telafi edilmesi gereken ana zayıflıktır."
    suffix = f" İkincil riskler: {secondary}." if secondary else ""
    return (
        f"Ana risk {report.main_risk.name}; risk puanı {report.main_risk.score:.0f}/100. Dayanak: "
        f"{report.main_risk.evidence} {meaning}{suffix} Veri olmayan bir başlık risksiz kabul edilmiyor; yalnız puanlanabilir kanıt ile veri boşluğu birbirinden ayrılıyor."
    )


def _conclusion_paragraph(report: ResearchReport) -> str:
    scored = [item for item in report.dimensions if item.score is not None]
    strongest = max(scored, key=lambda item: item.score) if scored else None
    weakest = min(scored, key=lambda item: item.score) if scored else None
    risk = report.main_risk
    score_text = "—" if report.research_score is None else f"{report.research_score:.0f}/100"

    if strongest is None:
        thesis = "Olumlu tezi taşıyacak belirgin bir güçlü boyut henüz doğrulanmış değil."
    else:
        thesis = f"Olumlu tezin ana dayanağı {strongest.name} ({strongest.score:.0f}/100)."
    if weakest is None:
        counter = "Belirgin tek bir zayıf boyut ayrışmıyor."
    else:
        counter = f"Buna karşı en zayıf halka {weakest.name} ({weakest.score:.0f}/100)."

    if risk is None:
        action = "Yeni veride özellikle zayıf boyutun iyileşmesi ve kritik seviyelerin korunması genel resmi güçlendirir."
    elif "Teknik" in risk.name:
        action = "Genel görünümün iyileşmesi için önce fiyat yapısında düşüş dizisinin sona ermesi, aktif direncin geri alınması ve bunun hacim/momentumla teyit edilmesi gerekir."
    elif "Değerleme" in risk.name:
        action = "Genel görünümün iyileşmesi için ya kârlılık/büyümenin mevcut primi haklı çıkaracak biçimde güçlenmesi ya da değerleme baskısının fiyatla normalleşmesi gerekir."
    else:
        action = f"Genel görünümün iyileşmesi için özellikle {tr_lower(risk.name)} başlığındaki kanıtların tersine dönmesi gerekir."

    coverage_note = _coverage_phrase(report.coverage)
    return (
        f"Genel araştırma skoru {score_text}. {thesis} {counter} "
        f"{('Ana risk ' + risk.name + f' ({risk.score:.0f}/100). ') if risk else 'Baskın tek risk yok. '}"
        f"{action} {coverage_note} Özetle bu skor bir AL/SAT kararı değil; olumlu tez, karşı tez ve teyit koşullarını aynı anda gösteren araştırma önceliklendirmesidir."
    )
