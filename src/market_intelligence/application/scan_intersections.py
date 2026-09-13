"""Same-direction intersections. Counts represent agreement, not win probability."""

from __future__ import annotations

from collections import defaultdict


def timeframe_intersections(details, limit=20):
    grouped = defaultdict(lambda: {"bullish": {}, "bearish": {}})
    for item in details:
        if item["direction"] in ("bullish", "bearish"):
            grouped[item["symbol"]][item["direction"]].setdefault(item["scanner"], item)
    result = []
    for symbol, sides in grouped.items():
        direction = min(sides, key=lambda side: (-len(sides[side]), side))
        matches = sides[direction]
        if len(matches) < 2:
            continue
        opposite = "bearish" if direction == "bullish" else "bullish"
        scanners = sorted(matches)
        plan_scanner = next(
            (s for s in scanners if matches[s]["plan"].get("scenarios")), scanners[0]
        )
        result.append(
            {
                "symbol": symbol,
                "direction": direction,
                "scanners": scanners,
                "count": len(scanners),
                "opposing": sorted(sides[opposite]),
                "plan": matches[plan_scanner]["plan"],
                "plan_scanner": plan_scanner,
                "direction_tie": len(matches) == len(sides[opposite]),
            }
        )
    result.sort(key=lambda item: (-item["count"], item["symbol"]))
    return result if limit is None else result[:limit]


def cross_timeframe_intersections(by_timeframe, limit=20):
    # Use the full eligible sets, not each timeframe's truncated top 20.
    grouped = defaultdict(lambda: defaultdict(dict))
    for timeframe, details in by_timeframe.items():
        for item in timeframe_intersections(details, limit=None):
            if not item["direction_tie"]:
                grouped[item["symbol"]][item["direction"]][timeframe] = item
    result = []
    for symbol, directions in grouped.items():
        candidates = []
        for direction, frames in directions.items():
            names = sorted({s for item in frames.values() for s in item["scanners"]})
            candidates.append((direction, frames, names))
        direction, frames, names = min(candidates, key=lambda v: (-len(v[1]), -len(v[2]), v[0]))
        if len(frames) < 2:
            continue
        result.append(
            {
                "symbol": symbol,
                "direction": direction,
                "timeframes": frames,
                "timeframe_count": len(frames),
                "scanners": names,
                "count": len(names),
                "opposing_timeframes": sorted(
                    {tf for side, items in directions.items() if side != direction for tf in items}
                ),
            }
        )
    result.sort(key=lambda item: (-item["timeframe_count"], -item["count"], item["symbol"]))
    return result[:limit]


