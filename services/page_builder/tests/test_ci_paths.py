"""CI and Dependabot cover the files the Python tests and the images depend on.

The `python` job in `.github/workflows/ci.yml` runs only when a file in its
paths filter moved, so a repo file a test reads must match that filter, or a
PR touching only that file skips the test that guards it.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import yaml

from services.page_builder.tags import ASSIGNMENTS_PATH, VOCAB_PATH
from services.page_builder.tests import test_hosting_cache, test_publish_paths

ROOT = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent


def _python_filter() -> list[str]:
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = ci["jobs"]["changes"]["steps"]
    filters = next(s["with"]["filters"] for s in steps if s.get("id") == "filter")
    return yaml.safe_load(filters)["python"]


def _read_paths() -> set[str]:
    """Repo files outside services/ that the guarded tests open."""
    paths = {
        test_hosting_cache.FIREBASE.relative_to(ROOT).as_posix(),
        VOCAB_PATH.relative_to(ROOT).as_posix(),
        ASSIGNMENTS_PATH.relative_to(ROOT).as_posix(),
        *test_publish_paths.PATHS,
        "agent/skills/check.py",
        "frontend/tests/fixtures/gov-map-vectors.json",
    }
    parity = (TESTS / "test_contract_parity.py").read_text(encoding="utf-8")
    paths |= set(re.findall(r'_read\("([^"]+)"\)', parity))
    return paths


def test_ci_python_filter_covers_files_tests_read():
    globs = _python_filter()
    paths = _read_paths()
    assert "firebase.json" in paths and "taxonomy/tags.json" in paths
    missing = sorted(p for p in paths
                     if not any(fnmatch.fnmatchcase(p, g) for g in globs))
    assert not missing, f"not in ci.yml's python paths filter: {missing}"
    for p in paths:
        assert (ROOT / p).is_file(), p


def _dependabot_dirs(ecosystem: str) -> set[str]:
    cfg = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    dirs: set[str] = set()
    for u in cfg["updates"]:
        if u["package-ecosystem"] == ecosystem:
            dirs |= {u["directory"]} if "directory" in u else set(u["directories"])
    return {d.rstrip("/") or "/" for d in dirs}


def _as_dir(path: Path) -> str:
    rel = path.parent.relative_to(ROOT).as_posix()
    return "/" if rel == "." else "/" + rel


def test_dependabot_covers_every_requirements_dir():
    reqs = [*ROOT.glob("requirements*.txt"), *(ROOT / "services").rglob("requirements*.txt")]
    missing = sorted({_as_dir(p) for p in reqs} - _dependabot_dirs("pip"))
    assert not missing, f"no dependabot pip entry for: {missing}"


def test_dependabot_covers_the_dockerfiles():
    files = [ROOT / "Dockerfile", ROOT / "infra" / "Dockerfile.publisher"]
    assert all(f.is_file() for f in files)
    missing = sorted({_as_dir(p) for p in files} - _dependabot_dirs("docker"))
    assert not missing, f"no dependabot docker entry for: {missing}"
