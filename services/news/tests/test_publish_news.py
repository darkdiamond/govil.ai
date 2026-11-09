"""The static-site news artifacts (publish_news) and the publisher hook."""
from __future__ import annotations

import json

from services.news.publish_news import publish_news, write_news


def _article(slug="mortgages-low", status="published", at="2026-11-09T08:00:00+00:00"):
    return {
        "slug": slug, "status": status, "headline": "כותרת", "dek": "תקציר", "byline": "מערכת govil.ai",
        "published_at": at, "updated_at": at, "tags": ["משכנתאות"],
        "hero": {"kind": "illustration", "sizes": {"16x9": "hero-16x9-a.jpg", "1x1": "hero-1x1-b.jpg"},
                 "alt": "איור", "caption": "איור"},
        "blocks": [{"type": "p", "runs": [
            {"t": "text", "v": "לפי "},
            {"t": "link", "v": "הנתונים", "href": "/datasets/old-slug/", "kind": "dataset", "id": "ds1"},
            {"t": "text", "v": " ו"},
            {"t": "link", "v": "מאגר שנמחק", "href": "/datasets/gone/", "kind": "dataset", "id": "ds-gone"},
            {"t": "link", "v": "הודעה", "href": "http://www.gov.il/he/pages/x", "kind": "source"},
        ]}],
        "charts": [], "sources": [{"url": "https://www.gov.il/he/pages/x", "title": "הודעה", "quote": "q"}],
        "dataset_ids": ["ds1", "ds-gone"], "ledger": {"facts": [1, 2, 3]},
    }


DATASETS = {"ds1": {"page_slug": "new-slug", "title": "משכנתאות", "organization": "בנק ישראל"}}


def test_writes_index_and_article_with_current_links(tmp_path):
    out = write_news(tmp_path, [_article()], datasets=DATASETS)
    assert out == {"articles": 1, "removed_dirs": 0}
    idx = json.loads((tmp_path / "news" / "index.json").read_text(encoding="utf-8"))["articles"]
    assert idx[0]["slug"] == "mortgages-low" and idx[0]["hero"] == "/news/mortgages-low/hero-16x9-a.jpg"
    assert idx[0]["dataset_ids"] == ["ds1"]
    art = json.loads((tmp_path / "news" / "mortgages-low" / "article.json").read_text(encoding="utf-8"))
    runs = art["blocks"][0]["runs"]
    assert runs[1]["href"] == "/datasets/new-slug/"           # re-resolved after a rename
    assert runs[3] == {"t": "text", "v": "מאגר שנמחק"}          # dataset gone: words stay, link goes
    assert runs[4]["href"].startswith("https://")
    assert "ledger" not in art and "quote" not in art["sources"][0]
    assert art["datasets"] == [{"id": "ds1", "href": "/datasets/new-slug/", "title": "משכנתאות",
                                "organization": "בנק ישראל"}]


def test_index_carries_card_data(tmp_path):
    a = _article() | {
        "words": 600, "tags": ["משכנתאות", "ללא-דף"],
        "blocks": [{"type": "p", "runs": [{"t": "text", "v": "x"}]},
                   {"type": "stat", "value": "62.7%", "label": "חשיפה למניות"}],
        "charts": [{"type": "bar", "option": {"series": [{"data": [1, 2]}]}},
                   {"type": "line", "option": {"series": [{"data": [1.0, None, 2.0, 3.0] + [4.0] * 40}]}}],
    }
    write_news(tmp_path, [a], datasets=DATASETS, tag_slugs={"משכנתאות": "משכנתאות"},
               tag_topics={"משכנתאות": "housing"}, topics={"housing": "דיור"})
    idx = json.loads((tmp_path / "news" / "index.json").read_text(encoding="utf-8"))["articles"][0]
    assert idx["stat"] == {"value": "62.7%", "label": "חשיפה למניות"}
    assert len(idx["spark"]) == 36 and None not in idx["spark"]
    assert idx["topic"] == {"id": "housing", "label": "דיור"} and idx["minutes"] == 3
    assert idx["tag_slugs"] == {"משכנתאות": "משכנתאות"}
    assert idx["datasets"] == [{"id": "ds1", "title": "משכנתאות", "href": "/datasets/new-slug/"}]
    art = json.loads((tmp_path / "news" / "mortgages-low" / "article.json").read_text(encoding="utf-8"))
    assert art["tag_slugs"] == {"משכנתאות": "משכנתאות"}


def test_card_data_is_optional(tmp_path):
    write_news(tmp_path, [_article()], datasets=DATASETS)
    idx = json.loads((tmp_path / "news" / "index.json").read_text(encoding="utf-8"))["articles"][0]
    assert idx["stat"] is None and idx["spark"] is None and idx["topic"] is None and idx["minutes"] is None


def test_unpublished_dirs_are_removed_and_order_is_newest_first(tmp_path):
    stale = tmp_path / "news" / "pulled-article"
    stale.mkdir(parents=True)
    (stale / "hero-16x9-x.jpg").write_bytes(b"x")
    arts = [_article("older", at="2026-11-01T08:00:00+00:00"), _article("newer"),
            _article("pulled-article", status="unpublished")]
    out = write_news(tmp_path, arts, datasets=DATASETS)
    assert out["removed_dirs"] == 1 and not stale.exists()
    idx = json.loads((tmp_path / "news" / "index.json").read_text(encoding="utf-8"))["articles"]
    assert [a["slug"] for a in idx] == ["newer", "older"]


def test_publish_news_fails_soft(tmp_path):
    class Boom:
        def collection(self, name):
            raise RuntimeError("firestore down")

    out = publish_news(tmp_path, client=Boom(), datasets=DATASETS)
    assert "error" in out
