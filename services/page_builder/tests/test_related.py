"""Tests for services.page_builder.related — content-based related datasets."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from services.page_builder import related
from services.page_builder.related import RelatedIndex, compute_related


@dataclass
class E:
    id: str
    title: str
    summary_he: Optional[str] = None
    organization_slug: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    source_status: str = "available"


def _filler(n: int) -> list[E]:
    # Unrelated background docs so document frequencies look like a corpus.
    topics = ["תקציב משרד האוצר", "בתי ספר יסודיים", "רישיונות נשק", "מחירי דירות",
              "חיסוני ילדים", "תיירות נכנסת", "פסולת ביתית", "שכר מינימום"]
    return [E(f"f{i}", topics[i % len(topics)] + f" {i}", organization_slug=f"o{i}")
            for i in range(n)]


def test_text_similarity_ranks_shared_subject_first():
    docs = [
        E("a", "איכות מים בקידוחים", "תוצאות דיגום כימי של מי תהום בקידוחים"),
        E("b", "היסטוריית איכות מים בקידוחים", "דיגומים היסטוריים של מי התהום"),
        E("c", "תאונות דרכים", "נפגעים בתאונות לפי יישוב"),
        *_filler(12),
    ]
    top = RelatedIndex(docs).score_all("a")
    assert top[0].id == "b"
    assert "text" in top[0].signals


def test_rare_shared_tag_outweighs_generic_one():
    generic = [E(f"g{i}", f"כותרת {i}", tags=["כללי"]) for i in range(10)]
    docs = [
        E("t", "יעד", tags=["כללי", "נדיר"]),
        E("rare", "אחר", tags=["נדיר"]),
        E("common", "שונה", tags=["כללי"]),
        *generic,
    ]
    scores = {m.id: m.score for m in RelatedIndex(docs).score_all("t")}
    assert scores["rare"] > scores["common"]


def test_excludes_self_and_unavailable_and_applies_floor():
    docs = [
        E("a", "מעיינות ספיקה", tags=["מעיינות"]),
        E("dead", "מעיינות ספיקה חודשית", tags=["מעיינות"], source_status="unavailable"),
        E("weak", "משהו אחר לגמרי"),
        *_filler(10),
    ]
    picks = [m.id for m in RelatedIndex(docs).top("a")]
    assert "a" not in picks and "dead" not in picks and "weak" not in picks
    # An unavailable page still gets related picks of its own.
    assert RelatedIndex(docs).top("dead")[0].id == "a"


def test_ministry_alone_never_qualifies():
    docs = [E("a", "אלפא", organization_slug="m"), E("b", "בטא", organization_slug="m"),
            *_filler(6)]
    assert RelatedIndex(docs).top("a") == []


def test_same_ministry_cap_lets_other_ministries_in(monkeypatch):
    monkeypatch.setattr(related, "REL_FLOOR", 0.0)
    same = [E(f"s{i}", f"רכבת קלה קו {i}", tags=["רכבת קלה"], organization_slug="mot")
            for i in range(6)]
    other = [E(f"o{i}", f"רכבת קלה עירונית {i}", tags=["רכבת קלה"], organization_slug=f"city{i}")
             for i in range(2)]
    docs = [E("t", "רכבת קלה תחנות", tags=["רכבת קלה"], organization_slug="mot"),
            *same, *other, *_filler(10)]
    picks = RelatedIndex(docs).top("t")
    assert len(picks) == 5
    assert sum(1 for m in picks if m.id.startswith("s")) == related.MAX_SAME_MINISTRY
    assert {"o0", "o1"} <= {m.id for m in picks}


def test_cap_falls_back_to_same_ministry_when_nothing_else_qualifies():
    docs = [E("t", "קידוחים מפלסים", tags=["קידוחים"], organization_slug="water")]
    docs += [E(f"s{i}", f"קידוחים מפלסים {i}", tags=["קידוחים"], organization_slug="water")
             for i in range(6)]
    docs += _filler(10)
    picks = RelatedIndex(docs).top("t")
    assert len(picks) == 5 and all(m.id.startswith("s") for m in picks)


def test_deterministic_tie_break_by_id():
    docs = [E("t", "זהה", tags=["x"]), E("b", "זהה", tags=["x"]), E("a", "זהה", tags=["x"]),
            *_filler(8)]
    first = [m.id for m in RelatedIndex(docs).top("t")]
    assert first[:2] == ["a", "b"]
    assert first == [m.id for m in RelatedIndex(list(reversed(docs))).top("t")]


def test_compute_related_covers_every_entry():
    docs = [E("a", "מים"), E("b", "מים וביוב"), *_filler(4)]
    out = compute_related(docs)
    assert set(out) == {d.id for d in docs}
