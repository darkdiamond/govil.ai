"""`admin` changes only what it is asked to: a correction never decides
whether an article is on the site."""
from __future__ import annotations

import pytest

from services.news import admin
from services.news import store as store_mod
from services.news.publish_news import LIVE


class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _Doc:
    def __init__(self, docs, slug):
        self.docs, self.slug = docs, slug

    def get(self):
        return _Snap(self.docs.get(self.slug))

    def update(self, upd):
        if self.slug not in self.docs:
            raise LookupError("no document")
        self.docs[self.slug].update(upd)


class _Db:
    def __init__(self, docs):
        self.docs = docs

    def collection(self, name):
        assert name == store_mod.ARTICLES
        return type("C", (), {"document": lambda _c, slug: _Doc(self.docs, slug)})()


@pytest.fixture
def docs(monkeypatch):
    docs: dict = {}
    real = store_mod.FirestoreArticles
    monkeypatch.setattr(store_mod, "FirestoreArticles", lambda: real(client=_Db(docs)))
    return docs


@pytest.mark.parametrize("status", ["published", "corrected"])
def test_correct_on_a_live_article_marks_it_corrected(docs, status):
    docs["live-article"] = {"slug": "live-article", "status": status}
    assert admin.main(["correct", "live-article", "--note", "תיקון"]) == 0
    assert docs["live-article"]["status"] == "corrected"
    assert docs["live-article"]["correction"] == "תיקון"


def test_correct_on_an_unpublished_article_keeps_it_off_the_site(docs, capsys):
    docs["pulled-article"] = {"slug": "pulled-article", "status": "unpublished"}
    assert admin.main(["correct", "pulled-article", "--note", "תיקון"]) == 1
    assert docs["pulled-article"]["status"] not in LIVE
    assert "correction" not in docs["pulled-article"]
    assert "unpublished" in capsys.readouterr().err


def test_correct_on_a_missing_article_is_refused(docs):
    assert admin.main(["correct", "no-such-article", "--note", "x"]) == 1
    assert docs == {}
