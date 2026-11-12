"""Mechanical gate for the authoring routine's self-merge.

`/solve-authoring-issues` runs unattended and merges its own batch PR, but
only when this guard finds nothing wrong. Recipe `compute.py` is
model-written and runs in the builder container, which can reach the
builder service account's token (CLAUDE.md, "Sandbox boundary"), and the
authoring model reads untrusted dataset content. So the merge decision rests
on these checks, not on the model's judgement:

- the PR is open, same-repo, not a draft, based on `main`, mergeable, and
  every CI check passed;
- it changes only `recipes/<id>/<recipe file>` (and the dataset tag list),
  deletes nothing outside the recipe dirs it changes, and adds no symlink;
- each changed `compute.py` imports only allowlisted modules and uses none of
  the names, attributes or I/O calls that bypass that allowlist;
- each changed template loads no script and links only to allowed hosts;
- `recipe.json` / `source.json` / `agent_data.seo` use only keys some recipe
  on main already uses (a new key means "deploy the job first");
- every `govlib` helper a recipe uses exists on main.

    python -m services.page_builder.automerge_guard <pr-number> [--wait SECONDS]

Prints one problem per line and exits 1, or prints `ok <head sha>` and exits
0 (merge with `--match-head-commit <sha>` so a later push can't ride along).
It reads GitHub with `gh` (read-only) and the PR's files with git:
`git fetch` of `refs/pull/<n>/head` and `main`, then `git diff --raw` from
the merge base and `git cat-file` for contents. git rather than the contents
API: no 1MB/base64 limit for snapshot geojson, and the raw diff carries file
modes (symlinks) and deletions.

`check(files, read)` is the importable core (no GitHub, no network).
Stdlib only.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

REPO = "darkdiamond/govil.ai"

# Same id rules as the skill's trust boundary.
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PROVIDER_RE = re.compile(r"^(boi|cbs)-[a-z0-9-]{1,60}$")

# What a recipe dir on main holds (2026-11-12: 375 dirs, each with the first
# four; 32 provider dirs add source.json; 3 snapshot recipes add a
# `<name>.geojson` named by an input's `snapshot`).
RECIPE_FILES = frozenset(
    {"recipe.json", "compute.py", "template.html.j2", "coverage.json", "source.json"}
)
SNAPSHOT_SUFFIX = ".geojson"
TAGS_FILE = "taxonomy/dataset-tags.json"

# Top-level modules compute.py may import: the union over every
# recipes/*/compute.py on main (2026-11-12). None of them gives network,
# process, filesystem or dynamic-code power by itself; the attribute and
# name rules below close what pandas/numpy expose. Recipes read their inputs
# as DataFrames passed to compute(frames) (recipe_exec.py), so no io, os or
# pathlib. test_automerge_guard.py fails if a merged recipe imports anything
# outside this set.
ALLOWED_IMPORTS = frozenset({
    "__future__", "calendar", "collections", "datetime", "govlib", "html",
    "itertools", "json", "math", "numpy", "pandas", "re", "statistics",
    "unicodedata",
})
# Never allowed, even if a future recipe on main used one (the honesty test
# checks the two sets stay disjoint).
FORBIDDEN_IMPORTS = frozenset({
    "socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp",
    "ftplib", "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "webbrowser",
    "subprocess", "os", "sys", "shutil", "ctypes", "cffi", "importlib", "pickle",
    "marshal", "shelve", "dill", "multiprocessing", "concurrent", "threading",
    "_thread", "signal", "builtins", "runpy", "code", "codeop", "pty", "asyncio",
    "glob", "pathlib", "tempfile", "io", "inspect", "gc", "resource", "fcntl",
    "mmap", "operator", "types", "zipimport", "pkgutil", "site", "sysconfig",
})
# `from pandas.x import ...` / `import numpy.x`: only these dotted modules.
ALLOWED_SUBMODULES = frozenset({"govlib.cbs", "govlib.fmt", "govlib.frame", "govlib.geo"})

# Builtins that reach other code or the interpreter. Banned as any reference,
# not only as calls (`f = eval` is the same thing). `open` has its own rule.
BANNED_NAMES = frozenset({
    "__import__", "eval", "exec", "compile", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "breakpoint", "input", "help", "memoryview",
    "exit", "quit",
})
# Dunder attributes recipes may touch (main uses `__setitem__`). Every other
# `.__x__` (`__class__`, `__subclasses__`, `__globals__`, `__builtins__`,
# `__code__`, `__dict__`, ...) is a problem.
ALLOWED_DUNDER_ATTRS = frozenset({"__setitem__", "__getitem__", "__contains__", "__len__"})
# pandas / numpy attributes that read or write files or URLs, or evaluate
# strings, whatever the receiver. `pd.read_csv(url, storage_options=...)`
# and `np.genfromtxt(url)` fetch URLs, so `read_*` is banned outright.
BANNED_ATTRS = frozenset({
    "to_pickle", "to_parquet", "to_feather", "to_hdf", "to_sql", "to_stata",
    "to_orc", "to_excel", "to_clipboard", "load", "loadtxt", "genfromtxt",
    "fromfile", "fromregex", "save", "savez", "savez_compressed", "savetxt",
    "tofile", "memmap", "DataSource", "ctypeslib", "lib", "f2py", "distutils",
    "testing", "io", "eval", "system", "popen",
})
BANNED_ATTR_PREFIXES = ("read_",)
# Writers that return a string with no target but write a file given one.
PATH_WRITERS = frozenset({
    "to_csv", "to_json", "to_html", "to_xml", "to_latex", "to_markdown", "to_string",
})
PATH_WRITER_KWARGS = frozenset({"path_or_buf", "buf", "path", "excel_writer"})
BANNED_KWARGS = frozenset({"storage_options", "local_dict", "global_dict", "resolvers"})
# A string naming an interpreter internal (`"{0.__class__.__globals__}".format`).
DUNDER_STRING_RE = re.compile(
    r"__(?:class|globals|subclasses|builtins|code|mro|bases|base|dict|import|"
    r"loader|spec|getattribute|reduce|reduce_ex|closure|func|self|init)__"
)
WRITE_MODE_CHARS = set("wax+")

# Hosts a template may name in an absolute URL. check.py (run on every
# rendered body) already bans `<script src=>`, network calls and src= loads
# outside gov.il / openstreetmap.org; this is the static pre-check on the
# template source. Main's templates name www.gov.il pages and OSM tiles.
TEMPLATE_HOSTS = ("gov.il", "boi.org.il", "openstreetmap.org")
_SCRIPT_SRC_RE = re.compile(r"<script\b[^>]*\bsrc\s*=", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s\"'<>`)\]\\]*", re.IGNORECASE)
_PROTO_RELATIVE_RE = re.compile(
    r"\b(?:src|href|action|poster|data|formaction)\s*=\s*[\"']?\s*//", re.IGNORECASE
)
_JINJA_BLOCK_RE = re.compile(r"\{[{%].*?[}%]\}", re.DOTALL)
_DUNDER_RE = re.compile(r"__\w+__")
_LEAFLET_SUBDOMAIN = "{s}."

# Free-form dict keys in recipe.json (keyed by input name): normalized to `*`.
FREE_KEY_PARENTS = frozenset({"authored_against.rows"})

PR_FIELDS = "files,headRefOid,state,isDraft,mergeable,baseRefName,isCrossRepository"


# ---------------------------------------------------------------------------
# What main already has
# ---------------------------------------------------------------------------

@dataclass
class MainCorpus:
    """Facts from `main` the checks compare a PR against."""

    recipe_keys: set[str] = field(default_factory=set)
    source_keys: set[str] = field(default_factory=set)
    seo_keys: set[str] = field(default_factory=set)
    govlib: dict[str, set[str]] = field(default_factory=dict)  # module -> names
    provider_ids: set[str] = field(default_factory=set)  # dirs with source.json
    recipe_ids: set[str] = field(default_factory=set)


def json_key_paths(obj: object, prefix: str = "") -> set[str]:
    """Every dict key path in a JSON document (`inputs[].by_id`)."""
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = "*" if prefix in FREE_KEY_PARENTS else str(k)
            path = f"{prefix}.{key}" if prefix else key
            out.add(path)
            out |= json_key_paths(v, path)
    elif isinstance(obj, list):
        for v in obj:
            out |= json_key_paths(v, prefix + "[]")
    return out


def seo_literal_keys(tree: ast.AST) -> set[str]:
    """Keys of `seo` dict literals: `"seo": {...}` or `seo = {...}`."""
    out: set[str] = set()

    def keys(d: ast.Dict) -> None:
        for k in d.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                out.add(k.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "seo"
                        and isinstance(v, ast.Dict)):
                    keys(v)
        elif (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
              and any(isinstance(t, ast.Name) and t.id == "seo" for t in node.targets)):
            keys(node.value)
    return out


def module_names(source: str) -> set[str]:
    """Top-level names a module defines or imports."""
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
    return names


GOVLIB_DIR = "services/page_builder/recipe_lib/govlib/"


def build_corpus(paths: Iterable[str], read: Callable[[str], str]) -> MainCorpus:
    c = MainCorpus()
    for path in paths:
        if path.startswith(GOVLIB_DIR) and path.endswith(".py"):
            mod = path[len(GOVLIB_DIR):-3]
            if "/" not in mod and mod != "__init__":
                c.govlib[mod] = module_names(read(path))
            continue
        parts = path.split("/")
        if len(parts) != 3 or parts[0] != "recipes":
            continue
        rid, name = parts[1], parts[2]
        c.recipe_ids.add(rid)
        if name == "recipe.json":
            c.recipe_keys |= json_key_paths(json.loads(read(path)))
        elif name == "source.json":
            c.provider_ids.add(rid)
            c.source_keys |= json_key_paths(json.loads(read(path)))
        elif name == "compute.py":
            c.seo_keys |= seo_literal_keys(ast.parse(read(path)))
    return c


# ---------------------------------------------------------------------------
# Per-file checks
# ---------------------------------------------------------------------------

def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _attr_problem(attr: str) -> str | None:
    if _is_dunder(attr) and attr not in ALLOWED_DUNDER_ATTRS:
        return f"attribute `{attr}`"
    if attr in BANNED_ATTRS or attr.startswith(BANNED_ATTR_PREFIXES):
        return f"attribute `{attr}` (file/URL I/O or string eval)"
    return None


def _open_mode(call: ast.Call) -> ast.expr | None:
    if len(call.args) >= 2:
        return call.args[1]
    for kw in call.keywords:
        if kw.arg == "mode":
            return kw.value
    return None


def check_compute(path: str, source: str, corpus: MainCorpus) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"{path}: does not parse ({e.msg}, line {e.lineno})"]
    problems: list[str] = []

    def bad(node: ast.AST, what: str) -> None:
        problems.append(f"{path}:{getattr(node, 'lineno', '?')}: {what}")

    govlib_alias: dict[str, str] = {}  # local name -> govlib module ("" = package)
    open_calls: set[int] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]
                if top not in ALLOWED_IMPORTS or top in FORBIDDEN_IMPORTS:
                    bad(node, f"imports `{a.name}` (not in the allowlist)")
                elif "." in a.name and a.name not in ALLOWED_SUBMODULES:
                    bad(node, f"imports submodule `{a.name}`")
                elif top == "govlib":
                    sub = a.name.partition(".")[2]
                    if sub and sub not in corpus.govlib:
                        bad(node, f"govlib module `{sub}` is not on main (deploy first)")
                    if a.asname:
                        govlib_alias[a.asname] = sub
                    else:
                        govlib_alias["govlib"] = ""
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            top = mod.split(".")[0]
            if node.level or not mod:
                bad(node, "relative import")
                continue
            if top not in ALLOWED_IMPORTS or top in FORBIDDEN_IMPORTS:
                bad(node, f"imports from `{mod}` (not in the allowlist)")
                continue
            if "." in mod and mod not in ALLOWED_SUBMODULES:
                bad(node, f"imports from submodule `{mod}`")
                continue
            for a in node.names:
                if a.name == "*":
                    bad(node, f"star import from `{mod}`")
                    continue
                why = _attr_problem(a.name)
                if why or a.name in BANNED_NAMES:
                    bad(node, f"imports `{a.name}` from `{mod}`")
                if top != "govlib":
                    continue
                if mod == "govlib":
                    if a.name not in corpus.govlib:
                        bad(node, f"govlib has no `{a.name}` on main (deploy the helper first)")
                    else:
                        govlib_alias[a.asname or a.name] = a.name
                else:
                    sub = mod.partition(".")[2]
                    if a.name not in corpus.govlib.get(sub, set()):
                        bad(node, f"govlib.{sub} has no `{a.name}` on main "
                                  "(deploy the helper first)")
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES or _is_dunder(node.id):
                bad(node, f"uses `{node.id}`")
        elif isinstance(node, ast.Attribute):
            why = _attr_problem(node.attr)
            if why:
                bad(node, f"uses {why}")
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in BANNED_KWARGS:
                    bad(node, f"passes `{kw.arg}=`")
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                open_calls.add(id(func))
                mode = _open_mode(node)
                if mode is not None and not (
                    isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                    and not (set(mode.value) & WRITE_MODE_CHARS)
                ):
                    bad(node, "calls `open` with a write or non-literal mode")
            if isinstance(func, ast.Attribute):
                if func.attr in PATH_WRITERS and (
                    node.args or any(k.arg in PATH_WRITER_KWARGS for k in node.keywords)
                ):
                    bad(node, f"`{func.attr}` with a target (writes a file)")
                if func.attr == "query":
                    arg = node.args[0] if node.args else None
                    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                            and "@" not in arg.value and "__" not in arg.value):
                        bad(node, "`query` needs a plain string literal (no `@`, no `__`)")
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and DUNDER_STRING_RE.search(node.value)):
            bad(node, "string names an interpreter internal")

    # `open` referenced other than as a direct call (`f = open`).
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "open" and id(node) not in open_calls:
            bad(node, "references `open` other than in a read-only call")

    # govlib.<module>.<name> / <alias>.<name> must exist on main.
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)):
            continue
        alias = node.value.id
        if alias not in govlib_alias:
            continue
        sub = govlib_alias[alias]
        if sub == "":  # the package itself: `govlib.fmt`
            if node.attr not in corpus.govlib:
                bad(node, f"govlib has no `{node.attr}` on main (deploy the helper first)")
        elif node.attr not in corpus.govlib.get(sub, set()):
            bad(node, f"govlib.{sub} has no `{node.attr}` on main (deploy the helper first)")
    for node in ast.walk(tree):  # govlib.fmt.int_he
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and govlib_alias.get(node.value.value.id) == ""
                and node.value.attr in corpus.govlib
                and node.attr not in corpus.govlib[node.value.attr]):
            bad(node, f"govlib.{node.value.attr} has no `{node.attr}` on main "
                      "(deploy the helper first)")

    for key in sorted(seo_literal_keys(tree) - corpus.seo_keys):
        problems.append(f"{path}: agent_data.seo key `{key}` no merged recipe uses yet; "
                        "needs a job deploy before merge")
    return problems


def _host_allowed(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in TEMPLATE_HOSTS)


def check_template(path: str, source: str) -> list[str]:
    problems: list[str] = []
    if _SCRIPT_SRC_RE.search(source):
        problems.append(f"{path}: has a <script src=>")
    if _PROTO_RELATIVE_RE.search(source):
        problems.append(f"{path}: has a protocol-relative URL (//host)")
    for m in _URL_RE.finditer(source):
        url = m.group(0)
        if url.startswith(("https://" + _LEAFLET_SUBDOMAIN, "http://" + _LEAFLET_SUBDOMAIN)):
            url = url.replace(_LEAFLET_SUBDOMAIN, "", 1)  # Leaflet tile subdomain
        try:
            parts = urlsplit(url)
            netloc = parts.netloc
            host = (parts.hostname or "").lower().rstrip(".")
            _ = parts.port  # raises on a malformed port
        except ValueError:
            problems.append(f"{path}: malformed URL `{m.group(0)[:80]}`")
            continue
        if not host or any(ch in netloc for ch in "@{}%") or not _host_allowed(host):
            problems.append(f"{path}: URL host not allowed: `{m.group(0)[:80]}`")
    for m in _JINJA_BLOCK_RE.finditer(source):
        if _DUNDER_RE.search(m.group(0)):
            problems.append(f"{path}: Jinja expression touches a dunder name")
            break
    return problems


def check_json_keys(path: str, text: str, known: set[str]) -> list[str]:
    try:
        doc = json.loads(text)
    except ValueError as e:
        return [f"{path}: not valid JSON ({e})"]
    new = sorted(json_key_paths(doc) - known)
    return [f"{path}: uses a {path.rsplit('/', 1)[1]} field no merged recipe uses yet "
            f"(`{k}`); needs a job deploy before merge" for k in new]


# ---------------------------------------------------------------------------
# The whole PR
# ---------------------------------------------------------------------------

def _recipe_path(path: str) -> tuple[str, str] | None:
    parts = path.split("/")
    if len(parts) == 3 and parts[0] == "recipes":
        return parts[1], parts[2]
    return None


def check(
    files: list[str],
    read: Callable[[str], str],
    *,
    deleted: Iterable[str] = (),
    corpus: MainCorpus | None = None,
) -> list[str]:
    """Problems with a PR that adds/modifies `files` and deletes `deleted`.

    `read(path)` returns a changed file's content at the PR head. `corpus`
    is what main holds (default: `corpus_from_git("origin/main")`). A rename
    is a deletion of the old path plus an added new path. Empty list = OK.
    """
    if corpus is None:
        corpus = corpus_from_git("origin/main")
    deleted = list(deleted)
    problems: list[str] = []
    if not files and not deleted:
        return ["PR changes no files"]

    touched: set[str] = set()  # recipe dirs with an added/modified file
    for path in files:
        if path == TAGS_FILE:
            continue
        rp = _recipe_path(path)
        if rp is None:
            problems.append(f"{path}: outside recipes/<id>/ and {TAGS_FILE}")
            continue
        rid, name = rp
        if not (UUID_RE.match(rid) or PROVIDER_RE.match(rid)):
            problems.append(f"{path}: `{rid}` is neither a dataset UUID nor a boi-/cbs- id")
            continue
        if name not in RECIPE_FILES and not name.endswith(SNAPSHOT_SUFFIX):
            problems.append(f"{path}: not a recipe file")
            continue
        touched.add(rid)

    for path in deleted:
        rp = _recipe_path(path)
        if rp is None or rp[0] not in touched:
            problems.append(f"{path}: deleted outside the recipe dirs this PR changes")

    changed = set(files)
    for rid in sorted(touched):
        base = f"recipes/{rid}/"
        recipe_path = base + "recipe.json"
        if PROVIDER_RE.match(rid) and rid not in corpus.provider_ids:
            problems.append(f"{base}: a provider recipe that is not on main "
                            "(provider recipes are fixes only)")
        if UUID_RE.match(rid) and base + "source.json" in changed:
            problems.append(f"{base}source.json: a CKAN dataset recipe can't add source.json")
        try:
            recipe = json.loads(read(recipe_path))
        except (OSError, KeyError, ValueError) as e:  # missing at head, or bad JSON
            problems.append(f"{recipe_path}: unreadable at the PR head ({type(e).__name__})")
            recipe = None
        if isinstance(recipe, dict):
            if recipe.get("dataset_id") != rid:
                problems.append(f"{recipe_path}: dataset_id does not match the directory")
            snapshots = {i.get("snapshot") for i in recipe.get("inputs") or []
                         if isinstance(i, dict)}
            for path in changed:
                if (path.startswith(base) and path.endswith(SNAPSHOT_SUFFIX)
                        and path[len(base):] not in snapshots):
                    problems.append(f"{path}: not a snapshot recipe.json declares")

    for path in files:
        rp = _recipe_path(path)
        if rp is None or rp[0] not in touched:
            continue
        name = rp[1]
        if name == "compute.py":
            problems += check_compute(path, read(path), corpus)
        elif name == "template.html.j2":
            problems += check_template(path, read(path))
        elif name == "recipe.json":
            problems += check_json_keys(path, read(path), corpus.recipe_keys)
        elif name == "source.json":
            problems += check_json_keys(path, read(path), corpus.source_keys)
        elif name in ("coverage.json",) or name.endswith(SNAPSHOT_SUFFIX):
            try:
                json.loads(read(path))
            except ValueError:
                problems.append(f"{path}: not valid JSON")
    if TAGS_FILE in changed:
        try:
            json.loads(read(TAGS_FILE))
        except ValueError:
            problems.append(f"{TAGS_FILE}: not valid JSON")
    return problems


# ---------------------------------------------------------------------------
# git / gh plumbing
# ---------------------------------------------------------------------------

def _run(args: list[str], check_rc: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=check_rc)


def git_tree_reader(ref: str, prefixes: list[str]) -> tuple[list[str], Callable[[str], str]]:
    """Paths under `prefixes` at `ref`, and a reader that batches `git cat-file`."""
    out = _run(["git", "ls-tree", "-r", "--name-only", ref, "--", *prefixes]).stdout
    paths = [p for p in out.splitlines() if p]
    cache: dict[str, str] = {}

    def prefetch(wanted: list[str]) -> None:
        todo = [p for p in wanted if p not in cache]
        if not todo:
            return
        proc = subprocess.run(
            ["git", "cat-file", "--batch"], input="".join(f"{ref}:{p}\n" for p in todo).encode(),
            capture_output=True, check=True,
        )
        data, pos = proc.stdout, 0
        for p in todo:
            nl = data.index(b"\n", pos)
            header = data[pos:nl].decode()
            pos = nl + 1
            if header.endswith(" missing"):
                continue
            size = int(header.rsplit(" ", 1)[1])
            cache[p] = data[pos:pos + size].decode("utf-8")
            pos += size + 1

    def read(path: str) -> str:
        prefetch([path])
        if path not in cache:
            raise FileNotFoundError(path)
        return cache[path]

    prefetch([p for p in paths if p.endswith((".json", ".py"))])
    return paths, read


def corpus_from_git(ref: str) -> MainCorpus:
    paths, read = git_tree_reader(ref, ["recipes", GOVLIB_DIR])
    wanted = [p for p in paths if p.endswith(("/recipe.json", "/source.json", "/compute.py"))
              or (p.startswith(GOVLIB_DIR) and p.endswith(".py"))]
    return build_corpus(wanted, read)


def pr_diff(base: str, head: str) -> tuple[list[str], list[str], list[str]]:
    """(added/modified paths, deleted paths, problems) from base to head."""
    out = _run(["git", "diff", "--raw", "--no-renames", "-z", base, head]).stdout
    tokens = out.split("\0")
    files, deleted, problems = [], [], []
    i = 0
    while i + 1 < len(tokens):
        meta, path = tokens[i], tokens[i + 1]
        i += 2
        if not meta.startswith(":"):
            continue
        _old_mode, new_mode, _a, _b, status = meta[1:].split(" ")
        if status.startswith("D"):
            deleted.append(path)
            continue
        if new_mode != "100644":
            problems.append(f"{path}: file mode {new_mode} (only plain files)")
        files.append(path)
    return files, deleted, problems


def _pr_view(n: int) -> dict:
    return json.loads(_run(["gh", "pr", "view", str(n), "--repo", REPO,
                            "--json", PR_FIELDS]).stdout)


def _pr_checks(n: int) -> tuple[list[dict], str]:
    proc = _run(["gh", "pr", "checks", str(n), "--repo", REPO,
                 "--json", "name,bucket"], check_rc=False)
    try:
        return json.loads(proc.stdout or "[]"), proc.stderr.strip()
    except ValueError:
        return [], (proc.stderr or proc.stdout).strip()


def check_checks(checks: list[dict], err: str) -> list[str]:
    if not checks:
        return [f"no CI checks reported{': ' + err[:120] if err else ''}"]
    problems = []
    if any(c.get("bucket") == "pending" for c in checks):
        problems.append("checks pending")
    for c in checks:
        if c.get("bucket") not in ("pass", "skipping", "pending"):
            problems.append(f"check `{c.get('name')}`: {c.get('bucket')}")
    return problems


def check_pr_meta(pr: dict) -> list[str]:
    problems = []
    if pr.get("state") != "OPEN":
        problems.append(f"PR is {str(pr.get('state')).lower()}, not open")
    if pr.get("isDraft"):
        problems.append("PR is a draft")
    if pr.get("isCrossRepository"):
        problems.append("PR comes from a fork")
    if pr.get("baseRefName") != "main":
        problems.append(f"PR base is `{pr.get('baseRefName')}`, not main")
    if pr.get("mergeable") != "MERGEABLE":
        problems.append(f"PR mergeable state is {pr.get('mergeable')}")
    return problems


def run_guard(n: int, wait_s: int = 0) -> tuple[list[str], str]:
    deadline = time.monotonic() + wait_s
    while True:
        checks, err = _pr_checks(n)
        cp = check_checks(checks, err)
        pending = any("pending" in p or p.startswith("no CI checks") for p in cp)
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(30)
    pr = _pr_view(n)
    problems = check_pr_meta(pr) + cp
    sha = pr.get("headRefOid") or ""
    _run(["git", "fetch", "-q", "origin", "+refs/heads/main:refs/remotes/origin/main"])
    _run(["git", "fetch", "-q", "origin", f"refs/pull/{n}/head"])
    fetched = _run(["git", "rev-parse", "FETCH_HEAD"]).stdout.strip()
    if fetched != sha:
        return problems + [f"PR head moved while checking ({sha[:12]} vs {fetched[:12]})"], sha
    base = _run(["git", "merge-base", "origin/main", sha]).stdout.strip()
    files, deleted, mode_problems = pr_diff(base, sha)
    _, read = git_tree_reader(sha, ["recipes", "taxonomy"])
    problems += mode_problems
    problems += check(files, read, deleted=deleted, corpus=corpus_from_git("origin/main"))
    return problems, sha


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pr", type=int)
    ap.add_argument("--wait", type=int, default=0,
                    help="seconds to wait for pending CI checks (polled every 30s)")
    args = ap.parse_args(argv)
    try:
        problems, sha = run_guard(args.pr, max(0, args.wait))
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        detail = getattr(e, "stderr", "") or str(e)
        print(f"guard could not run: {str(detail).strip()[:300]}")
        return 1
    if problems:
        for p in problems:
            print(p)
        return 1
    print(f"ok {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
