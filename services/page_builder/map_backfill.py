"""One-off: find datasets whose page would gain geometry from a `map: true`
input, and ask for it on GitHub. Local only (Firestore + gh credentials).

Map files used to be undownloadable by script (see recipe.py), so recipes
skipped them. Now that the refresh downloads them, this walks every source:

    list   download + parse each candidate map file (as a `map` input would)
           and print what `open` would do. Writes nothing.
    open   do it: an `[author] … (<id8>)` issue (reason `map_available`) for a
           recipe whose page lacks that geometry, a comment on the open issue
           of a dataset still waiting for its first recipe. Issues go through
           `refresh.queue_authoring`, so Firestore records them exactly like
           the daily job's (no duplicates, no reopening).

Classes (`list` prints each):
    issue       has a recipe, its page draws no map, or draws points where
                the file has lines/polygons
    comment     no recipe, an open authoring issue already asks for one
    mapped      the recipe already reads this resource (map/snapshot input),
                or its map already shows the file's points
    no_recipe   no recipe and no open issue (a legacy page, or not queued):
                reported only; the daily selector decides when to queue it
    failed      the file didn't download or parse (the reason is shown)

`open` refuses to open more than --max-new issues (default 50) at once.
Needs GITHUB_DISPATCH_TOKEN (e.g. `GITHUB_DISPATCH_TOKEN=$(gh auth token)`).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .author import RECIPES_ROOT, _map_resources, _map_suffix
from .recipe import TEMPLATE_FILENAME, Recipe, RecipeError

REPO = os.environ.get("PUBLISH_GITHUB_REPO", "darkdiamond/govil.ai")
_NO_DATA = ("restricted", "unavailable")
_DEFAULT_FLOOR = "2025-01-01"
# A template that draws a map: Leaflet calls, GovMap, or a map element.
_MAP_RE = re.compile(r"\bL\.[a-zA-Z]+\(|\bGovMap\b|id=\"map", re.IGNORECASE)
_POINTS = {"Point", "MultiPoint"}


@dataclass
class MapFile:
    resource_id: str
    name: str
    format: str
    features: int = 0
    geometry_types: dict = field(default_factory=dict)
    crs: str = ""
    columns: list = field(default_factory=list)
    error: str = ""

    @property
    def points_only(self) -> bool:
        return bool(self.geometry_types) and set(self.geometry_types) <= _POINTS | {"none"}

    def line(self) -> str:
        if self.error:
            return f"`{self.resource_id}` {self.format} {self.name}: FAILED {self.error}"
        return (f"`{self.resource_id}` {self.format} {self.name}: {self.features:,} features "
                f"{json.dumps(self.geometry_types)}, {self.crs}, properties "
                f"{json.dumps(self.columns[:12], ensure_ascii=False)}")


@dataclass
class Candidate:
    src: object
    maps: list[MapFile]
    kind: str = ""
    why: str = ""
    issue: Optional[int] = None
    labels: list = field(default_factory=list)


def probe_map(res: dict, fetch_file_fn: Callable, work: Path) -> MapFile:
    """Download and parse one map file the way the refresh's `map` input does."""
    from . import geo_snapshot as gs
    from .refresh import _DEFAULT_MAP_MAX_BYTES, _PAGE_TIMEOUT_S, _env_int

    m = MapFile(res["id"], res.get("name") or "", res.get("format") or "")
    dest = work / f"{res['id'][:8]}{_map_suffix(res)}"
    try:
        fetch_file_fn(res.get("url") or "", dest,
                      max_bytes=_env_int("REFRESH_MAP_MAX_BYTES", _DEFAULT_MAP_MAX_BYTES),
                      timeout_s=_PAGE_TIMEOUT_S, deadline=time.monotonic() + 300)
        feats, prj = gs.parse_map(dest.read_bytes(), Path(res.get("url") or dest.name).name)
        if not feats:
            raise gs.SnapshotError("no features")
        m.crs = gs.detect_crs(feats, prj)
        m.features = len(feats)
        m.geometry_types = dict(sorted(Counter(
            (f.get("geometry") or {}).get("type") or "none" for f in feats).items()))
        m.columns = list(dict.fromkeys(k for f in feats for k in (f.get("properties") or {})))
    except Exception as e:
        m.error = f"{type(e).__name__}: {str(e)[:200]}"
    finally:
        dest.unlink(missing_ok=True)
    return m


