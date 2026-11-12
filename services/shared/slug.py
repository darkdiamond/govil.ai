"""Deterministic Hebrew-aware slug helpers.

Two flavours, both stable and LLM-free:

  * ``slugify`` — romanizes Hebrew to Latin. Display/SEO only; carried on
    ``DatasetMeta.slug`` and not used for routing.
  * ``hebrew_slugify`` — keeps the Hebrew letters and only strips
    punctuation/whitespace. The publisher combines its output with a slice
    of the CKAN id to form ``page_slug`` — the segment that appears in
    ``/datasets/<slug>/`` URLs (same approach as the Hebrew tag slugs).
"""
from __future__ import annotations

import re
import unicodedata

# Standard Hebrew → Latin romanization. Final-form letters get the same
# value as their non-final equivalents except where the spoken sound
# differs (final kaf softens to "kh", final pe to "f").
HEBREW_TO_LATIN: dict[str, str] = {
    "א": "a",   "ב": "b",   "ג": "g",   "ד": "d",
    "ה": "h",   "ו": "v",   "ז": "z",   "ח": "ch",
    "ט": "t",   "י": "y",   "כ": "k",   "ך": "kh",
    "ל": "l",   "מ": "m",   "ם": "m",   "נ": "n",
    "ן": "n",   "ס": "s",   "ע": "a",   "פ": "p",
    "ף": "f",   "צ": "tz",  "ץ": "tz",  "ק": "k",
    "ר": "r",   "ש": "sh",  "ת": "t",
}

# Hebrew points / cantillation / punctuation we drop entirely.
_NIKTUD_RE = re.compile(r"[֑-ׇ]")
# Hebrew punctuation that should split words.
_HEB_PUNCT_RE = re.compile(r"[־׳״\"]")
# Anything that isn't a-z, 0-9, or hyphen → hyphen.
_NON_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_MULTI_HYPHEN_RE = re.compile(r"-{2,}")


def slugify(text: str, *, fallback: str) -> str:
    """Return a stable, readable slug for `text`.

    Strategy:
      1. Normalize Unicode (NFC).
      2. Drop niktud / cantillation marks.
      3. Map each Hebrew letter to Latin via `HEBREW_TO_LATIN`.
      4. Lowercase any pre-existing Latin letters / digits.
      5. Replace every other character with `-`, collapse runs.
      6. If the result is empty, return `fallback` (typically the dataset id).
    """
    if not text:
        return fallback
    s = unicodedata.normalize("NFC", text)
    s = _NIKTUD_RE.sub("", s)
    s = _HEB_PUNCT_RE.sub(" ", s)

    out: list[str] = []
    for ch in s:
        mapped = HEBREW_TO_LATIN.get(ch)
        if mapped is not None:
            out.append(mapped)
        elif ch.isascii() and (ch.isalnum() or ch == "-"):
            out.append(ch.lower())
        else:
            out.append("-")
    slug = "".join(out)
    slug = _NON_SLUG_RE.sub("-", slug)
    slug = _MULTI_HYPHEN_RE.sub("-", slug).strip("-")
    return slug or fallback


# Keep Hebrew letters + ASCII alphanumerics + hyphen; everything else
# (whitespace, punctuation, URL-reserved chars) becomes a hyphen. The
# Hebrew block is U+0590–U+05FF; niktud/cantillation inside that block is
# dropped first via _NIKTUD_RE so vocalized and bare spellings agree.
_NON_HEB_SLUG_RE = re.compile(r"[^0-9A-Za-zא-ת-]+")


def hebrew_slugify(text: str) -> str:
    """Return a stable, readable slug that keeps the Hebrew characters.

    Unlike :func:`slugify`, Hebrew letters are preserved (not romanized) so
    the slug reads like the title. The output is decoded Unicode (no
    percent-encoding) — Nitro writes those as native Unicode directory names
    during ``nuxt generate`` and the link side encodes for the wire. Returns
    an empty string when nothing slug-worthy survives (the caller appends an
    id slice, so an empty base is fine).
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFC", text)
    s = _NIKTUD_RE.sub("", s)
    s = _NON_HEB_SLUG_RE.sub("-", s)
    s = _MULTI_HYPHEN_RE.sub("-", s).strip("-")
    return s


def default_page_slug(dataset_id: str, title: str | None, own_suffix: str | None = None) -> str:
    """A dataset's `/datasets/<page_slug>/` segment when nothing clashes: the
    Hebrew title slug plus the provider's own suffix, else the first 8 hex
    characters of the id. The publisher (`publish._build_page_slugs`) widens
    the id slice only on a clash across the corpus; a parity test keeps the
    two in step."""
    base = hebrew_slugify(title or "")
    if own_suffix:
        return f"{base}-{own_suffix}" if base else dataset_id
    suffix = dataset_id.replace("-", "")[:8] or dataset_id
    return f"{base}-{suffix}" if base else suffix
