"""The three publish paths must do the same steps.

`.github/workflows/publish.yml` is the primary path; `cloudbuild-publish.yaml`
(PUBLISH_VIA=cloudbuild) and `infra/publish-local.sh` are the fallbacks. They
are maintained by hand, and the fallbacks used to miss steps added to the
primary (news images, analytics IDs, redirects, IndexNow). This checks each
file for a marker per step; it can't prove a step runs, only that nobody
forgot to write it.
"""
from __future__ import annotations

import re
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