def classify(c: Candidate, recipe: Optional[Recipe], open_issue: Optional[int]) -> None:
    good = [m for m in c.maps if not m.error]
    if not good:
        c.kind, c.why = "failed", "; ".join(m.error for m in c.maps)
        return
    if recipe is not None:
        read = {i.by_id for i in recipe.manifest.inputs if i.map or i.snapshot}
        if read & {m.resource_id for m in good}:
            c.kind, c.why = "mapped", "the recipe already reads the map file"
            return
        has_map = bool(_MAP_RE.search((recipe.root / TEMPLATE_FILENAME).read_text(encoding="utf-8")))
        if has_map and all(m.points_only for m in good):
            c.kind, c.why = "mapped", "its map already draws points; the file holds only points"
            return
        c.kind = "issue"
        c.why = ("its map draws points; the file has lines/polygons" if has_map
                 else "the page draws no map")
        return
    if open_issue:
        c.kind, c.why, c.issue = "comment", f"open issue #{open_issue}", open_issue
        return
    c.kind, c.why = "no_recipe", "no recipe and no open authoring issue"


def detail_text(c: Candidate) -> str:
    return ("Map files the daily job can download (add a `map: true` input):\n"
            + "\n".join("- " + m.line() for m in c.maps if not m.error))


def open_issues_by_id8(repo: str = REPO) -> dict[str, tuple[int, list[str]]]:
    """id8 → (number, labels) of open `[author] … (<id8>)` issues by the
    routine's trusted author."""
    out = subprocess.run(
        ["gh", "issue", "list", "--repo", repo, "--author", "darkdiamond", "--state", "open",
         "--limit", "1000", "--json", "number,title,labels"],
        check=True, capture_output=True, text=True,
    ).stdout
    found = {}
    for it in json.loads(out):
        m = re.search(r"\(([0-9a-f]{8})\)\s*$", it["title"])
        if m and it["title"].startswith("[author]"):
            found[m.group(1)] = (it["number"], [lb["name"] for lb in it.get("labels") or []])
    return found


def _iter_sources(store):
    from services.shared.firestore import SOURCES_COLL, SourceRecord

    for d in store.client.collection(SOURCES_COLL).stream():
        yield SourceRecord.from_doc(d)


def find_candidates(store, *, floor: datetime, recipes_root: Path = RECIPES_ROOT,
                    fetch_file_fn: Optional[Callable] = None,
                    issues: Optional[dict] = None, skip_ids: frozenset = frozenset()) -> list[Candidate]:
    from .agent_contract import fetch_resource_file

    fetch_file_fn = fetch_file_fn or fetch_resource_file
    issues = open_issues_by_id8() if issues is None else issues
    out = []
    with tempfile.TemporaryDirectory(prefix="map-backfill-") as tmp:
        for src in _iter_sources(store):
            if (src.id in skip_ids or getattr(src, "provider", None)
                    or src.analysis_status in _NO_DATA
                    or src.metadata_modified is None
                    or src.metadata_modified.astimezone(timezone.utc) < floor):
                continue
            files = _map_resources({"resources": src.resources})
            if not files:
                continue
            c = Candidate(src, [probe_map(r, fetch_file_fn, Path(tmp)) for r in files])
            recipe = None
            if (recipes_root / src.id / TEMPLATE_FILENAME).is_file():
                try:
                    recipe = Recipe.load(recipes_root / src.id)
                except (RecipeError, ValueError) as e:
                    c.kind, c.why = "failed", f"recipe doesn't load: {e}"
                    out.append(c)
                    continue
            issue = issues.get(src.id[:8])
            classify(c, recipe, issue[0] if issue else None)
            c.labels = issue[1] if issue else []
            out.append(c)
            print(f"  {src.id[:8]} {c.kind:9} {c.why[:90]}", file=sys.stderr)
    out.sort(key=lambda c: (c.kind, c.src.id))
    return out


