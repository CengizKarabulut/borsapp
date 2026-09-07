"""Analist kartı görseli.

Telegram'da uzun düz metin yerine okunabilir bir kart üretir. Kart yalnızca
mevcut yorum çıktısını görselleştirir; yeni bir hesap veya iddia içermez.
Yükseklik içeriğe göre hesaplanır, böylece metin hiçbir zaman kırpılmaz.
"""

from __future__ import annotations

import math
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from src.plain_language import bar_state_plain

BG = "#0f172a"
PANEL = "#111827"
CARD = "#16202e"
WHITE = "#f8fafc"
MUTED = "#cbd5e1"
ACCENT = "#38bdf8"
LIGHT_GREEN = "#22c55e"
LIGHT_RED = "#ef4444"
YELLOW = "#eab308"
GRAY = "#64748b"

CARD_WIDTH_INCHES = 12.0
DPI = 100
MARGIN = 0.66
LINE_HEIGHT = 0.342
TITLE_HEIGHT = 0.62
SECTION_GAP = 0.31


def tone_colour(tone: str) -> str:
    return {
        "positive": LIGHT_GREEN,
        "negative": LIGHT_RED,
        "warning": YELLOW,
        "neutral": MUTED,
    }.get(tone, MUTED)


def _evidence_caption(item: dict[str, Any]) -> str:
    family = str(item.get("family", "Teknik gösterge"))
    state = str(item.get("state", "karışık"))
    lowered = family.casefold()
    if "uyumsuzluk" in lowered:
        indicator = family.partition("(")[2].partition(")")[0].upper() or "Momentum"
        trust = "orta güven" if "orta" in state.casefold() else "erken uyarı"
        return f"{indicator}: Fiyat düşerken göstergede toparlanma ihtimali ({trust})."
    if "göreceli" in lowered:
        return "Endekse göre performans: Hisse karşılaştırılan endeksten daha zayıf."
    if "mtf" in lowered or "zaman" in lowered:
        return "Zaman dilimleri: Günlük, haftalık ve aylık görünüm aynı yönde değil."
    if "katılım" in lowered or "hacim" in lowered:
        return "Hacim: İşlem hacmi fiyat hareketini yeterince desteklemiyor."
    if "yapı" in lowered:
        return "Fiyat yapısı: Son tepe ve dipler aşağı yönlü."
    return f"{family}: {state}"


def _wrap(text: str, font_size: int, width_inches: float, weight: str = "normal") -> list[str]:
    """Metni kart genişliğine göre satırlara böler; kalın yazı daha geniş sayılır."""
    character_width = font_size * (0.60 if weight == "bold" else 0.52)
    characters = max(int(width_inches * 72 / character_width), 20)
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        lines.extend(textwrap.wrap(paragraph, characters) or [""])
    return lines


class _Block:
    def __init__(self, kind: str, text: str, font_size: int, colour: str, weight: str = "normal") -> None:
        self.kind = kind
        self.text = text
        self.font_size = font_size
        self.colour = colour
        self.weight = weight
        self.lines: list[str] = []

    def measure(self, width_inches: float) -> float:
        if self.kind == "gap":
            return SECTION_GAP
        if self.kind == "section":
            self.lines = [self.text]
            return TITLE_HEIGHT
        self.lines = _wrap(self.text, self.font_size, width_inches, self.weight)
        return len(self.lines) * LINE_HEIGHT * (self.font_size / 12.0)


