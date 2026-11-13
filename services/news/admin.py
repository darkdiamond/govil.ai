"""Manage published articles (Firestore `articles/`). Changes reach the site
on the next publish (`gh workflow run publish.yml`, or the next job that
re-renders something).

    python -m services.news.admin list [--rejected] [--days 30]
    python -m services.news.admin unpublish <slug>            # page removed on next publish
    python -m services.news.admin republish <slug>
    python -m services.news.admin correct <slug> --note "…"   # shown on the page, bumps dateModified
    python -m services.news.admin publish on|off|status       # the kill switch

`publish off` writes `news_state/control {publish: "off"}`: from the next run
on, the job publishes nothing, whatever its NEWS_PUBLISH env says (a deploy
can't reset it). `publish on` writes "live", which hands the decision back to
the env: the job still needs NEWS_PUBLISH=live. `status` prints the flag
(not set = the env decides).
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    from .store import (
        ARTICLES,
        CONTROL,
        LIVE_STATUSES,
        REJECTS,
        STATE,
        FirestoreArticles,
    )

    ap = argparse.ArgumentParser(prog="python -m services.news.admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--rejected", action="store_true")
    ls.add_argument("--days", type=int, default=30)
    for name in ("unpublish", "republish"):
        sub.add_parser(name).add_argument("slug")
    c = sub.add_parser("correct")
    c.add_argument("slug")
    c.add_argument("--note", required=True)
    sub.add_parser("publish").add_argument("mode", choices=("on", "off", "status"))
    a = ap.parse_args(argv)

    st = FirestoreArticles()
    if a.cmd == "publish":
        if a.mode != "status":
            st.set_publish_flag("live" if a.mode == "on" else "off")
        flag = st.read_publish_flag()
        print(f"{STATE}/{CONTROL} publish={flag or '(not set: the env NEWS_PUBLISH decides)'}")
        if flag == "live":
            print("the job publishes only while its NEWS_PUBLISH env is also 'live'", file=sys.stderr)
        return 0
    if a.cmd == "list":
        if a.rejected:
            for d in st.db.collection(REJECTS).order_by("at", direction="DESCENDING").limit(50).stream():
                x = d.to_dict() or {}
                print(json.dumps({"at": x.get("at"), "reason": x.get("reason"),
                                  "headline": (x.get("core") or {}).get("headline"),
                                  "problems": (x.get("problems") or [])[:5]}, ensure_ascii=False))
        else:
            for x in st.recent(a.days):
                print(f"{str(x.get('published_at'))[:10]}  {x.get('status'):10}  {x.get('slug')}  {x.get('headline')}")
        return 0
    if a.cmd == "unpublish":
        st.set_status(a.slug, "unpublished")
    elif a.cmd == "republish":
        st.set_status(a.slug, "published")
    elif a.cmd == "correct":
        # A correction never decides whether the article is on the site.
        snap = st.db.collection(ARTICLES).document(a.slug).get()
        status = (snap.to_dict() or {}).get("status") if snap.exists else None
        if status not in LIVE_STATUSES:
            print(f"correct: {a.slug} is {status or 'not found'}, not live; nothing changed "
                  "(republish it first to correct it on the site)", file=sys.stderr)
            return 1
        st.set_status(a.slug, "corrected", correction=a.note)
    print(f"{a.cmd}: {a.slug} — run the publish workflow to update the site", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
