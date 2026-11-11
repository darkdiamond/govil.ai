"""hero(): which image-model answers are decoded and which fall back to the chart card."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from services.news import images


class _LLM:
    def __init__(self, raw: bytes):
        self.raw = raw

    def image(self, prompt: str) -> bytes:
        return self.raw


def _encode(fmt: str, size=(1200, 700)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (20, 90, 200)).save(buf, fmt)
    return buf.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_hero_decodes_allowed_formats(fmt):
    meta, files = images.hero(_LLM(_encode(fmt)), "brief", [1.0, 2.0])
    assert meta["kind"] == "illustration"
    assert set(meta["sizes"]) == {"16x9", "4x3", "1x1", "webp"} and len(files) == 4


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF"])
def test_hero_refuses_other_formats(fmt):
    meta, files = images.hero(_LLM(_encode(fmt)), "brief", [1.0, 2.0])
    assert meta["kind"] == "chart" and len(files) == 4


def test_hero_undecodable_bytes_fall_back():
    meta, _ = images.hero(_LLM(b"\x89PNG\r\n\x1a\nnot really a png"), "brief", [1.0, 2.0])
    assert meta["kind"] == "chart"


def test_hero_refuses_oversized_image_before_decoding(monkeypatch):
    monkeypatch.setattr(images, "MAX_HERO_PIXELS", 1200 * 700 - 1)
    meta, _ = images.hero(_LLM(_encode("PNG")), "brief", [1.0, 2.0])
    assert meta["kind"] == "chart"


def test_hero_lets_a_refused_key_through():
    from services.news.llm import LLMUnavailable

    class _Refused:
        def image(self, prompt):
            raise LLMUnavailable("key refused")

    with pytest.raises(LLMUnavailable):
        images.hero(_Refused(), "brief", [1.0, 2.0])
