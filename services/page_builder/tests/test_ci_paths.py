"""CI and Dependabot cover the files the Python tests and the images depend on.

The `python` job in `.github/workflows/ci.yml` runs only when a file in its
paths filter moved, so a repo file a test reads must match that filter, or a
PR touching only that file skips the test that guards it. The config files are
read with plain line parsing: PyYAML is not a CI dependency.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from services.page_builder.tags import ASSIGNMENTS_PATH, VOCAB_PATH

ROOT = Path(__file__).resolve().parents[3]

# Repo files tests read through a constant of the module under test, which a
# scan of the test sources can't see.
INDIRECT = (VOCAB_PATH, ASSIGNMENTS_PATH)

_STR = r"""(?:"([^"\n]*)"|'([^'\n]*)')"""
_JOIN = rf"((?:\s*\)?\s*/\s*{_STR})+)"
_ROOT_EXPR = r"Path\(__file__\)\.resolve\(\)\.parents\[(\d)\]"


def _python_filter() -> list[str]:
    """The `python:` globs of the paths filter in ci.yml."""
    lines = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "python:")
    indent = len(lines[start]) - len(lines[start].lstrip())
    globs = []
    for ln in lines[start + 1:]:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if len(ln) - len(ln.lstrip()) <= indent:
            break
        m = re.fullmatch(r"-\s*'([^']+)'", s)
        assert m, f"unexpected line in the python filter: {ln!r}"
        globs.append(m.group(1))
    return globs


def _strings(text: str) -> list[str]:
    return [a or b for a, b in re.findall(_STR, text)]


def _test_reads() -> dict[str, set[str]]:
    """Repo paths outside services/ that the test sources under services/ name:
    root-relative string literals naming a committed file, and literal joins
    off a `Path(__file__).resolve().parents[N]` that is the repo root, or off a
    name bound to such a path. Maps each path to the tests that name it."""
    found: dict[str, set[str]] = {}
    for f in sorted((ROOT / "services").glob("**/tests/*.py")):
        src = f.read_text(encoding="utf-8")
        flat = re.sub(r"\s+", " ", src)
        who = f.relative_to(ROOT).as_posix()

        for s in _strings(src):
            if s and not s.startswith(("/", "services/")) and (ROOT / s).is_file():
                found.setdefault(s, set()).add(who)

        heads: dict[str, str] = {}  # regex of a root-based expression -> its path
        for m in re.finditer(rf"(?:(\w+)\s*=\s*)?{_ROOT_EXPR}", flat):
            if f.resolve().parents[int(m.group(2))] == ROOT:
                heads[re.escape(m.group(0).split("=")[-1].strip())] = ""
                if m.group(1):
                    heads[rf"\b{m.group(1)}\b"] = ""
        joins: set[tuple[str, str]] = set()  # (path, name it is bound to)
        for _ in range(3):  # names bound to joins, up to three levels deep
            for head, prefix in list(heads.items()):
                for m in re.finditer(rf"(?:(\w+)\s*=\s*)?\(?\s*{head}{_JOIN}", flat):
                    path = "/".join(filter(None, [prefix, *_strings(m.group(2))]))
                    if m.group(1):
                        heads.setdefault(rf"\b{m.group(1)}\b", path)
                    joins.add((path, m.group(1) or ""))
        for path, name in joins:
            if name and re.search(rf"\b{name}\b{_JOIN}", flat):
                continue  # the name's own joins list the files it reads
            found.setdefault(path, set()).add(who)
    return found


def test_ci_python_filter_covers_files_tests_read():
    globs = _python_filter()
    reads = _test_reads()
    for p in INDIRECT:
        reads.setdefault(p.relative_to(ROOT).as_posix(), set()).add("(module constant)")
    # the scan still finds the reads it was written against
    tests = "services/page_builder/tests/"
    assert tests + "test_skills.py" in reads[".claude/skills/solve-authoring-issues/SKILL.md"]
    assert tests + "test_hosting_cache.py" in reads["firebase.json"]
    assert tests + "test_contract_parity.py" in reads["frontend/nuxt.config.ts"]
    assert "(module constant)" in reads["taxonomy/tags.json"]

    def covered(path: str) -> bool:
        target = path + "/x" if (ROOT / path).is_dir() else path
        return any(fnmatch.fnmatchcase(target, g) for g in globs)

    missing = sorted(
        f"{p} (read by {', '.join(sorted(who))})"
        for p, who in reads.items()
        # a wildcard names the uncommitted local page corpus, not a repo file
        if not p.startswith("services/") and "*" not in p and not covered(p)
    )
    assert not missing, f"not in ci.yml's python paths filter: {missing}"


def _dependabot_dirs(ecosystem: str) -> set[str]:
    text = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
    dirs: set[str] = set()
    for entry in re.split(r"^\s*-\s*package-ecosystem:", text, flags=re.MULTILINE)[1:]:
        if entry.split("\n", 1)[0].strip().strip("\"'") != ecosystem:
            continue
        m = re.search(r"^\s*directory:\s*[\"']?([^\"'\n]+)", entry, re.MULTILINE)
        assert m, f"dependabot {ecosystem} entry without a directory"
        dirs.add(m.group(1).strip().rstrip("/") or "/")
    return dirs


def test_dependabot_covers_every_requirements_dir():
    reqs = [*ROOT.glob("requirements*.txt"), *(ROOT / "services").rglob("requirements*.txt")]
    dirs = set()
    for p in reqs:
        rel = p.parent.relative_to(ROOT).as_posix()
        dirs.add("/" if rel == "." else "/" + rel)
    missing = sorted(dirs - _dependabot_dirs("pip"))
    assert not missing, f"no dependabot pip entry for: {missing}"


def test_dependabot_covers_the_dockerfiles():
    # the builder's Dockerfile at the root and infra/Dockerfile.publisher
    missing = sorted({"/", "/infra"} - _dependabot_dirs("docker"))
    assert not missing, f"no dependabot docker entry for: {missing}"
