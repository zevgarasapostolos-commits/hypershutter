"""The app icon: build/HyperShutter.icns from assets/branding/AppIcon.iconset (the designed icon).
Without it, a placeholder (slate "HS" in a gold ring) is drawn instead."""

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SLATE, GOLD, WHITE = (64, 83, 102), (165, 151, 105), (250, 248, 243)


def font(size: int):
    for f in ("/System/Library/Fonts/NewYork.ttf", "/System/Library/Fonts/Supplemental/Georgia.ttf",
              "/System/Library/Fonts/Times.ttc"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def draw(size: int = 1024) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = size * 0.09
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=size * 0.2, fill=WHITE)
    r = size * 0.30
    c = size / 2
    d.ellipse([c - r, c - r, c + r, c + r], outline=GOLD, width=max(2, size // 160))
    f = font(int(size * 0.27))
    box = d.textbbox((0, 0), "HS", font=f)
    d.text((c - (box[2] - box[0]) / 2 - box[0], c - (box[3] - box[1]) / 2 - box[1]), "HS", font=f, fill=SLATE)
    return im


def main() -> None:
    given = ROOT / "assets" / "branding" / "AppIcon.iconset"            # the designed icon, all sizes
    if given.is_dir():
        out = ROOT / "build" / "HyperShutter.icns"
        out.parent.mkdir(exist_ok=True)
        subprocess.run(["iconutil", "-c", "icns", str(given), "-o", str(out)], check=True)
        print(out)
        return
    png = ROOT / "assets" / "branding" / "placeholder-icon.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    src = ROOT / "assets" / "branding" / "hypershutter-icon-1024.png"
    big = Image.open(src).convert("RGBA") if src.exists() else draw()
    if not src.exists():
        big.save(png)
    iconset = ROOT / "build" / "HyperShutter.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for s in (16, 32, 128, 256, 512):
        big.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
        big.resize((2 * s, 2 * s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ROOT / "build" / "HyperShutter.icns")], check=True)
    print(ROOT / "build" / "HyperShutter.icns")


if __name__ == "__main__":
    sys.exit(main())
