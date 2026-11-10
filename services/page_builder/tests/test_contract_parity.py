"""Contracts copied by hand between Python and the frontend must agree.

The frontend sources are read as text with small regexes, so this runs in
the python CI job with no Node. When one of these fails, change every copy
the message names, not just the one the test reads first.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import typing
from pathlib import Path

from services.page_builder import publish, schema
from services.page_builder import refresh as rf

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "frontend"

_CHECK_PATH = ROOT / "agent" / "skills" / "check.py"
_spec = importlib.util.spec_from_file_location("agent_check_parity", _CHECK_PATH)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _block(text: str, start_re: str, close: str) -> str:
    """The text from `start_re`'s match up to the first `close` after it."""
    m = re.search(start_re, text)
    assert m, f"pattern not found: {start_re}"
    end = text.index(close, m.end())
    return text[m.end():end]


def _quoted(text: str) -> list[str]:
    return re.findall(r"""["']([^"']+)["']""", text)


# --- search-index fields --------------------------------------------------

def test_search_index_fields_match_everywhere():
    py = set(publish._SEARCH_INDEX_FIELDS)

    nuxt = _block(_read("frontend/nuxt.config.ts"), r"const SLIM_FIELDS\s*=\s*\[", "]")
    slim_fields = _quoted(nuxt)

    fn = _block(
        _read("frontend/utils/search-index.ts"),
        r"function slimEntry\([^)]*\)\s*:\s*SlimEntry\s*\{\s*return\s*\{",
        "};",
    )
    slim_entry = re.findall(r"^\s*(\w+)\s*:", fn, re.MULTILINE)

    iface = _block(_read("frontend/types/manifest.ts"), r"export interface SlimEntry\s*\{", "}")
    slim_type = re.findall(r"^\s*(\w+)\??\s*:", iface, re.MULTILINE)

    for name, got in (
        ("frontend/nuxt.config.ts SLIM_FIELDS", slim_fields),
        ("frontend/utils/search-index.ts slimEntry", slim_entry),
        ("frontend/types/manifest.ts SlimEntry", slim_type),
    ):
        assert len(got) == len(set(got)), f"{name} lists a field twice: {got}"
        assert set(got) == py, (
            f"{name} differs from publish._SEARCH_INDEX_FIELDS: "
            f"missing {sorted(py - set(got))}, extra {sorted(set(got) - py)}"
        )


# --- dataset kinds ---------------------------------------------------------

def test_dataset_kinds_match_everywhere():
    py = set(typing.get_args(schema.DatasetKind))
    assert py, "schema.DatasetKind lost its Literal values"
    assert check.VALID_DATASET_KINDS == py, (
        f"agent/skills/check.py VALID_DATASET_KINDS {sorted(check.VALID_DATASET_KINDS)} "
        f"!= schema.DatasetKind {sorted(py)}"
    )
    ts = set(_quoted(_block(_read("frontend/types/manifest.ts"),
                            r"export type DatasetKind\s*=", ";")))
    assert ts == py, f"frontend/types/manifest.ts DatasetKind {sorted(ts)} != {sorted(py)}"


# --- SEO limits ------------------------------------------------------------

def test_seo_limits_match_schema():
    assert check.SEO_LIMITS == {
        "title": (1, schema.SEO_TITLE_MAX),
        "description": (schema.SEO_DESCRIPTION_MIN, schema.SEO_DESCRIPTION_MAX),
        "name": (1, schema.SEO_NAME_MAX),
    }
    assert set(check.SEO_LIMITS) | {"alternate_names"} == set(schema.SeoMeta.model_fields)


def test_seo_alternate_names_literals_match_schema():
    # check.py writes these two numbers inline in check_seo (it is standalone).
    src = _CHECK_PATH.read_text(encoding="utf-8")
    body = src[src.index("def check_seo("):src.index("\ndef ", src.index("def check_seo(") + 1)]
    count = re.search(r"len\(names\)\s*>\s*(\d+)", body)
    length = re.search(r"one_line\(n,\s*1,\s*(\d+)\)", body)
    assert count and length, "check_seo's alternate_names checks moved; update this test"
    assert int(count.group(1)) == schema.SEO_ALTERNATE_NAMES_MAX
    assert int(length.group(1)) == schema.SEO_NAME_MAX


# --- map encoding (govlib.geo ↔ frontend/scripts/gov-map.js) ---------------

def test_govlib_geo_encodes_the_frozen_ring():
    vec = json.loads((FRONTEND / "tests" / "fixtures" / "gov-map-vectors.json")
                     .read_text(encoding="utf-8"))
    sys.path.insert(0, str(rf.RECIPE_LIB_DIR))
    try:
        from govlib import geo
    finally:
        sys.path.remove(str(rf.RECIPE_LIB_DIR))

    ring = [tuple(p) for p in vec["ring"]]
    assert vec["scale"] == geo.SCALE
    origin = geo.origin([p[0] for p in ring], [p[1] for p in ring])
    assert origin == vec["origin"]
    assert geo.encode([ring], origin) == [vec["flat"]]