def _report(cands: list[Candidate]) -> None:
    counts = Counter(c.kind for c in cands)
    print(f"\n{len(cands)} sources with map files: "
          + ", ".join(f"{k} {n}" for k, n in sorted(counts.items())))
    for c in cands:
        print(f"\n[{c.kind}] {c.src.id}  {c.src.title}\n  {c.why}")
        for m in c.maps:
            print(f"  - {m.line()}")


_MAP_BLOCK_RE = re.compile(r"author snapshot|in a browser|map file|CDN", re.IGNORECASE)


def _blocked_on_maps(number: int, repo: str = REPO) -> bool:
    """True when the issue's `authoring-blocked` comment blames the map file."""
    out = subprocess.run(["gh", "issue", "view", str(number), "--repo", repo, "--json", "comments"],
                         check=True, capture_output=True, text=True).stdout
    return any(_MAP_BLOCK_RE.search(cm.get("body") or "")
               for cm in json.loads(out).get("comments") or [])


def _comment(number: int, c: Candidate, repo: str = REPO) -> bool:
    """Comment on the issue; lift an `authoring-blocked` label that was about
    the map file. Returns whether the label was lifted."""
    body = ("The daily job can now download this dataset's map file itself, so a recipe can "
            "draw the geometry with a `map: true` input (no browser download, no committed "
            "snapshot; see `/author-dataset`, \"Map files\").\n\n```text\n"
            + detail_text(c).replace("`", "'") + "\n```\n")
    subprocess.run(["gh", "issue", "comment", str(number), "--repo", repo, "--body", body],
                   check=True, capture_output=True, text=True)
    if "authoring-blocked" in c.labels and _blocked_on_maps(number, repo):
        subprocess.run(["gh", "issue", "edit", str(number), "--repo", repo,
                        "--remove-label", "authoring-blocked"],
                       check=True, capture_output=True, text=True)
        return True
    return False


def open_all(store, cands: list[Candidate], *, max_new: int) -> dict:
    from .refresh import queue_authoring

    new = [c for c in cands if c.kind == "issue"]
    if len(new) > max_new:
        raise SystemExit(f"{len(new)} issues to open > --max-new {max_new}; "
                         "review `list` and re-run with a higher cap")
    done = {"opened": [], "commented": [], "unblocked": [], "errors": []}
    for c in new:
        n = queue_authoring(store, c.src, "map_available", detail=detail_text(c))
        (done["opened"] if n else done["errors"]).append((c.src.id, n))
    for c in (c for c in cands if c.kind == "comment"):
        try:
            if _comment(c.issue, c):
                done["unblocked"].append((c.src.id, c.issue))
            done["commented"].append((c.src.id, c.issue))
        except subprocess.CalledProcessError as e:
            done["errors"].append((c.src.id, (e.stderr or "")[:200]))
    return done


def _cli(argv: Optional[list[str]] = None) -> int:
    from services.shared.firestore import FirestoreStateStore

    ap = argparse.ArgumentParser(prog="python -m services.page_builder.map_backfill")
    ap.add_argument("cmd", choices=["list", "open"])
    ap.add_argument("--floor", default=os.environ.get("MIN_MODIFIED_FLOOR") or _DEFAULT_FLOOR,
                    help="skip sources CKAN last modified before this date (the selector's floor)")
    ap.add_argument("--max-new", type=int, default=50)
    ap.add_argument("--skip", nargs="*", default=[], help="dataset ids to leave out")
    args = ap.parse_args(argv)
    floor = datetime.fromisoformat(args.floor)
    floor = floor if floor.tzinfo else floor.replace(tzinfo=timezone.utc)
    if args.cmd == "open" and not os.environ.get("GITHUB_DISPATCH_TOKEN"):
        raise SystemExit("set GITHUB_DISPATCH_TOKEN (e.g. $(gh auth token))")
    store = FirestoreStateStore()
    cands = find_candidates(store, floor=floor, skip_ids=frozenset(args.skip))
    _report(cands)
    if args.cmd == "open":
        done = open_all(store, cands, max_new=args.max_new)
        print("\n" + json.dumps(done, ensure_ascii=False, indent=1))
        return 1 if done["errors"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