def _summary_blocks(commentary: dict[str, Any]) -> list[_Block]:
    """1. kart: hikâye, son iki mum ve açık sonuç."""
    setup = commentary.get("setup", {})
    clarity = commentary.get("clarity", {})
    story = commentary.get("market_story") or commentary.get("plain_summary", {}).get("text", "—")
    candle_story = commentary.get("candle_story", "Son iki mum için formasyon özeti üretilemedi.")
    conclusion = commentary.get("general_interpretation", "Net bir genel sonuç üretilemedi.")
    blocks = [
        _Block("section", "PİYASANIN HİKÂYESİ", 23, ACCENT),
        _Block("body", story, 20, WHITE),
        _Block("gap", "", 12, WHITE),
        _Block("section", "SON İKİ MUM NE DİYOR?", 23, ACCENT),
        _Block("body", candle_story, 18, MUTED),
        _Block("gap", "", 12, WHITE),
        _Block("section", "NET SONUÇ", 23, ACCENT),
        _Block("body", conclusion, 20, tone_colour(commentary.get("tone", "neutral")), "bold"),
        _Block("gap", "", 12, WHITE),
        _Block("section", "KURULUM", 23, ACCENT),
        _Block("body", f"{setup.get('name', '—')}  •  eğilim: {setup.get('bias', '—')}", 20, tone_colour(setup.get("tone", "neutral")), "bold"),
    ]
    if setup.get("description"):
        blocks.append(_Block("body", setup["description"], 17, MUTED))
    blocks.append(_Block("gap", "", 12, WHITE))
    blocks.append(
        _Block("body", f"Okuma netliği: {clarity.get('state', '—')} — {clarity.get('reason', '')}", 17, tone_colour(clarity.get("tone", "neutral")))
    )
    return blocks

def _note_blocks(commentary: dict[str, Any]) -> list[_Block]:
    """2. kart: analist notu, gerekçe ve kanıt dengesi."""
    setup = commentary.get("setup", {})
    blocks: list[_Block] = []
    paragraphs = [item.strip() for item in str(commentary.get("analyst_note", "")).split("\n\n") if item.strip()]
    if setup.get("name") and len(paragraphs) > 1:
        paragraphs = paragraphs[1:]
    if paragraphs:
        blocks.append(_Block("section", "ANALİST NOTU", 23, ACCENT))
        for paragraph in paragraphs:
            blocks.append(_Block("body", paragraph, 18, WHITE))
            blocks.append(_Block("gap", "", 11, WHITE))
    blocks.append(_Block("section", "NEDEN BU OKUMA?", 23, ACCENT))
    blocks.append(_Block("body", commentary.get("reconciliation", "—"), 18, MUTED))
    supporting = commentary.get("supporting_evidence", [])
    counter = commentary.get("counter_evidence", [])
    if supporting or counter:
        blocks.append(_Block("gap", "", 12, WHITE))
        blocks.append(_Block("section", "KANIT DENGESİ", 23, ACCENT))
        for item in supporting:
            blocks.append(_Block("body", f"▲  {_evidence_caption(item)}", 18, LIGHT_GREEN))
        for item in counter:
            blocks.append(_Block("body", f"▼  {_evidence_caption(item)}", 18, LIGHT_RED))
    return blocks


def _level_blocks(commentary: dict[str, Any], limit: int = 4) -> list[_Block]:
    """3. kart: seviyeler, senaryo eşikleri ve son değişimler."""
    setup = commentary.get("setup", {})
    scenario = commentary.get("scenario_map", {})
    labels = scenario.get("labels", {})
    clusters = commentary.get("levels", {}).get("clusters", [])
    blocks: list[_Block] = []
    if clusters:
        blocks.append(_Block("section", "TEKNİK YOĞUNLAŞMA BÖLGELERİ", 23, ACCENT))
        for cluster in clusters[:limit]:
            members = ", ".join(cluster.get("members", [])[:5])
            low, high = float(cluster["low"]), float(cluster["high"])
            span = f"{low:,.2f}" if abs(high - low) < 0.005 else f"{low:,.2f} – {high:,.2f}"
            blocks.append(
                _Block(
                    "body",
                    f"{span}   {cluster.get('side', '')} ({cluster.get('strength', '')})   →  {members}",
                    18,
                    MUTED,
                )
            )
        blocks.append(_Block("gap", "", 12, WHITE))
    two_sided = str(setup.get("bias", "")) == "iki yönlü"
    for key, colour in (("strengthen", LIGHT_GREEN), ("weaken", LIGHT_RED), ("neutral", MUTED)):
        items = scenario.get(key, [])
        if not items:
            continue
        blocks.append(_Block("section", str(labels.get(key, key)).upper(), 22, ACCENT))
        for item in items:
            if two_sided and key == "strengthen":
                lowered = item.casefold()
                line_colour = LIGHT_GREEN if "yukarı" in lowered else LIGHT_RED if "aşağı" in lowered else MUTED
            else:
                line_colour = colour
            blocks.append(_Block("body", f"•  {item}", 18, line_colour))
        blocks.append(_Block("gap", "", 12, WHITE))
    changes = commentary.get("changes", [])
    if changes:
        blocks.append(_Block("section", "DÜNDEN BUGÜNE", 22, ACCENT))
        for item in changes[:limit]:
            blocks.append(_Block("body", f"•  {item}", 18, MUTED))
    return blocks


