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


def test_batch_stages_only_recipe_files():
    text = _text()
    cmds = _commands(text, "git add") + _commands(text, "[ -f")
    assert cmds, "expected git add commands in SKILL.md"
    for cmd in cmds:
        # A whole recipes/ (or recipes/<id>/) dir would commit stray raw-row files.
        assert not re.search(r"\brecipes/(\S*/)?(\s|$)", cmd), cmd
    m = re.search(r"^## 6\. One PR.*?(?=^## )", text, re.DOTALL | re.MULTILINE)
    assert m, "step 6 not found"
    for name in ("recipe.json", "compute.py", "template.html.j2", "coverage.json",
                 "source.json", "snapshot"):
        assert name in m.group(0), name


def test_trust_boundary_accepts_provider_ids_as_well_as_uuids():
    # The builder titles a provider source's issue with its full id
    # (`(cbs-index-cpi)`); a UUID-only rule would drop those issues silently.
    text = _text()
    m = re.search(r"^## Trust boundary.*?(?=^## )", text, re.DOTALL | re.MULTILINE)
    assert m, "Trust boundary section not found"
    section = m.group(0)
    uuid_rule = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    provider_rule = "^(boi|cbs)-[a-z0-9-]{1,60}$"
    assert uuid_rule in section, section
    assert provider_rule in section, section
    assert "source.json" in section, section
    # The rule must accept what the builder actually writes for a provider.
    from services.page_builder import notify

    pid = "cbs-index-cpi"
    body = notify.issue_body(dataset_id=pid, title="t", org="o",
                             reason="recipe_failed", detail="d")
    line = re.search(r"^- dataset: `([^`]+)`$", body, re.MULTILINE)
    assert line and re.fullmatch(provider_rule, line.group(1))
    assert notify.issue_title("t", pid).endswith(f"({line.group(1)})")


def test_routine_merges_only_through_the_guard():
    # The routine merges its own batch PR, but only after automerge_guard
    # passes, and never with --admin, --auto or a force.
    text = _text()
    m = re.search(r"^## 6a\. Auto-merge.*?(?=^## )", text, re.DOTALL | re.MULTILINE)
    assert m, "step 6a not found"
    section = m.group(0)
    # main's copy of the guard, never the batch branch's own (it would judge itself)
    assert "git show origin/main:services/page_builder/automerge_guard.py" in section
    guard = _commands(section, "python3 -I /tmp/automerge_guard_main.py")
    assert guard and "--wait" in guard[0], guard
    assert "python -m services.page_builder.automerge_guard" not in section
    merges = _commands(text, "gh pr merge")
    assert len(merges) == 1, merges
    merge = merges[0]
    assert merge in section
    for flag in ("--merge", "--match-head-commit", "--repo"):
        assert flag in merge, merge
    for flag in ("--admin", "--auto", "--squash", "--rebase"):
        assert flag not in merge, merge
    assert section.index("automerge_guard") < section.index("gh pr merge")
    assert "Review:" in text
