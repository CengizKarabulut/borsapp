"""Kareleri tek gorselde birlestiren izgara katmani.

Neden ayri bir adim: dort kareyi tek bir matplotlib figuru icinde ic ice
GridSpec'lerle cizmek, panel oranlarini ve satir ici kunyeleri her karo icin
yeniden hesaplamayi gerektirirdi. Bunun yerine her kare kendi basina, tam
kontrolle cizilir; birlestirme piksel duzeyinde yapilir. Boylece tek kare ile
izgara karosu bire bir ayni gorunur.

Karolar farkli yukseklikte olabilir (panel sayilari farkli); satir yuksekligi
o satirdaki en uzun karoya gore belirlenir ve digerleri ustten hizalanir.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .theme import Theme

#: Karolar arasi bosluk ve dis kenar payi (piksel, 1600px karo genisligine gore)
_GUTTER = 18
_MARGIN = 22
_HEADER = 78


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """DejaVu her matplotlib kurulumunda bulunur; ayri yazi tipi indirmeye gerek yok."""
    import matplotlib

    base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(str(base / name), size)
    except OSError:
        return ImageFont.load_default()


def compose_grid(
    tiles: list[Path | str],
    path: str | Path,
    theme: Theme,
    columns: int = 2,
    title: str = "",
    subtitle: str = "",
    tile_width: int | None = None,
) -> Path:
    """Karolari satir/sutun duzeninde tek gorsele yerlestirir.

    tiles: cizilmis PNG yollari, soldan saga ve yukaridan asagiya sirali.
    columns: sutun sayisi (2 -> 2x2, 4 -> 2x4).
    """
    if not tiles:
        raise ValueError("En az bir karo gerekli")

    images = [Image.open(str(t)).convert("RGB") for t in tiles]
    if tile_width:
        images = [
            im.resize((tile_width, round(im.height * tile_width / im.width)),
                      Image.LANCZOS)
            for im in images
        ]

    width = max(im.width for im in images)
    rows = math.ceil(len(images) / columns)
    # Her satirin yuksekligi o satirdaki en uzun karoya gore
    row_heights = [
        max((im.height for im in images[r * columns:(r + 1) * columns]), default=0)
        for r in range(rows)
    ]

    header = _HEADER if (title or subtitle) else 0
    canvas_w = _MARGIN * 2 + width * columns + _GUTTER * (columns - 1)
    canvas_h = _MARGIN * 2 + header + sum(row_heights) + _GUTTER * (rows - 1)

    canvas = Image.new("RGB", (canvas_w, canvas_h), theme.c("bg"))
    draw = ImageDraw.Draw(canvas)

    if header:
        draw.text((_MARGIN, _MARGIN - 2), title, font=_font(30, bold=True),
                  fill=theme.c("text"))
        draw.text((_MARGIN, _MARGIN + 36), subtitle, font=_font(17),
                  fill=theme.c("muted"))
        line_y = _MARGIN + header - 14
        draw.line([(_MARGIN, line_y), (canvas_w - _MARGIN, line_y)],
                  fill=theme.c("axis"), width=1)

    y = _MARGIN + header
    for r in range(rows):
        x = _MARGIN
        for im in images[r * columns:(r + 1) * columns]:
            # Karo cercevesi: koyu zeminde karolarin siniri belirsiz kaliyor
            draw.rectangle([x - 1, y - 1, x + im.width, y + im.height],
                           outline=theme.c("axis"), width=1)
            canvas.paste(im, (x, y))
            x += width + _GUTTER
        y += row_heights[r] + _GUTTER

    for im in images:
        im.close()

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, format="PNG", optimize=True)
    return path
