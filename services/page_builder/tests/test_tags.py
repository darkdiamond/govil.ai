"""Tests for services.page_builder.tags — normalization, vocabulary, index, redirects."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import pytest

from services.page_builder.tags import (
    ASSIGNMENTS_PATH,
    MAX_ASSIGNED,
    MIN_ASSIGNED,
    VOCAB_PATH,
    Taxonomy,
    TaxonomyError,
    build_tag_index,
    legacy_tag_slug_map,
    normalize,
    org_drop_names,
    tag_redirects,
)

VOCAB = {
    "topics": [
        {"id": "water", "label_he": "מים", "intro_he": "מבוא"},
        {"id": "transport", "label_he": "תחבורה"},
    ],
    "tags": {
        "מי תהום": {"topic": "water", "aliases": ["אקוויפר", "מי-תהום"]},
        "מים": {"topic": "water", "intro_he": "הכל על מים"},
        "אוטובוסים": {"topic": "transport", "aliases": ["אוטובוס"]},
        'אג"ח': {},
    },
    "drop": ["GIS", "water"],
}


@dataclass
class E:
    id: str
    tags: list[str]
    organization_slug: Optional[str] = None


@pytest.mark.parametrize("raw,expected", [
    ("  מי   תהום ", "מי תהום"),
    ("מי-תהום", "מי תהום"),
    ("מי_תהום", "מי תהום"),
    ("GIS", "gis"),
    ("אג״ח", 'אג"ח'),
    ("צמ”ה", 'צמ"ה'),
    ("ש׳", "ש'"),
    ("", ""),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_normalize_nfc():
    decomposed = "é"
    assert normalize(decomposed) == "é"


def test_resolve_aliases_drop_and_passthrough():
    tax = Taxonomy.from_dicts(VOCAB)
    assert tax.resolve("אקוויפר") == "מי תהום"
    assert tax.resolve("מי-תהום") == "מי תהום"
    assert tax.resolve("אוטובוס") == "אוטובוסים"
    assert tax.resolve("gis") is None
    assert tax.resolve("Water") is None
    assert tax.resolve("משהו חדש") == "משהו חדש"
    assert tax.resolve("  ") is None


def test_canonicalize_dedups_in_order_and_drops_org_names():
    tax = Taxonomy.from_dicts(VOCAB)
    drop = org_drop_names(["רשות המים", None])
    got = tax.canonicalize(["אקוויפר", "מים", "מי תהום", "רשות המים", "GIS"], drop)
    assert got == ["מי תהום", "מים"]


def test_dataset_tags_prefers_curated_assignment():
    tax = Taxonomy.from_dicts(VOCAB, {"x": ["מים", "מי תהום", "אוטובוסים"]})
    assert tax.dataset_tags("x", suggested=["אוטובוס"]) == ["מים", "מי תהום", "אוטובוסים"]
    assert tax.dataset_tags("y", suggested=["אוטובוס"], ckan=["אקוויפר"]) == ["אוטובוסים", "מי תהום"]


@pytest.mark.parametrize("vocab,match", [
    ({"tags": {"א": {"aliases": ["ב"]}, "ג": {"aliases": ["ב"]}}}, "claimed by both"),
    ({"tags": {"א": {"slug": "x"}, "ב": {"slug": "x"}}}, "share slug"),
    ({"tags": {"א": {"topic": "nope"}}}, "unknown topic"),
    ({"tags": {"GIS": {}}}, "normal form"),
    ({"tags": {"א": {"aliases": ["ב"]}}, "drop": ["ב"]}, "dropped"),
])
def test_load_rejects_inconsistent_vocab(vocab, match):
    with pytest.raises(TaxonomyError, match=match):
        Taxonomy.from_dicts(vocab)


def test_load_rejects_unknown_or_duplicate_assignment():
    with pytest.raises(TaxonomyError, match="not in the vocabulary"):
        Taxonomy.from_dicts(VOCAB, {"x": ["מים", "לא קיים"]})
    with pytest.raises(TaxonomyError, match="duplicate"):
        Taxonomy.from_dicts(VOCAB, {"x": ["מים", "מים"]})


def test_slugs_are_stable_and_quote_free():
    tax = Taxonomy.from_dicts(VOCAB)
    assert tax.slug("מי תהום") == "מי-תהום"
    assert tax.slug('אג"ח') == "אגח"
    assert tax.slug("free tag") == "free-tag"


def test_build_tag_index_threshold_cooccurrence_and_ministries():
    tax = Taxonomy.from_dicts(VOCAB)
    entries = [
        E("1", ["מים", "מי תהום"], "water-auth"),
        E("2", ["מים", "מי תהום"], "water-auth"),
        E("3", ["מים", "אוטובוסים"], "transport"),
        E("4", ["אוטובוסים"], "transport"),
    ]
    index = build_tag_index(entries, tax, min_datasets=2)
    assert list(index) == ["מים", "אוטובוסים", "מי תהום"]
    assert index["מים"]["count"] == 3
    assert index["מים"]["ministries"] == {"water-auth": 2, "transport": 1}
    assert index["מים"]["related"] == ["מי תהום", "אוטובוסים"]
    assert index["מים"]["intro_he"] == "הכל על מים"
    assert index["מי תהום"]["topic"] == "water"
    assert "intro_he" in index["אוטובוסים"] and index["אוטובוסים"]["intro_he"] is None
    assert build_tag_index(entries, tax, min_datasets=4) == {}


def _old_build_tag_slugs(tags):
    """Verbatim copy of the pre-taxonomy publish._build_tag_slugs body."""
    import hashlib
    import re
    unsafe = re.compile(r"[\s/?#&]+")
    seen, out = {}, {}
    for tag in sorted(set(tags)):
        slug = unsafe.sub("-", tag).strip("-")
        if not slug:
            slug = hashlib.sha1(tag.encode("utf-8")).hexdigest()[:8]
        if slug in seen and seen[slug] != tag:
            slug = f"{slug}-{hashlib.sha1(tag.encode('utf-8')).hexdigest()[:6]}"
        seen[slug] = tag
        out[tag] = slug
    return out


def test_legacy_slug_map_matches_old_scheme_including_hash_suffixes():
    raw = ["מי תהום", "מי-תהום", "a/b", "?", "GIS", "gis"]
    got = legacy_tag_slug_map(raw)
    assert got == _old_build_tag_slugs(raw)
    assert got["מי תהום"] == "מי-תהום"
    assert got["מי-תהום"].startswith("מי-תהום-")


def test_tag_redirects_targets():
    tax = Taxonomy.from_dicts(VOCAB)
    index = build_tag_index([E("1", ["מי תהום"]), E("2", ["מי תהום"])], tax, min_datasets=2)
    raw = ["מי תהום", "מי-תהום", "אקוויפר", "GIS", "נדיר"]
    red = tag_redirects(raw, tax, index)
    legacy = legacy_tag_slug_map(raw)
    assert legacy["מי תהום"] not in red            # still a live page
    assert red[legacy["מי-תהום"]] == "/tags/מי-תהום/"
    assert red["אקוויפר"] == "/tags/מי-תהום/"
    assert "GIS" not in red                        # dropped: left to 404
    # A CKAN tag carrying Firebase glob syntax must never become a source.
    globby = ["מי*", "מי:x", "{מי}", "מי@(a|b)", "מי+(x)", "מי!(y)"]
    tax2 = Taxonomy.from_dicts({"tags": {"מי תהום": {"aliases": globby}}})
    assert tag_redirects(globby, tax2, index) == {}
    assert "נדיר" not in red                       # no page: left to 404


def test_committed_taxonomy_is_consistent():
    """The real vocabulary + assignment load cleanly (no conflicting aliases,
    unknown topics, duplicate slugs or off-vocabulary assignments) and every
    curated dataset carries MIN..MAX tags. A bad vocabulary PR fails here."""
    tax = Taxonomy.load()
    assert tax.topics and tax.tags
    assert all(t.topic for t in tax.tags.values()), "every canonical tag needs a topic"
    for sid, tags in tax.assignments.items():
        assert MIN_ASSIGNED <= len(tags) <= MAX_ASSIGNED, sid


def test_committed_assignment_file_is_sorted():
    data = json.loads(ASSIGNMENTS_PATH.read_text(encoding="utf-8"))
    assert list(data) == sorted(data), "keep taxonomy/dataset-tags.json sorted by id"
    assert json.loads(VOCAB_PATH.read_text(encoding="utf-8"))["tags"]


def test_assign_cli_validates_and_writes_sorted(tmp_path, monkeypatch, capsys):
    from services.page_builder import tags as tags_mod

    target = tmp_path / "dataset-tags.json"
    target.write_text(json.dumps({"zzz": ["מים", "קידוחים", "מי תהום"]}, ensure_ascii=False))
    monkeypatch.setattr(tags_mod, "ASSIGNMENTS_PATH", target)

    assert tags_mod.main(["assign", "aaa", "תחבורה", "רכבת"]) == 1   # too few
    assert tags_mod.main(["assign", "aaa", "תחבורה", "רכבת", "רקל"]) == 1  # alias
    assert "use 'רכבת קלה'" in capsys.readouterr().err
    assert json.loads(target.read_text()) == {"zzz": ["מים", "קידוחים", "מי תהום"]}

    assert tags_mod.main(["assign", "aaa", "תחבורה", "רכבת", "רכבת קלה"]) == 0
    written = json.loads(target.read_text())
    assert list(written) == ["aaa", "zzz"]
    assert written["aaa"] == ["תחבורה", "רכבת", "רכבת קלה"]

    monkeypatch.setattr(tags_mod, "PENDING_ROOT", tmp_path / "authoring")
    (tmp_path / "authoring" / "bbb").mkdir(parents=True)
    (tmp_path / "authoring" / "bbb" / "tags.json").write_text(
        json.dumps(["כלכלה", "בנקים", "ריבית"], ensure_ascii=False))
    assert tags_mod.main(["assign", "--from-pending", "bbb"]) == 0
    assert json.loads(target.read_text())["bbb"] == ["כלכלה", "בנקים", "ריבית"]

    # A non-list pending file is rejected outright, not iterated.
    (tmp_path / "authoring" / "ccc").mkdir()
    (tmp_path / "authoring" / "ccc" / "tags.json").write_text(
        json.dumps({"כלכלה": 1, "בנקים": 1, "ריבית": 1}, ensure_ascii=False))
    assert tags_mod.main(["assign", "--from-pending", "ccc"]) == 1
    assert "JSON list" in capsys.readouterr().err
    assert "ccc" not in json.loads(target.read_text())
