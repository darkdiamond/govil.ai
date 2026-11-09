"""The article's hero image, in the sizes Google wants.

An AI editorial illustration (`llm.image`, house style below — non-photoreal,
no text, no people, no logos, no flags), captioned "איור" on the page. If the
image model fails, a chart card drawn from the story's main series stands in
(brand gradient + the line, no text). Either way the result is cropped to
16:9 (1600×900, Discover's ≥1200px), 4:3 (1200×900) and 1:1 (1200×1200) for
NewsArticle JSON-LD, as JPEG (og:image) and WebP (the page). Filenames carry
a content hash: hosting caches images for a year as immutable.
"""
from __future__ import annotations

import hashlib
import io
import logging

from PIL import Image, ImageDraw, ImageFilter

log = logging.getLogger(__name__)

HOUSE_STYLE = (
    "Editorial illustration for a serious Israeli news site's data story. Flat, modern vector "
    "style with soft grain, generous negative space, calm composition. Palette: deep navy "
    "#0b3668, brand blue #0068f5, light blue #f1f7ff, white, one warm accent. Wide 16:9 framing "
    "with the subject centred (it will be cropped to 4:3 and square). Strictly NO text, letters, "
    "numbers, charts with labels, logos, flags, or recognisable real people or places' signage. "
    "Not photorealistic. Subject: "
)
SIZES = {"16x9": (1600, 900), "4x3": (1200, 900), "1x1": (1200, 1200)}


def _crop(img: Image.Image, w: int, h: int) -> Image.Image:
    src_w, src_h = img.size
    target = w / h
    if src_w / src_h > target:
        nw = int(src_h * target)
        x = (src_w - nw) // 2
        img = img.crop((x, 0, x + nw, src_h))
    else:
        nh = int(src_w / target)
        y = (src_h - nh) // 2
        img = img.crop((0, y, src_w, y + nh))
    return img.resize((w, h), Image.LANCZOS)


def chart_card(values: list[float], size=(1600, 900)) -> Image.Image:
    """Fallback hero: brand gradient with the story's series as a bold line."""
    w, h = size
    # Header gradient #025fdb → #0b3668, top to bottom.
    mask = Image.linear_gradient("L").resize(size)
    img = Image.composite(Image.new("RGB", size, "#0b3668"), Image.new("RGB", size, "#025fdb"), mask)
    vals = [v for v in values if v is not None]
    if len(vals) >= 2:
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        mx, my = w * 0.08, h * 0.18
        pts = [(mx + i * (w - 2 * mx) / (len(vals) - 1), h - my - (v - lo) / span * (h - 2 * my))
               for i, v in enumerate(vals)]
        glow = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).line(pts, fill=(255, 255, 255, 90), width=28, joint="curve")
        img = Image.alpha_composite(img.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(14)))
        d = ImageDraw.Draw(img)
        d.line(pts, fill=(255, 255, 255, 255), width=10, joint="curve")
        x, y = pts[-1]
        d.ellipse((x - 18, y - 18, x + 18, y + 18), fill=(255, 193, 7, 255))
        img = img.convert("RGB")
    return img


def variants(img: Image.Image, stem: str) -> tuple[dict[str, str], dict[str, bytes]]:
    """({size: filename}, {filename: bytes}) — JPEG per size plus a 16:9 WebP."""
    names, files = {}, {}
    img = img.convert("RGB")
    for key, (w, h) in SIZES.items():
        buf = io.BytesIO()
        _crop(img, w, h).save(buf, "JPEG", quality=84, optimize=True, progressive=True)
        data = buf.getvalue()
        name = f"{stem}-{key}-{hashlib.sha256(data).hexdigest()[:10]}.jpg"
        names[key], files[name] = name, data
    buf = io.BytesIO()
    _crop(img, *SIZES["16x9"]).save(buf, "WEBP", quality=80, method=6)
    data = buf.getvalue()
    name = f"{stem}-16x9-{hashlib.sha256(data).hexdigest()[:10]}.webp"
    names["webp"], files[name] = name, data
    return names, files


def hero(llm, brief: str, fallback_values: list[float]) -> tuple[dict, dict[str, bytes]]:
    """(hero meta, files). meta: {kind: illustration|chart, sizes{...}}."""
    kind = "illustration"
    img = None
    if llm is not None and brief:
        try:
            raw = llm.image(HOUSE_STYLE + brief)
            img = Image.open(io.BytesIO(raw))
            img.load()
            if img.size[0] < 1024:
                raise ValueError(f"image too small: {img.size}")
        except Exception:
            log.warning("news: illustration failed — chart card instead", exc_info=True)
            img = None
    if img is None:
        kind = "chart"
        img = chart_card(fallback_values)
    names, files = variants(img, "hero")
    return {"kind": kind, "sizes": names}, files