def _overview_blocks(commentary: dict[str, Any], limit: int = 4) -> list[_Block]:
    """1. kart: sade özet, kurulum, okuma netliği ve kanıt dengesi."""
    blocks = _summary_blocks(commentary)
    supporting = commentary.get("supporting_evidence", [])
    counter = commentary.get("counter_evidence", [])
    if supporting or counter:
        blocks.append(_Block("gap", "", 12, WHITE))
        blocks.append(_Block("section", "KANIT DENGESİ", 23, ACCENT))
        for item in supporting:
            blocks.append(_Block("body", f"▲  {_evidence_caption(item)}", 18, LIGHT_GREEN))
        for item in counter:
            blocks.append(_Block("body", f"▼  {_evidence_caption(item)}", 18, LIGHT_RED))
    return blocks


def _detail_blocks(commentary: dict[str, Any], limit: int = 4) -> list[_Block]:
    """2. kart: dört grubun kısa anlamı, gerekçe, seviyeler ve senaryolar."""
    blocks: list[_Block] = [_Block("section", "DÖRT GÖSTERGE GRUBU", 23, ACCENT)]
    for item in commentary.get("indicator_schemas", []):
        tone = tone_colour(item.get("tone", "neutral"))
        blocks.append(_Block("body", f"{item.get('name', 'Grup')} — {item.get('state', '—')}", 18, tone, "bold"))
        if item.get("guide"):
            blocks.append(_Block("body", f"NASIL OKUNUR?  {item['guide']}", 16, MUTED))
        if item.get("stock_comment"):
            blocks.append(_Block("body", f"BU HİSSEDE NE SÖYLÜYOR?  {item['stock_comment']}", 17, WHITE, "bold"))
        if item.get("reading"):
            blocks.append(_Block("body", f"GÖSTERGE DEĞERLERİ  {item['reading']}", 14, GRAY))
        if item.get("confirmation"):
            blocks.append(_Block("body", f"TEYİT  {item['confirmation']}", 15, LIGHT_GREEN))
        if item.get("risk"):
            blocks.append(_Block("body", f"RİSK  {item['risk']}", 15, YELLOW))
        if not item.get("guide") and item.get("plain"):
            blocks.append(_Block("body", item["plain"], 16, MUTED))
        blocks.append(_Block("gap", "", 12, WHITE))
    blocks.append(_Block("section", "NEDEN BU OKUMA?", 23, ACCENT))
    blocks.append(_Block("body", commentary.get("reconciliation", "—"), 17, MUTED))
    blocks.append(_Block("gap", "", 12, WHITE))
    blocks.extend(_level_blocks(commentary, limit))
    return blocks

CARD_PAGES = (
    ("Özet", _overview_blocks),
    ("Analiz ve Seviyeler", _detail_blocks),
)


def _blocks(status: dict[str, Any]) -> list[_Block]:
    """Geriye dönük uyumluluk: üç sayfanın bloklarını tek listede verir."""
    commentary = status.get("technical_commentary", {})
    combined: list[_Block] = []
    for _, builder in CARD_PAGES:
        combined.extend(builder(commentary))
    return combined


