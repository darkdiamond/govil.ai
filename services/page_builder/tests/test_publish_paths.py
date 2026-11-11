"""The three publish paths must do the same steps.

`.github/workflows/publish.yml` is the primary path; `cloudbuild-publish.yaml`
(PUBLISH_VIA=cloudbuild) and `infra/publish-local.sh` are the fallbacks. They
are maintained by hand, and the fallbacks used to miss steps added to the
primary (news images, analytics IDs, redirects, IndexNow). This checks each
file for a marker per step; it can't prove a step runs, only that nobody
forgot to write it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

PATHS = (
    ".github/workflows/publish.yml",
    "cloudbuild-publish.yaml",
    "infra/publish-local.sh",
)

# Steps that are commands: the marker must sit outside a quoted string on its
# line, so a log label like `step_begin "firebase deploy …"` can't stand in for
# the command itself.
COMMANDS = {
    "publish from Firestore", "news images rsync", "nuxt generate",
    "redirects", "firebase deploy", "IndexNow",
}

# step → a regex that must match the file once continuation lines are joined
MARKERS = {
    "publish from Firestore": r"services\.page_builder\.publish\s+--from-firestore",
    "news images rsync": r"rsync\b[^\n]*/news/",
    "nuxt generate": r"npm run generate",
    "NUXT_PUBLIC_GTAG_ID": r"NUXT_PUBLIC_GTAG_ID",
    "NUXT_PUBLIC_ADSENSE_ID": r"NUXT_PUBLIC_ADSENSE_ID",
    "NUXT_PUBLIC_CLARITY_ID": r"NUXT_PUBLIC_CLARITY_ID",
    "redirects": r"node\s+frontend/scripts/gen-redirects\.mjs",
    "firebase deploy": r"firebase\s+deploy\b",
    "IndexNow": r"node\s+frontend/scripts/indexnow-ping\.mjs",
}


def _joined(rel: str) -> str:
    """The file with backslash-continued lines joined into one, and full-line
    comments dropped, so a marker can't be satisfied by a comment."""
    text = re.sub(r"\\\n\s*", " ", (ROOT / rel).read_text(encoding="utf-8"))
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _unquoted_match(pattern: str, text: str) -> bool:
    """A match whose line prefix has balanced quotes, i.e. not inside a string."""
    for m in re.finditer(pattern, text):
        prefix = text[text.rfind("\n", 0, m.start()) + 1:m.start()]
        if prefix.count('"') % 2 == 0 and prefix.count("'") % 2 == 0:
            return True
    return False


@pytest.mark.parametrize("rel", PATHS)
@pytest.mark.parametrize("step", list(MARKERS))
def test_publish_path_has_step(rel, step):
    text = _joined(rel)
    found = (_unquoted_match(MARKERS[step], text) if step in COMMANDS
             else re.search(MARKERS[step], text))
    assert found, (
        f"{rel} lacks the '{step}' step (/{MARKERS[step]}/); keep the publish "
        f"paths in step: {', '.join(PATHS)}"
    )


# Order checks. Each step is located by its first command (outside a string).
# `publish-local.sh` runs `infra/sync-datasets.sh --apply`, which rsyncs the
# datasets and then deletes the publisher JSON, so that call counts as both.
SYNC_DATASETS_CALL = r"infra/sync-datasets\.sh\s+--apply"
DATASETS_RSYNC = rf"rsync\b[^\n]*/datasets/|{SYNC_DATASETS_CALL}"
STALE_JSON_DELETE = (
    r"find\s[^\n]*-name\s+'data\.json'[^\n]*-name\s+'agent_data\.json'[^\n]*-delete"
    rf"|{SYNC_DATASETS_CALL}"
)
# Cloud Build starts from a fresh workspace with no cache, so nothing stale
# can be there before its rsync (which excludes the JSON files).
NO_STALE_JSON = {"cloudbuild-publish.yaml"}


def _first(pattern: str, text: str) -> int | None:
    for m in re.finditer(pattern, text):
        prefix = text[text.rfind("\n", 0, m.start()) + 1:m.start()]
        if prefix.count('"') % 2 == 0 and prefix.count("'") % 2 == 0:
            return m.start()
    return None


@pytest.mark.parametrize("rel", PATHS)
def test_publish_path_step_order(rel):
    text = _joined(rel)
    rsync = _first(DATASETS_RSYNC, text)
    publish = _first(MARKERS["publish from Firestore"], text)
    generate = _first(MARKERS["nuxt generate"], text)
    assert rsync is not None, f"{rel} lacks the datasets content.html rsync"
    assert publish is not None and generate is not None, rel
    assert rsync < publish < generate, (
        f"{rel}: expected datasets rsync, then publish, then generate"
    )
    if rel in NO_STALE_JSON:
        return
    delete = _first(STALE_JSON_DELETE, text)
    assert delete is not None, (
        f"{rel} keeps data.json/agent_data.json from an earlier run: delete them "
        "after the datasets rsync, before the publisher writes its own"
    )
    assert rsync <= delete < publish, (
        f"{rel}: the stale-JSON delete must run after the rsync, before publish"
    )


def _push_paths() -> list[str]:
    text = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    block = re.search(r"^    paths:\n((?:      - .*\n)+)", text, re.MULTILINE)
    assert block, "publish.yml push paths not found"
    return re.findall(r'-\s+"([^"]+)"', block.group(1))


def test_push_paths_cover_publisher_imports():
    # Every services module the publisher loads, including the lazy news
    # store import, must trigger a deploy when it changes.
    code = (
        "import sys, services.page_builder.publish, services.news.publish_news, "
        "services.news.store\n"
        "for name, mod in sorted(sys.modules.items()):\n"
        "    f = getattr(mod, '__file__', None)\n"
        "    if name.startswith('services') and f: print(f)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    paths = _push_paths()

    def covered(rel: str) -> bool:
        return any(rel == p or (p.endswith("/**") and rel.startswith(p[:-2]))
                   for p in paths)

    files = [Path(f).resolve().relative_to(ROOT).as_posix() for f in out.split()]
    assert files
    missing = [f for f in files if not covered(f)]
    assert not missing, f"publish.yml push paths miss {missing}"


def test_publisher_image_pins_match_the_primary_path():
    # The fallback image must run the Node and firebase-tools the primary path
    # runs: publish.yml pins Node away from a release that breaks the deploy's
    # auth, and deploys with the lockfile's firebase-tools.
    workflow = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    node = re.search(r'node-version:\s*"([0-9.]+)"', workflow)
    assert node, "publish.yml node-version not found"
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    firebase = lock["packages"]["node_modules/firebase-tools"]["version"]

    dockerfile = (ROOT / "infra/Dockerfile.publisher").read_text(encoding="utf-8")
    base = re.search(r"^FROM\s+node:(\S+)", dockerfile, re.MULTILINE)
    assert base, "Dockerfile.publisher FROM node:<tag> not found"
    assert re.match(rf"{re.escape(node.group(1))}(-|$)", base.group(1)), (
        f"Dockerfile.publisher node:{base.group(1)} vs publish.yml {node.group(1)}"
    )
    assert re.search(rf"firebase-tools@{re.escape(firebase)}\b", dockerfile), (
        f"Dockerfile.publisher must install firebase-tools@{firebase} (the lockfile's)"
    )
