"""`run_host_check` — agent/skills/check.py on the sanitized body, the final
gate before anything is staged (recipe refresh and `author verify`)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT_PATH = REPO_ROOT / "agent" / "skills" / "check.py"
_CHECK_TIMEOUT_S = 60


def run_host_check(
    content_html: str, agent_data_json: str, workdir: Path, *, recipe: bool = False
) -> None:
    """Run agent/skills/check.py on the sanitized outputs; raise on non-zero.

    The sanitizer may have rewritten the body, so this runs on its output —
    the authoritative gate. Used by the recipe refresh before anything
    reaches GCS/Firestore and by `author verify`, so a recipe passes the
    exact same bar locally as in production.

    Trust boundary: this always runs the IMAGE's check.py
    (`CHECK_SCRIPT_PATH`, root-owned under /app) — never a copy inside a
    sandbox workdir, which sandboxed code could rewrite. `workdir` must be
    a HOST-owned directory, not the sandbox workdir: the sandbox user owns
    that tree and could pre-plant a symlink at validated-content.html that
    this (root) process would write through.
    `-I` keeps PYTHONPATH/user-site/cwd out of check.py's import path.
    """
    c = workdir / "validated-content.html"
    a = workdir / "validated-agent_data.json"
    c.write_text(content_html, encoding="utf-8")
    a.write_text(agent_data_json, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-I", str(CHECK_SCRIPT_PATH), *(["--recipe"] if recipe else []),
             str(c), str(a)],
            capture_output=True,
            text=True,
            timeout=_CHECK_TIMEOUT_S,
            check=False,  # the exit code is reported below, with the output
        )
    except subprocess.TimeoutExpired as e:
        # The body decides how long check.py takes, so this is the page's
        # failure like any other verdict, not a crash.
        raise RuntimeError(
            f"host self-check timed out after {_CHECK_TIMEOUT_S}s "
            f"({len(content_html):,} bytes of content)"
        ) from e
    if proc.returncode != 0:
        raise RuntimeError(
            f"host self-check failed (exit {proc.returncode}): "
            f"{(proc.stdout or proc.stderr).strip()[:500]}"
        )