def render_intersections(title, ranked, slot, *, targets, coverage, global_view=False):
    import io
    import textwrap
    from pathlib import Path

    from PIL import Image, ImageDraw, ImageFont

    from market_intelligence.application.live_scans import LABELS

    font_path = next(
        (
            p
            for p in (
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                Path("C:/Windows/Fonts/arial.ttf"),
            )
            if p.exists()
        ),
        None,
    )
    if font_path is None:
        raise RuntimeError("Unicode font unavailable")

    def font(size):
        return ImageFont.truetype(str(font_path), size)

    def names(scanners):
        return " + ".join(LABELS.get(s, s) for s in scanners)

    def wrap(line):
        return textwrap.wrap(line, width=99, break_long_words=False, break_on_hyphens=False) or [""]

    def price_line(item):
        plan = item["plan"]
        side = "long" if item["direction"] == "bullish" else "short"
        v = next((v for v in plan.get("scenarios", []) if v["side"] == side), None)
        if v is None:
            return "Giriş / stop / TP: hesaplanamadı"
        values = "   |   ".join(
            f"{label} {v[key]:.2f}"
            for key, label in (
                ("entry", "Giriş*"),
                ("stop", "Stop"),
                ("tp1", "TP1"),
                ("tp2", "TP2"),
                ("tp3", "TP3"),
            )
        )
        return values + f"   |   Risk %{v['risk_pct']:.2f}"

    cards = []
    for i, item in enumerate(ranked, 1):
        side = "YUKARI" if item["direction"] == "bullish" else "AŞAĞI"
        heading = f"{i:02}   {item['symbol']}   /   {side}   /   {item['count']} farklı tarama"
        lines = []
        if global_view:
            heading += f"   /   {item['timeframe_count']} zaman dilimi"
            for tf, detail in item["timeframes"].items():
                lines += wrap(f"{tf} ({targets[tf]}): {names(detail['scanners'])}")
                if detail["opposing"]:
                    lines += wrap(f"{tf} zıt bulgular: {names(detail['opposing'])}")
            if item["opposing_timeframes"]:
                lines += wrap(
                    "Zıt yönün baskın olduğu zaman dilimleri: "
                    + ", ".join(item["opposing_timeframes"])
                )
        else:
            lines += wrap(names(item["scanners"]))
            lines += wrap(price_line(item))
            basis = (
                "Bölünmeye düzeltilmiş"
                if item["plan"].get("price_basis") == "split_adjusted"
                else "Ham"
            )
            lines += wrap(
                f"{basis} fiyat referansı • Plan kaynağı: {LABELS.get(item['plan_scanner'], item['plan_scanner'])}"
            )
            if item["opposing"]:
                lines += wrap(
                    ("YÖN EŞİT / ÇELİŞKİ: " if item["direction_tie"] else "Zıt bulgular: ")
                    + names(item["opposing"])
                )
        cards.append((heading, lines, side))
    if not cards:
        cards = [
            (
                "Uygun kesişim bulunamadı",
                [
                    "Liste en az iki aynı yönlü tarama gerektirir; 20 satıra tamamlamak için doldurulmaz."
                ],
                "",
            )
        ]
    pages = []
    group = []
    used = 0
    for card in cards:
        height = 80 + len(card[1]) * 31
        if group and used + height > 2350:
            pages.append(group)
            group = []
            used = 0
        group.append(card)
        used += height
    if group:
        pages.append(group)
    images = []
    for page, items in enumerate(pages, 1):
        height = 390 + sum(80 + len(c[1]) * 31 for c in items)
        image = Image.new("RGB", (1440, height), "#0B1220")
        d = ImageDraw.Draw(image)

        def draw(x, y, text, size=24, color="#ECF2FA", d=d):
            d.text((x, y), text, font=font(size), fill=color)

        d.rectangle((0, 0, 1440, 8), fill="#42D6B3")
        draw(42, 28, "BORSAPP  /  KESİŞİM MASASI", 33)
        draw(
            42, 81, f"{title} • İlk 20 • {len(ranked)} uygun hisse • Sayfa {page}/{len(pages)}", 27
        )
        draw(42, 126, f"Üretim {slot:%d.%m.%Y %H:%M} • " + coverage, 19, "#9AACBF")
        if not global_view:
            draw(42, 160, "Kapanış: " + next(iter(targets.values())), 20, "#9AACBF")
        y = 210
        for heading, lines, side in items:
            cardheight = 64 + 31 * len(lines)
            d.rounded_rectangle((28, y - 8, 1412, y + cardheight), radius=12, fill="#132136")
            draw(44, y + 5, heading, 25, "#42D6B3" if side == "YUKARI" else "#FFABB1")
            for j, line in enumerate(lines):
                draw(44, y + 49 + j * 31, line, 22)
            y += cardheight + 16
        draw(
            42,
            height - 138,
            "Sıra: "
            + (
                "zaman dilimi sayısı → farklı tarama sayısı → hisse kodu"
                if global_view
                else "aynı yöndeki farklı tarama sayısı → hisse kodu"
            ),
            21,
            "#9AACBF",
        )
        draw(
            42,
            height - 101,
            "Kesişim sayısı başarı olasılığı değildir. Yönsüz bulgular oy sayılmaz; eksik kapsam korunur.",
            20,
            "#9AACBF",
        )
        draw(
            42,
            height - 64,
            "Zaman dilimlerinin fiyatları birleştirilmez. * Giriş kapanış referansıdır; gerçekleşmiş emir değildir.",
            19,
            "#9AACBF",
        )
        images.append(image)
    pngs = []
    for image in images:
        out = io.BytesIO()
        image.save(out, format="PNG")
        pngs.append(out.getvalue())
    pdf = io.BytesIO()
    images[0].save(pdf, format="PDF", save_all=True, append_images=images[1:], resolution=144)
    return tuple(pngs), pdf.getvalue()
