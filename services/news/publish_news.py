"""News artifacts for the static site (called from page_builder.publish).

    frontend/public/news/index.json           every live article, newest first (slim)
    frontend/public/news/<slug>/article.json  one article, ready to render

Images are already there: publish.yml rsyncs `gs://<staging>/news/` into
`public/news/` before the publisher runs. A directory whose slug is not a
live article (unpublished, or never accepted) is removed, so its images
don't ship. Dataset links are re-resolved against the current page slugs,
so a renamed dataset never leaves an article pointing at an old URL.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)
LIVE = ("published", "corrected")


def _dataset_href(ds: str, page_slugs: dict[str, str]) -> str | None:
    slug = page_slugs.get(ds)
    return f"/datasets/{slug}/" if slug else None


def _relink(blocks: list[dict], page_slugs: dict[str, str]) -> list[dict]:
    out = []
    for b in blocks or []:
        if b.get("type") == "p":
            runs = []
            for r in b.get("runs") or []:
                if r.get("t") == "link" and r.get("kind") == "dataset" and r.get("id"):
                    href = _dataset_href(r["id"], page_slugs)
                    # A dataset that left the site: keep the words, drop the link.
                    r = {**r, "href": href} if href else {"t": "text", "v": r.get("v", "")}
                elif r.get("t") == "link" and str(r.get("href") or "").startswith("http://"):
                    r = {**r, "href": "https://" + r["href"][len("http://"):]}
                runs.append(r)
            b = {**b, "runs": runs}
        out.append(b)
    return out


def write_news(out_root: Path, articles, *, datasets: dict[str, dict]) -> dict:
    """`articles`: live article docs (store.join shape). `datasets`: id →
    {page_slug, title, organization} for every published dataset."""
    page_slugs = {i: d["page_slug"] for i, d in datasets.items() if d.get("page_slug")}
    news_root = out_root / "news"
    news_root.mkdir(parents=True, exist_ok=True)
    live = [a for a in articles if a.get("status") in LIVE and a.get("slug")]
    live.sort(key=lambda a: str(a.get("published_at") or ""), reverse=True)

    index = []
    for a in live:
        slug = a["slug"]
        d = news_root / slug
        d.mkdir(exist_ok=True)
        hero = dict(a.get("hero") or {})
        sizes = {k: f"/news/{slug}/{v}" for k, v in (hero.get("sizes") or {}).items()}
        cards = [{"id": i, "href": _dataset_href(i, page_slugs), **{k: datasets[i].get(k)
                  for k in ("title", "organization")}} for i in a.get("dataset_ids") or [] if i in datasets]
        doc = {
            "slug": slug, "status": a["status"], "headline": a.get("headline"), "dek": a.get("dek"),
            "published_at": a.get("published_at"), "updated_at": a.get("updated_at"),
            "byline": a.get("byline"), "tags": a.get("tags") or [], "correction": a.get("correction"),
            "hero": {"sizes": sizes, "alt": hero.get("alt"), "caption": hero.get("caption"),
                     "kind": hero.get("kind")},
            "blocks": _relink(a.get("blocks") or [], page_slugs), "charts": a.get("charts") or [],
            "sources": [{k: s.get(k) for k in ("url", "title")} for s in a.get("sources") or []],
            "datasets": cards,
        }
        (d / "article.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        index.append({k: doc[k] for k in ("slug", "headline", "dek", "published_at", "updated_at",
                                           "tags", "status")}
                     | {"hero": sizes.get("16x9"), "hero_alt": hero.get("alt"),
                        "dataset_ids": [c["id"] for c in cards]})

    keep = {a["slug"] for a in live}
    removed = 0
    for d in news_root.iterdir():
        if d.is_dir() and d.name not in keep:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    (news_root / "index.json").write_text(json.dumps(
        {"generated_at": datetime.now(UTC).isoformat(), "articles": index}, ensure_ascii=False),
        encoding="utf-8")
    return {"articles": len(index), "removed_dirs": removed}


def publish_news(out_root: Path, *, datasets: dict[str, dict], project: str | None = None,
                 client=None) -> dict:
    """Fail soft: the dataset site must deploy even if news can't be read.
    Articles are read from the `news` Firestore database (store.NEWS_DATABASE);
    `client` overrides that client (tests)."""
    try:
        from .store import FirestoreArticles

        articles = list(FirestoreArticles(client=client, project=project).iter_published())
        return write_news(out_root, articles, datasets=datasets)
    except Exception as e:
        log.exception("publish: news artifacts skipped")
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}
