"""Visual 20-equity morning pivot cards from confirmed, dated OHLCV results.

Only render levels computed from real previous-session OHLCV. Each panel
displays twenty exact user-pinned securities (last panel may contain fewer).
"""
from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw
from scripts.atc_timeframe_visuals import _font

PER_CARD = 20
WIDTH = 1536
ROW_HEIGHT = 51
BG = "#F1F5F9"
NAVY = "#112E4A"
MUTED = "#5D728A"
ACCENT = "#087B7A"
DIVIDER = "#D6E0EA"


def visual_rows(rows):
    """Retain the user's full 630-share inventory; never suppress missing bars."""
    if len(rows) != 630 or len({row[0] for row in rows}) != 630:
        raise ValueError("Morning cards require exactly 630 unique pinned tickers")
    return sorted(rows, key=lambda row: row[0])


def render_morning_png(*, last_session, rows, page, pages, total_verified):
    if not 1 <= len(rows) <= PER_CARD:
        raise ValueError("One card must contain 1-20 real securities")
    if page < 1 or page > pages:
        raise ValueError("Page number invalid")
    height = 315 + len(rows) * ROW_HEIGHT + 85
    img = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((22, 20, WIDTH - 22, height - 18),
                           radius=20, fill="#FFFFFF")
    draw.rectangle((22, 20, WIDTH - 22, 112), fill=NAVY)
    draw.text((54, 38), "ALPHA TREND CIPHER | GÜNLÜK DESTEK & DİRENÇ",
              font=_font(29, bold=True), fill="#FFFFFF")
    draw.text((54, 143), f"{last_session:%d.%m.%Y} | ÖNCEKİ SEANS TEYİTLİ KAPANIŞI",
              font=_font(22, bold=True), fill=NAVY)
    draw.text((54, 183), f"630 hisse  |  Geçerli veri {total_verified}/630  |  Klasik Pivot (H/L/C)",
              font=_font(20), fill=MUTED)
    draw.text((54, 225), "HİSSE", font=_font(20, bold=True), fill=MUTED)
    for x, name in ((325, "S2"), (510, "S1"), (687, "PİVOT"),
                    (892, "R1"), (1075, "R2"), (1288, "KAYNAK")):
        draw.text((x, 225), name, font=_font(19, bold=True), fill=MUTED)
    draw.line((54, 257, WIDTH-56, 257), fill=DIVIDER, width=2)

    for idx, entry in enumerate(rows):
        symbol, levels, _turnover, status, *extra = entry
        top = 265 + idx * ROW_HEIGHT
        if idx % 2 == 0:
            draw.rounded_rectangle((44, top, WIDTH - 44, top + ROW_HEIGHT - 1),
                                   radius=6, fill="#F6F9FC")
        draw.text((57, top + 12), f"#{symbol}",
                  font=_font(20, bold=True), fill=NAVY)
        if status != "TEYITLI" or levels is None:
            draw.text((325, top + 12), "TEYİTLİ VERİ YOK",
                      font=_font(18, bold=True), fill="#AC4D40")
            continue
        s1, s2, pivot, r1, r2 = levels
        for x, number in zip((325, 510, 687, 892, 1075),
                             (s2, s1, pivot, r1, r2), strict=True):
            display = f"{number:.4f}" if number < 2 else f"{number:.2f}"
            draw.text((x, top + 12), display, font=_font(20, bold=x == 687),
                      fill=ACCENT if x == 687 else NAVY)
        source = extra[0] if extra else ""
        short = source.split("/")[0].replace("tvdatafeed", "TV").replace(
            "yfinance", "Yahoo").replace("borsapy", "Borsapy")
        draw.text((1288, top + 14), short[:13], font=_font(16), fill=MUTED)

    draw.line((54, height-112, WIDTH-56, height-112), fill=DIVIDER, width=1)
    draw.text((54, height-94), f"SAYFA {page}/{pages}  |  {len(rows)} HİSSE",
              font=_font(21, bold=True), fill=NAVY)
    draw.text((54, height-60),
              "Kapanış verilerinin fiyat bazları CSV'de. Pivotlar al-sat hedefi değildir. YTD.",
              font=_font(17), fill=MUTED)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def build_visual_pages(*, last_session, rows, total_verified):
    ordered = visual_rows(rows)
    count = math.ceil(len(ordered) / PER_CARD)
    result = []
    for offset in range(0, len(ordered), PER_CARD):
        page = offset // PER_CARD + 1
        segment = ordered[offset:offset + PER_CARD]
        result.append((
            page, segment, render_morning_png(
                last_session=last_session, rows=segment, page=page,
                pages=count, total_verified=total_verified,
            ),
        ))
    return result
