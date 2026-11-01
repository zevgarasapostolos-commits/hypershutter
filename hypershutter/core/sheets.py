"""Contact sheets: frames tiled in a grid, each labelled with its time (Pillow; this ffmpeg
build has no drawtext). Sheets for the model never show file names or folder paths.

Sized for the high-resolution vision tier (Sonnet 5.5 / Opus 5.5): up to 2576 px on the long
edge and 3.75 MP per image, about (w*h)/750 tokens, capped near 4784.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from hypershutter.core import config, store
from hypershutter.core.frames import Frame, FrameSettings
from hypershutter.core.media import Clip

MAX_EDGE = 2576
MAX_PIXELS = 3_750_000
TOKEN_CAP = 4784
LABEL_COLOUR = (240, 214, 90)     # the yellow of the user's own sheets
FONT_PATHS = ["/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc"]


@dataclass(frozen=True)
class SheetLayout:
    width: int = MAX_EDGE
    cols: int = 6
    rows: int = 4
    label_h: int = 24
    gap: int = 3

    def key(self) -> str:
        return f"w{self.width}_c{self.cols}_r{self.rows}"

    @property
    def per_sheet(self) -> int:
        return self.cols * self.rows

    def tile(self) -> tuple[int, int]:
        tw = (self.width - self.gap * (self.cols + 1)) // self.cols
        return tw, round(tw * 9 / 16)


def _font(size: int) -> ImageFont.ImageFont:
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def image_tokens(w: int, h: int) -> int:
    return min(TOKEN_CAP, math.ceil(w * h / 750))


def render(tiles: list[tuple[str, str]], layout: SheetLayout, out: Path) -> tuple[int, int]:
    """tiles = [(image path, label)]. Letterboxed into 16:9 cells; returns the sheet size."""
    tw, th = layout.tile()
    cols = min(layout.cols, len(tiles))
    rows = math.ceil(len(tiles) / layout.cols)
    w = cols * tw + (cols + 1) * layout.gap
    h = rows * (th + layout.label_h) + (rows + 1) * layout.gap
    sheet = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    font = _font(layout.label_h - 7)
    for i, (path, label) in enumerate(tiles):
        r, c = divmod(i, layout.cols)
        x = layout.gap + c * (tw + layout.gap)
        y = layout.gap + r * (th + layout.label_h + layout.gap)
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((tw, th), Image.LANCZOS)
                sheet.paste(im, (x + (tw - im.width) // 2, y + (th - im.height) // 2))
        except OSError:
            draw.rectangle([x, y, x + tw, y + th], outline=(80, 80, 80))
        tl = draw.textlength(label, font=font)
        draw.text((x + (tw - tl) / 2, y + th + 3), label, fill=LABEL_COLOUR, font=font)
    assert w <= MAX_EDGE and h <= MAX_EDGE and w * h <= MAX_PIXELS, (w, h)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=85)
    return w, h


def _clock(t: float) -> str:
    s = int(t)
    return f"{s // 60}:{s % 60:02d}" if s < 3600 else f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def clip_sheets(clip: Clip, frames: list[Frame], start: datetime | None, settings: FrameSettings,
                layout: SheetLayout = SheetLayout(), variant: str = "") -> list[Path]:
    """Sheets for the model: label = time in clip · corrected time of day. No file names.
    `variant` separates the cache of a subsampled frame set from the full one."""
    key = store.file_key(clip.name, clip.size, clip.mtime)
    d = config.cache_dir("sheets", hashlib.sha1(key.encode()).hexdigest()[:20],
                         f"{settings.key()}_{layout.key()}{variant}")
    paths = []
    for k in range(0, len(frames), layout.per_sheet):
        chunk = frames[k:k + layout.per_sheet]
        out = d / f"sheet_{k // layout.per_sheet:03d}.jpg"
        if not out.exists():
            tiles = []
            for f in chunk:
                label = _clock(f.t)
                if start:
                    label += f" · {start + timedelta(seconds=f.t):%H:%M:%S}"
                tiles.append((f.path, label))
            render(tiles, layout, out)
        paths.append(out)
    return paths


def sheet_shapes(n_frames: int, layout: SheetLayout = SheetLayout()) -> list[tuple[int, int]]:
    """Pixel sizes of the sheets n frames will produce (for cost estimates without rendering)."""
    tw, th = layout.tile()
    shapes = []
    for k in range(0, n_frames, layout.per_sheet):
        n = min(layout.per_sheet, n_frames - k)
        cols, rows = min(layout.cols, n), math.ceil(n / layout.cols)
        shapes.append((cols * tw + (cols + 1) * layout.gap, rows * (th + layout.label_h) + (rows + 1) * layout.gap))
    return shapes
