"""Static checks on the unattended authoring routine's skill file.

The repo is public, so anyone can open a PR from a fork. The routine must
count only same-repo PRs and must never read PR text, only issue numbers.
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL = (
    Path(__file__).resolve().parents[3]
    / ".claude"
    / "skills"
    / "solve-authoring-issues"
    / "SKILL.md"
)


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _commands(text: str, prefix: str) -> list[str]:
    """Each shell command starting with ``prefix``, joined across ``\\`` line breaks."""
    joined = re.sub(r"\\\n\s*", " ", text)
    return [line.strip() for line in joined.splitlines() if line.strip().startswith(prefix)]


def test_pr_list_counts_only_same_repo_prs_and_reads_no_pr_text():
    cmds = _commands(_text(), "gh pr list")
    assert cmds, "expected a gh pr list command in SKILL.md"
    for cmd in cmds:
        assert "isCrossRepository" in cmd, cmd
        assert "--jq" in cmd, cmd


def test_trust_boundary_covers_pull_requests():
    text = _text()
    m = re.search(r"^## Trust boundary.*?(?=^## )", text, re.DOTALL | re.MULTILINE)
    assert m, "Trust boundary section not found"
    # About PR text as input, not the existing rule on what the batch PR may change.
    assert re.search(r"\b(PR|pull request) (titles|bodies)", m.group(0), re.IGNORECASE), m.group(0)
