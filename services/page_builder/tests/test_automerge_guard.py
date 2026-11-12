"""The authoring routine merges its own PR only when automerge_guard passes.

Fixture strings for each check (pass and fail), plus checks over every
recipe on main: the guard must accept what humans already merged, and its
constants must stay honest about what recipes use.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from services.page_builder import automerge_guard as g

ROOT = Path(__file__).resolve().parents[3]
UID = "0a03a2a8-a146-4711-9bd8-63f44a8d1975"
UID2 = "11111111-2222-3333-4444-555555555555"
BASE = f"recipes/{UID}/"

RECIPE = {
    "contract_version": 1,
    "dataset_id": UID,
    "recipe_version": 1,
    "authored_at": "2026-11-12T00:00:00Z",
    "authored_against": {"metadata_modified": "x", "rows": {"main": 10}},
    "inputs": [{"name": "main", "by_id": "r", "required_columns": ["a"]}],
    "min_insights": 3,
    "lint_allow_numbers": [],
}
COMPUTE = '''\
import math
import re
from collections import Counter

import numpy as np
import pandas as pd
from govlib import fmt, frame


def compute(frames):
    df = frames["main"]
    n = len(df)
    s = df.groupby("a").size().to_dict()
    tbl = df.to_csv(index=False)
    x = df.query("a != ''")
    d = {}
    d.__setitem__("k", 1)
    return {"n": fmt.int_he(n), "s": s, "t": tbl, "m": math.pi,
            "seo": {"title": "t", "description": "d"}}
'''
TEMPLATE = (
    '<div>{{ model.n }}</div><a href="https://www.gov.il/he/x">gov</a>'
    '<script>L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png")</script>'
)


def _govlib() -> dict[str, set[str]]:
    d = ROOT / g.GOVLIB_DIR
    return {p.stem: g.module_names(p.read_text()) for p in d.glob("*.py") if p.stem != "__init__"}


def _usage() -> tuple[set[str], set[str]]:
    """Module attributes and from-imports of the merged recipes (as on main)."""
    attrs: set[str] = set()
    froms: set[str] = set()
    for p in (ROOT / "recipes").glob("*/compute.py"):
        a, f = g.module_usage(ast.parse(p.read_text(encoding="utf-8")))
        attrs |= a
        froms |= f
    return attrs, froms


@pytest.fixture(scope="module")
def corpus() -> g.MainCorpus:
    attrs, froms = _usage()
    return g.MainCorpus(
        module_attrs=attrs,
        from_names=froms,
        recipe_keys=g.json_key_paths(RECIPE) | {"inputs[].snapshot", "limits",
                                                "limits.max_records"},
        source_keys={"provider", "config", "config.resources", "config.resources[].id"},
        seo_keys={"title", "description", "name", "alternate_names"},
        govlib=_govlib(),
        provider_ids={"cbs-wages"},
        recipe_ids={UID, "cbs-wages"},
    )


def _pr(files: dict[str, str], corpus, deleted=()) -> list[str]:
    return g.check(list(files), lambda p: files[p], deleted=deleted, corpus=corpus)


def _recipe_files(**over) -> dict[str, str]:
    files = {
        BASE + "recipe.json": json.dumps(RECIPE),
        BASE + "compute.py": COMPUTE,
        BASE + "template.html.j2": TEMPLATE,
        BASE + "coverage.json": "{}",
    }
    files.update(over)
    return files


def _compute(src: str, corpus) -> list[str]:
    return g.check_compute(BASE + "compute.py", src, corpus)


# --- the whole PR: paths, deletions, ids ------------------------------------

def test_clean_recipe_pr_passes(corpus):
    files = _recipe_files()
    files[g.TAGS_FILE] = "{}"
    assert _pr(files, corpus) == []


def test_empty_pr_is_a_problem(corpus):
    assert _pr({}, corpus)


@pytest.mark.parametrize("path", [
    "services/page_builder/refresh.py", "frontend/pages/x.vue", "infra/x.sh",
    ".github/workflows/ci.yml", "NOTES.md", ".claude/skills/x/SKILL.md",
    "taxonomy/tags.json", "recipes/README.md", f"recipes/{UID}/sub/compute.py",
    f"recipes/{UID}/notes.md", f"recipes/{UID}/extract.csv", "recipes/not-an-id/recipe.json",
    "recipes/osm-roads/recipe.json",
])
def test_path_outside_the_recipe_files_is_a_problem(corpus, path):
    files = _recipe_files()
    files[path] = "{}"
    probs = _pr(files, corpus)
    assert any(p.startswith(path) for p in probs), probs


def test_deleting_another_recipe_is_a_problem(corpus):
    probs = _pr(_recipe_files(), corpus, deleted=[f"recipes/{UID2}/compute.py"])
    assert any("deleted outside" in p for p in probs), probs


def test_deleting_the_tags_file_is_a_problem(corpus):
    assert any("deleted outside" in p
               for p in _pr(_recipe_files(), corpus, deleted=[g.TAGS_FILE]))


def test_deleting_inside_a_changed_recipe_dir_is_fine(corpus):
    assert _pr(_recipe_files(), corpus, deleted=[BASE + "old.geojson"]) == []


def test_rename_out_of_a_recipe_dir_is_a_problem(corpus):
    # A rename is delete old + add new: the new path is outside recipes/.
    files = {"services/x.py": COMPUTE}
    probs = _pr(files, corpus, deleted=[BASE + "compute.py"])
    assert len(probs) >= 2, probs


def test_new_provider_recipe_is_a_problem(corpus):
    rid = "boi-new-thing"
    rec = dict(RECIPE, dataset_id=rid)
    files = {f"recipes/{rid}/recipe.json": json.dumps(rec),
             f"recipes/{rid}/source.json": json.dumps({"provider": "boi_sdmx"})}
    assert any("provider recipe" in p for p in _pr(files, corpus))


def test_existing_provider_recipe_fix_is_fine(corpus):
    rid = "cbs-wages"
    files = {f"recipes/{rid}/recipe.json": json.dumps(dict(RECIPE, dataset_id=rid)),
             f"recipes/{rid}/source.json": json.dumps({"provider": "cbs"})}
    assert _pr(files, corpus) == []


def test_uuid_recipe_adding_source_json_is_a_problem(corpus):
    files = _recipe_files(**{BASE + "source.json": json.dumps({"provider": "x"})})
    assert any("can't add source.json" in p for p in _pr(files, corpus))


def test_dataset_id_must_match_dir(corpus):
    files = _recipe_files(**{BASE + "recipe.json": json.dumps(dict(RECIPE, dataset_id=UID2))})
    assert any("dataset_id" in p for p in _pr(files, corpus))


def test_missing_recipe_json_is_a_problem(corpus):
    files = {BASE + "compute.py": COMPUTE}
    assert any("unreadable" in p for p in _pr(files, corpus))


def test_geojson_must_be_a_declared_snapshot(corpus):
    files = _recipe_files(**{BASE + "geo.geojson": "{}"})
    assert any("snapshot" in p for p in _pr(files, corpus))
    rec = dict(RECIPE, inputs=[dict(RECIPE["inputs"][0], snapshot="geo.geojson")])
    files[BASE + "recipe.json"] = json.dumps(rec)
    assert _pr(files, corpus) == []


# --- recipe.json / source.json keys ------------------------------------------

def test_new_recipe_json_field_needs_a_deploy(corpus):
    rec = dict(RECIPE, brand_new_field=1)
    probs = _pr(_recipe_files(**{BASE + "recipe.json": json.dumps(rec)}), corpus)
    assert any("brand_new_field" in p and "deploy" in p for p in probs), probs


def test_new_nested_recipe_json_field_needs_a_deploy(corpus):
    rec = dict(RECIPE, inputs=[dict(RECIPE["inputs"][0], fancy=True)])
    probs = _pr(_recipe_files(**{BASE + "recipe.json": json.dumps(rec)}), corpus)
    assert any("inputs[].fancy" in p for p in probs), probs


def test_authored_against_rows_keys_are_free_form(corpus):
    rec = dict(RECIPE, authored_against={"metadata_modified": "x",
                                         "rows": {"any_input_name": 3}})
    assert _pr(_recipe_files(**{BASE + "recipe.json": json.dumps(rec)}), corpus) == []


def test_new_source_json_field_needs_a_deploy(corpus):
    rid = "cbs-wages"
    files = {f"recipes/{rid}/recipe.json": json.dumps(dict(RECIPE, dataset_id=rid)),
             f"recipes/{rid}/source.json": json.dumps({"provider": "cbs", "newkey": 1})}
    assert any("newkey" in p for p in _pr(files, corpus))


def test_invalid_recipe_json_is_a_problem(corpus):
    assert _pr(_recipe_files(**{BASE + "recipe.json": "{"}), corpus)


# --- compute.py ----------------------------------------------------------------

def test_clean_compute_passes(corpus):
    assert _compute(COMPUTE, corpus) == []


def test_syntax_error_is_a_problem(corpus):
    assert any("does not parse" in p for p in _compute("def f(:\n", corpus))


@pytest.mark.parametrize("mod", sorted(g.FORBIDDEN_IMPORTS - {"__future__"}))
def test_forbidden_import(corpus, mod):
    assert _compute(f"import {mod}\n", corpus)
    assert _compute(f"from {mod} import x\n", corpus)


@pytest.mark.parametrize("src", [
    "import pandas.io.common\n",
    "import numpy.ctypeslib\n",
    "from pandas.io import common\n",
    "from pandas import read_csv\n",
    "from pandas import io\n",
    "from numpy import load\n",
    "from json import *\n",
    "from . import x\n",
    "import yaml\n",
])
def test_bad_import_forms(corpus, src):
    assert _compute(src, corpus), src


@pytest.mark.parametrize("name", sorted(g.BANNED_NAMES))
def test_banned_builtin_names(corpus, name):
    assert _compute(f"x = {name}\n", corpus)
    assert _compute(f"{name}('x')\n", corpus)


@pytest.mark.parametrize("src", [
    "f = open('x', 'w')\n", "f = open('x', 'a')\n", "f = open('x', 'x')\n",
    "f = open('x', 'r+')\n", "f = open('x', mode='wb')\n", "f = open('x', m)\n",
    "o = open\n",
])
def test_open_with_write_mode(corpus, src):
    assert _compute(src, corpus), src


@pytest.mark.parametrize("src", ["f = open('x')\n", "f = open('x', 'rb')\n",
                                 "f = open('x', mode='r')\n", "f = open\n"])
def test_open_is_banned_even_read_only(corpus, src):
    # inputs arrive as DataFrames; a read could reach /proc or the workdir
    assert _compute(src, corpus), src


@pytest.mark.parametrize("src", [
    "import calendar\ncalendar.sys.modules['os'].getcwd()\n",
    "import pandas as pd\npd.core.common.os.listdir('.')\n",
    "import json\njson.decoder.re._compile\n",
    "import statistics\nstatistics.random._os\n",
    "import datetime\nx = datetime.datetime._fromtimestamp\n",
    "import collections\ncollections.abc.sys\n",
])
def test_module_attribute_traversal_is_rejected(corpus, src):
    assert _compute(src, corpus), src


def test_a_column_named_like_a_module_is_fine(corpus):
    assert _compute("def compute(f):\n    return f['x'].code.tolist()\n", corpus) == []


@pytest.mark.parametrize("attr", ["__subclasses__", "__globals__", "__builtins__",
                                  "__code__", "__class__", "__mro__", "__dict__"])
def test_dunder_attributes(corpus, attr):
    assert _compute(f"y = x.{attr}\n", corpus)


def test_builtins_name_and_getattr_trick(corpus):
    assert _compute("y = __builtins__\n", corpus)
    assert _compute("y = getattr(__builtins__, 'ev' + 'al')\n", corpus)


@pytest.mark.parametrize("src", [
    "df = pd.read_csv('http://x')\n",
    "df = pd.read_json(u)\n",
    "a = np.genfromtxt(u)\n",
    "a = np.load(p)\n",
    "df.to_pickle('p')\n",
    "df.to_csv('out.csv')\n",
    "df.to_json(path_or_buf='x')\n",
    "x = pd.eval('1+1')\n",
    "x = df.eval('a+b')\n",
    "x = np.lib.npyio\n",
    "x = pd.io.common\n",
    "x = f(storage_options={'h': 'v'})\n",
    "x = df.query(q)\n",
    "x = df.query('a == @b')\n",
    "x = '{0.__class__.__globals__}'.format(df)\n",
])
def test_io_and_eval_bypasses(corpus, src):
    assert _compute(src, corpus), src


def test_string_writers_without_target_are_fine(corpus):
    assert _compute("s = df.to_csv(index=False)\nj = df.to_json(orient='records')\n",
                    corpus) == []


@pytest.mark.parametrize("src", [
    "from govlib import nope\n",
    "from govlib.fmt import nope\n",
    "import govlib.nope\n",
    "from govlib import fmt\nx = fmt.nope(1)\n",
    "from govlib import fmt as f\nx = f.nope(1)\n",
    "import govlib\nx = govlib.fmt.nope(1)\n",
    "import govlib\nx = govlib.nope\n",
])
def test_govlib_name_missing_on_main(corpus, src):
    probs = _compute(src, corpus)
    assert any(w in p for p in probs for w in ("deploy the helper first", "not on main",
                                                "submodule")), probs


@pytest.mark.parametrize("src", [
    "from govlib import fmt\nx = fmt.int_he(1)\n",
    "from govlib.fmt import int_he\n",
    "import govlib\nx = govlib.fmt.int_he(1)\n",
    "import govlib.fmt as f\nx = f.int_he(1)\n",
])
def test_govlib_existing_names_are_fine(corpus, src):
    assert _compute(src, corpus) == []


def test_new_seo_key_needs_a_deploy(corpus):
    probs = _compute("def compute(f):\n    return {'seo': {'title': 't', 'keywords': 'k'}}\n",
                     corpus)
    assert any("keywords" in p for p in probs), probs
    assert _compute("seo = {'og_image': 'x'}\n", corpus)


# --- template ------------------------------------------------------------------

def test_clean_template_passes():
    assert g.check_template("t", TEMPLATE) == []
    assert g.check_template("t", '<a href="https://www.boi.org.il/x">b</a>'
                                 '<a href="https://data.gov.il/dataset/x">d</a>'
                                 '<a href="https://www.cbs.gov.il/he">c</a>') == []


@pytest.mark.parametrize("src", [
    '<script src="https://cdn.example/x.js"></script>',
    '<SCRIPT type="text/javascript" SRC=/x.js></SCRIPT>',
    '<a href="https://evil.example/x">x</a>',
    '<img src="http://tracker.example/p.gif">',
    '<a href="https://gov.il@evil.example/">x</a>',
    '<a href="https://evilgov.il/">x</a>',
    '<a href="https://{{ model.host }}/x">x</a>',
    '<img src="//evil.example/p.gif">',
    '{{ "".__class__.__mro__ }}',
])
def test_bad_templates(src):
    assert g.check_template("t", src), src


# --- PR metadata and CI ------------------------------------------------------

def test_pr_meta():
    good = {"state": "OPEN", "isDraft": False, "isCrossRepository": False,
            "baseRefName": "main", "mergeable": "MERGEABLE"}
    assert g.check_pr_meta(good) == []
    for k, v in [("state", "MERGED"), ("isDraft", True), ("isCrossRepository", True),
                 ("baseRefName", "dev"), ("mergeable", "CONFLICTING"),
                 ("mergeable", "UNKNOWN")]:
        assert g.check_pr_meta(dict(good, **{k: v})), (k, v)


def test_checks():
    assert g.check_checks([{"name": "a", "bucket": "pass"},
                           {"name": "b", "bucket": "skipping"}], "") == []
    assert g.check_checks([{"name": "a", "bucket": "pending"}], "") == ["checks pending"]
    assert g.check_checks([{"name": "a", "bucket": "fail"}], "")
    assert g.check_checks([{"name": "a", "bucket": "cancel"}], "")
    assert g.check_checks([], "no checks reported")


def test_pr_diff_parses_raw_output(monkeypatch):
    raw = "\0".join([
        ":000000 100644 0000000 abc1234 A", BASE + "compute.py",
        ":100644 000000 abc1234 0000000 D", f"recipes/{UID2}/compute.py",
        ":000000 120000 0000000 abc1234 A", BASE + "template.html.j2",
        "",
    ])

    class P:
        stdout = raw

    monkeypatch.setattr(g, "_run", lambda *a, **k: P)
    files, deleted, problems = g.pr_diff("b", "h")
    assert files == [BASE + "compute.py", BASE + "template.html.j2"]
    assert deleted == [f"recipes/{UID2}/compute.py"]
    assert problems and "120000" in problems[0]


def test_cli_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(g, "run_guard", lambda n, w: ([], "abc"))
    assert g.main(["5"]) == 0
    assert capsys.readouterr().out.strip() == "ok abc"
    monkeypatch.setattr(g, "run_guard", lambda n, w: (["p1", "p2"], "abc"))
    assert g.main(["5"]) == 1
    assert capsys.readouterr().out.split() == ["p1", "p2"]


# --- against main --------------------------------------------------------------

def _main_recipe_files() -> list[str]:
    return sorted(str(p.relative_to(ROOT)) for p in (ROOT / "recipes").glob("*/*")
                  if p.is_file())


def test_every_recipe_on_main_passes():
    files = _main_recipe_files()
    govlib = [str(p.relative_to(ROOT)) for p in (ROOT / g.GOVLIB_DIR).glob("*.py")]

    def read(p: str) -> str:
        return (ROOT / p).read_text(encoding="utf-8")

    corpus = g.build_corpus(files + govlib, read)
    assert g.check(files, read, corpus=corpus) == []


def test_import_allowlist_matches_main():
    used: set[str] = set()
    for p in (ROOT / "recipes").glob("*/compute.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                used |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                used.add(node.module.split(".")[0])
    assert used <= g.ALLOWED_IMPORTS, used - g.ALLOWED_IMPORTS
    assert not (g.ALLOWED_IMPORTS & g.FORBIDDEN_IMPORTS)


def test_recipe_file_set_matches_main():
    for p in (ROOT / "recipes").glob("*/*"):
        if p.is_file():
            assert p.name in g.RECIPE_FILES or p.name.endswith(g.SNAPSHOT_SUFFIX), p


def test_govlib_submodules_match_main():
    mods = {f"govlib.{p.stem}" for p in (ROOT / g.GOVLIB_DIR).glob("*.py")
            if p.stem != "__init__"}
    assert mods == set(g.ALLOWED_SUBMODULES)


@pytest.mark.parametrize("src", [
    "import pandas as pd\nx = pd.compat.pickle_compat.loads(b'')\n",
    "import pandas as pd\nm = pd\nm.compat\n",
    "import pandas as pd\ndef f():\n    return pd\n",
    "import numpy as np\nnp.random.bit_generator.x\n",
    "from pandas import compat\n",
    "from pandas import DataFrame\n",
    "import pandas as pd\npd.core.frame.DataFrame\n",
    "def f(x):\n    match x:\n        case object(real=r):\n            return r\n",
    "import pandas as pd\npd.unpickle_thing\n",
    "import json\nj = json\n",
    "import json\ndef f(json=1):\n    return json\n",
    "import json\nx = [json for json in range(3)]\n",
    "import json\ntry:\n    pass\nexcept ValueError as json:\n    pass\n",
    "import pandas as pd\nc = pd.core\n",
    "import json\nimport math as json\n",
    "from collections import OrderedDict\n",
    "from govlib import fmt\nf = fmt\n",
    "from govlib import frame\nm = frame\nm.pd.core\n",
    "from govlib import geo\ndef f(geo):\n    return geo\n",
    "from govlib import geo\ndef f(x):\n    geo = x\n    return geo\n",
])
def test_module_walks_aliases_and_match_are_rejected(corpus, src):
    assert _compute(src, corpus), src


@pytest.mark.parametrize("src", [
    "import pandas as pd\nx = pd.Timestamp.max.year\n",
    "import numpy as np\ndef f(a, i, v):\n    np.add.at(a, i, v)\n",
    "import pandas as pd\nx = pd.offsets.MonthEnd(0)\n",
    "from collections import Counter\nc = Counter()\n",
    "def f(rows):\n    return [r.core for r in rows]\n",
])
def test_known_chains_and_local_shadows_are_fine(corpus, src):
    assert _compute(src, corpus) == [], src


@pytest.mark.parametrize("src", [
    "def f(df):\n    w = df.to_csv\n    w('/tmp/x')\n",
    "def f(df):\n    return [df.to_json][0]('/tmp/x')\n",
    "def f(df):\n    q = df.query\n    return q('a > 1')\n",
    "def f(df):\n    return df.agg('to_csv', '/tmp/x')\n",
    "def f(df):\n    return df.apply('eval')\n",
    "def f(df):\n    return df.agg({'a': 'read_csv'})\n",
])
def test_writer_refs_and_name_dispatch_are_rejected(corpus, src):
    assert _compute(src, corpus), src


@pytest.mark.parametrize("src", [
    "def f(df):\n    return df.to_string(index=False)\n",
    "def f(df):\n    return df.agg('sum'), {'k': 'to_date'}\n",
])
def test_direct_calls_and_plain_strings_are_fine(corpus, src):
    assert _compute(src, corpus) == [], src


@pytest.mark.parametrize("src", [
    "def f(df):\n    return df.to_csv(**{'path_or_buf': '/tmp/x'})\n",
    "def f(df, kw):\n    return df.to_json(**kw)\n",
    "def f(df, a):\n    return df.to_string(*a)\n",
    "def f(df):\n    return df.query('a > 1', **{'local_dict': {}})\n",
    "def f(df, g):\n    return g(**{'storage_options': {}})\n",
    "def f(df, g, k):\n    return g(**{k: 1})\n",
])
def test_star_args_cannot_hide_targets_or_kwargs(corpus, src):
    assert _compute(src, corpus), src


def test_named_aggregation_and_local_helpers_keep_working(corpus):
    src = ("def _pick(a, b):\n    return a\n"
           "def f(df, cols):\n"
           "    x = df.agg(**{c: ('v', 'sum') for c in cols})\n"
           "    return _pick(**{'a': 1, 'b': 2}), x\n")
    assert _compute(src, corpus) == []