def render_analyst_card(status: dict[str, Any], output: Path, blocks: list[_Block] | None = None, page_label: str = "") -> Path:
    """Verilen blokları okunabilir bir PNG kartına dönüştürür."""
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.family"] = "DejaVu Sans"
    text_width = CARD_WIDTH_INCHES - 2 * MARGIN
    blocks = _blocks(status) if blocks is None else blocks
    heights = [block.measure(text_width) for block in blocks]
    header_height = 1.86
    total = header_height + sum(heights) + 2 * MARGIN

    figure = plt.figure(figsize=(CARD_WIDTH_INCHES, total), dpi=DPI, facecolor=BG)
    axes = figure.add_axes([0, 0, 1, 1])
    axes.set_xlim(0, CARD_WIDTH_INCHES)
    axes.set_ylim(0, total)
    axes.axis("off")
    axes.add_patch(
        FancyBboxPatch(
            (MARGIN * 0.4, MARGIN * 0.4),
            CARD_WIDTH_INCHES - MARGIN * 0.8,
            total - MARGIN * 0.8,
            boxstyle="round,pad=0.02,rounding_size=0.12",
            facecolor=CARD,
            edgecolor="#233046",
            linewidth=1.2,
        )
    )

    cursor = total - MARGIN
    symbol = status.get("symbol", "—")
    price = status.get("price", float("nan"))
    change = status.get("change_pct", 0.0)
    bar_state = status.get("bar_state", {})
    heading = f"{symbol} — {page_label}" if page_label else f"{symbol} — Analist Kartı"
    axes.text(MARGIN, cursor - 0.34, heading, color=WHITE, fontsize=36, fontweight="bold", va="top")
    cursor -= 0.94
    # Tarama kartında fiyat/değişim yerine serbest bir başlık satırı kullanılır.
    headline = status.get("header_line")
    if headline:
        axes.text(MARGIN, cursor - 0.20, str(headline), color=WHITE, fontsize=22, fontweight="bold", va="top")
    else:
        change_colour = LIGHT_GREEN if change >= 0 else LIGHT_RED
        axes.text(MARGIN, cursor - 0.18, f"{price:,.2f}", color=WHITE, fontsize=29, fontweight="bold", va="top")
        axes.text(MARGIN + 2.05, cursor - 0.26, f"{change:+.2f}%", color=change_colour, fontsize=24, fontweight="bold", va="top")
        axes.text(
            MARGIN + 4.02,
            cursor - 0.19,
            bar_state_plain(bar_state),
            color=MUTED,
            fontsize=14,
            va="top",
        )
    axes.text(
        MARGIN + 4.02,
        cursor - 0.50,
        f"{status.get('timestamp', '—')}  |  {status.get('data_provider', '—')}",
        color=GRAY,
        fontsize=12,
        va="top",
    )
    cursor -= 0.74
    axes.plot([MARGIN, CARD_WIDTH_INCHES - MARGIN], [cursor, cursor], color="#233046", linewidth=1.4)
    cursor -= 0.22

    for block, height in zip(blocks, heights, strict=True):
        if block.kind == "gap":
            cursor -= height
            continue
        if block.kind == "section":
            axes.text(MARGIN, cursor - 0.24, block.text, color=block.colour, fontsize=block.font_size, fontweight="bold", va="top")
            cursor -= height
            continue
        step = LINE_HEIGHT * (block.font_size / 12.0)
        for line in block.lines:
            axes.text(MARGIN, cursor - step * 0.72, line, color=block.colour, fontsize=block.font_size, fontweight=block.weight, va="top")
            cursor -= step

    figure.savefig(output, facecolor=BG, dpi=DPI)
    plt.close(figure)
    return output


MAX_ASPECT_RATIO = 2.2


def _paginate(blocks: list[_Block], text_width: float, budget: float) -> list[list[_Block]]:
    """Blokları, hiçbir sayfa yükseklik bütçesini aşmayacak biçimde böler.

    Telegram çok uzun görselleri yükseklik sınırına sığdırmak için daraltır ve
    yazı okunmaz hale gelir; bu yüzden sayfa oranı sınırlanır.
    """
    heights = [block.measure(text_width) for block in blocks]
    total = sum(heights)
    page_count = max(1, math.ceil(total / budget))
    target = total / page_count
    pages: list[list[_Block]] = []
    current: list[_Block] = []
    used = 0.0
    for index, (block, height) in enumerate(zip(blocks, heights, strict=True)):
        remaining = page_count - len(pages)
        # Kalın grup başlığı, hemen ardından gelen açıklamadan ayrılmaz.
        linked_height = 0.0
        if index + 1 < len(blocks):
            next_block = blocks[index + 1]
            if (block.kind == "section" and next_block.kind != "gap") or (
                block.kind == "body"
                and block.weight == "bold"
                and next_block.kind == "body"
                and next_block.weight != "bold"
            ):
                linked_height = heights[index + 1]
        projected = used + height + linked_height
        exceeds_budget = current and projected > budget
        balanced_break = current and remaining > 1 and projected - height / 2 > target and len(blocks) - index >= remaining - 1
        if exceeds_budget or balanced_break:
            pages.append(current)
            current, used = [], 0.0
        if not current and block.kind == "gap":
            continue
        current.append(block)
        used += height
    if current:
        pages.append(current)
    return pages or [[]]


DETAIL_SETTINGS = {
    "kompakt": {"ratio": 2.7, "limit": 3},
    "dengeli": {"ratio": 2.2, "limit": 4},
    "tam": {"ratio": 2.2, "limit": 4},
}


def render_analyst_cards(status: dict[str, Any], directory: Path, stem: str = "analyst_card") -> list[Path]:
    """Yorumu okunabilir kartlara böler; ayrıntı seviyesi sayfa sayısını belirler."""
    commentary = status.get("technical_commentary", {})
    settings = DETAIL_SETTINGS.get(str(status.get("report_detail", "dengeli")), DETAIL_SETTINGS["dengeli"])
    text_width = CARD_WIDTH_INCHES - 2 * MARGIN
    budget = CARD_WIDTH_INCHES * settings["ratio"] - 2.6
    # Bölümler ayrı ayrı sayfalanırsa kısa bölüm yarı boş bir sayfa üretir; tüm
    # bloklar tek akışta toplanıp eşit dağıtılır. Bölüm başlıkları blokların
    # içinde zaten yer aldığı için bilgi kaybı olmaz.
    blocks: list[_Block] = []
    for _, builder in CARD_PAGES:
        blocks.extend(builder(commentary, settings["limit"]))
    chunks = _paginate(blocks, text_width, budget)
    paths: list[Path] = []
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        label = "Analist Kartı" if total == 1 else f"Analist Kartı {index}/{total}"
        paths.append(render_analyst_card(status, directory / f"{stem}_{index}.png", chunk, label))
    return paths

def standardize_pages(paths: list[Path], background: str = BG) -> list[Path]:
    """Sayfaların yalnız genişliğini eşitler; yüksekliğe boş dolgu eklemez.

    Telegram albümünde ortak genişlik korunurken her görsel kendi içeriği kadar
    uzar. Böylece kısa sayfaların altında büyük, boş renk alanları oluşmaz.
    """
    if not paths:
        return paths
    from PIL import Image

    sizes = []
    for path in paths:
        with Image.open(path) as image:
            sizes.append(image.size)
    target_width = max(width for width, _ in sizes)
    for path, (width, height) in zip(paths, sizes, strict=True):
        if width == target_width:
            continue
        target_height = max(1, round(height * target_width / width))
        with Image.open(path) as image:
            resized = image.convert("RGB").resize((target_width, target_height), Image.Resampling.LANCZOS)
            resized.save(path)
    return paths
