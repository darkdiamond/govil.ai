"""The guards from TODO.md's News list (2026-11-13): Decimal SQL facts, the
table_schema cap, the brief's datasets only, the news load caps, calc rules,
an empty catalog, unread snapshots, critic scores, chart text, NAT64, the 4K
hero, and the stored ledger."""
from __future__ import annotations

import gc
import io
import json
import weakref
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from services.news import gates, run
from services.news.ledger import Ledger
from services.news.tests.test_ledger_gates import _draft as gate_draft
from services.news.tests.test_ledger_gates import _setup
from services.news.tests.test_safety import _StubQuery, _toolbox_with
from services.news.tests.test_window import CURSOR, _FakeArticles, _summary, live  # noqa: F401
from services.news.tools import SCHEMA_RESULT_CHARS, Toolbox, _is_num

# ── SQL results and the schema ──────────────────────────────────────────


@pytest.mark.parametrize("v, ok", [
    (Decimal("12.50"), True), (Decimal(-3), True), (Decimal("NaN"), False),
    (Decimal("sNaN"), False), (Decimal("Infinity"), False), (Decimal("1e400"), False),
    (10 ** 400, False), (True, False), (7, True), (float("nan"), False), ("7", False),
])
def test_is_num_takes_finite_decimals(v, ok):
    assert _is_num(v) is ok


def test_decimal_sql_cells_become_facts():
    tb = _toolbox_with(_StubQuery({"columns": ["total"], "rows": [[Decimal("1234.50")]],
                                   "truncated": False}))
    out = json.loads(tb.call("sql", {"dataset_id": "ds1", "query": "SELECT sum(x)::DECIMAL(10,2)"}))
    cell = out["rows"][0][0]
    assert cell["v"] == 1234.5 and tb.ledger.facts[cell["fact"]].value == 1234.5


def test_decimal_sql_with_duckdb():
    pytest.importorskip("duckdb")
    tb = Toolbox(ledger=Ledger(), series={}, models={}, catalog={},
                 tables=lambda ds: {"t": pd.DataFrame({"n": ["1.25", "2.5"]})})
    try:
        out = json.loads(tb.call("sql", {"dataset_id": "d", "query": "SELECT sum(n::DECIMAL(10,2)) AS s FROM t"}))
    finally:
        tb.close()
    assert out["rows"][0][0]["v"] == 3.75 and out["rows"][0][0]["fact"] == "f1"


def test_table_schema_is_capped_for_wide_tables():
    cols = [(f"column_with_a_long_name_{i}", "VARCHAR") for i in range(800)]
    q = _StubQuery({}, schema={"wide": cols, "other": [("a", "BIGINT")]}, sample=[tuple("x" * 50 for _ in cols)])
    raw = _toolbox_with(q).call("table_schema", {"dataset_id": "ds1"})
    out = json.loads(raw)
    assert len(raw) <= SCHEMA_RESULT_CHARS
    assert out["wide"]["sample"] == [] and 0 < len(out["wide"]["columns"]) < 800
    assert out["wide"]["more_columns"] == 800 - len(out["wide"]["columns"])
    assert "other" not in out and "1 more tables" in out["_note"]


def test_table_schema_small_tables_are_whole():
    q = _StubQuery({}, schema={"t": [("a", "BIGINT")]}, sample=[(1,), (2,)])
    out = json.loads(_toolbox_with(q).call("table_schema", {"dataset_id": "ds1"}))
    assert set(out) == {"t"} and len(out["t"]["sample"]) == 2


# ── the brief's datasets only, and shared tables ────────────────────────


def test_sql_and_schema_refuse_datasets_outside_the_brief():
    asked = []
    tb = Toolbox(ledger=Ledger(), series={}, models={}, catalog={}, dataset_ids=["mine"],
                 tables=lambda ds: asked.append(ds) or {})
    for tool in ("sql", "table_schema"):
        args = {"dataset_id": "someone-else"} | ({"query": "SELECT 1"} if tool == "sql" else {})
        err = json.loads(tb.call(tool, args))["error"]
        assert "not in this brief" in err and "mine" in err
    assert asked == []   # nothing was loaded


def test_a_shared_table_query_is_not_closed_by_the_toolbox():
    pytest.importorskip("duckdb")
    from services.news.query import TableQuery

    q = TableQuery({"t": pd.DataFrame({"n": ["1"]})})
    try:
        for _ in range(2):   # two stories of one run
            tb = Toolbox(ledger=Ledger(), series={}, models={}, catalog={}, tables=lambda ds: q,
                         dataset_ids=["d"])
            assert json.loads(tb.call("sql", {"dataset_id": "d", "query": "SELECT n FROM t"}))["rows"]
            tb.close()
    finally:
        q.close()


def test_table_query_consume_drops_the_frames():
    pytest.importorskip("duckdb")
    from services.news.query import TableQuery

    frames = {"a": pd.DataFrame({"n": ["1", "2"]}), "b": pd.DataFrame({"s": ["x"]})}
    q = TableQuery(frames, consume=True)
    try:
        assert frames == {}
        assert q.run("SELECT sum(n) FROM a")["rows"] == [[3]]
    finally:
        q.close()


class _Recipe:
    manifest = SimpleNamespace(inputs=[SimpleNamespace(name="main", snapshot=None, map=False, concat=False)])


def _tables(monkeypatch, tmp_path, *, preview_total=10, rows=10, size=100, **kw):
    """A DatasetTables over a fake store/repo/CKAN; returns (tables, seen)."""
    from services.news.data import DatasetTables
    from services.page_builder import recipe_exec, refresh
    from services.page_builder.refresh import FetchedInput

    seen: dict = {"fetched": 0}
    store = SimpleNamespace(get_source=lambda ds: SimpleNamespace(resources=[{"id": "r1"}], provider=None))
    repo = SimpleNamespace(load=lambda ds, path: _Recipe())
    monkeypatch.setattr(refresh, "probe_inputs", lambda recipe, resources, *a: SimpleNamespace(
        resolved={"main": [{"id": "r1"}]}, preview=lambda rid: {"total": preview_total}))

    def fetch(recipe, resources, dest, *, probe, **_kw):
        seen["fetched"] += 1
        seen["dest"] = dest
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / "main.csv"
        f.write_bytes(b"n\n" + b"1" * (size - 2))
        return {"main": [FetchedInput(f, "r1", "res", rows)]}

    def frames(spec):
        df = pd.DataFrame({"n": ["1", "2"]})
        seen["frame"] = weakref.ref(df)
        return {"main": df}

    monkeypatch.setattr(refresh, "fetch_inputs", fetch)
    monkeypatch.setattr(recipe_exec, "load_frames", frames)
    return DatasetTables(store, repo, work_root=tmp_path, **kw), seen


def test_dataset_tables_keep_duckdb_only_and_use_the_full_id(monkeypatch, tmp_path):
    pytest.importorskip("duckdb")
    ds = "0123abcd-ffff-eeee-dddd-ccccbbbbaaaa"
    t, seen = _tables(monkeypatch, tmp_path)
    try:
        q = t(ds)
        assert seen["dest"].parent.name == ds         # the whole id, not its first 8 characters
        assert not seen["dest"].parent.exists()       # the files are gone once loaded
        gc.collect()
        assert seen["frame"]() is None                # and so is the pandas frame
        assert q.run("SELECT sum(n) FROM main")["rows"] == [[3]]
        assert t(ds) is q and seen["fetched"] == 1    # one load per run
    finally:
        t.close()


@pytest.mark.parametrize("kw, fetched, needle", [
    ({"preview_total": 5_000, "max_rows": 1_000}, 0, "in the datastore"),   # refused before download
    ({"rows": 5_000, "max_rows": 1_000}, 1, "exported"),
    ({"size": 5_000, "max_bytes": 1_000}, 1, "NEWS_TABLE_MAX_BYTES"),
])
def test_dataset_tables_cap_news_loads(monkeypatch, tmp_path, kw, fetched, needle):
    from services.news.data import DataUnavailable

    t, seen = _tables(monkeypatch, tmp_path, **kw)
    try:
        with pytest.raises(DataUnavailable, match=needle):
            t("ds-1")
        assert seen["fetched"] == fetched and "frame" not in seen
    finally:
        t.close()


def test_dataset_tables_refuse_a_path_for_an_id_and_remember_failures(monkeypatch, tmp_path):
    from services.news.data import DataUnavailable

    victim = tmp_path / "keep"
    victim.mkdir()
    t, seen = _tables(monkeypatch, tmp_path, size=5_000, max_bytes=1_000)
    try:
        with pytest.raises(DataUnavailable, match="not a dataset id"):
            t("../keep")
        assert victim.exists() and seen["fetched"] == 0
        for _ in range(2):   # over the cap: fetched once, refused for every later story
            with pytest.raises(DataUnavailable, match="NEWS_TABLE_MAX_BYTES"):
                t("ds-1")
        assert seen["fetched"] == 1
    finally:
        t.close()


def test_dataset_tables_caps_come_from_env(monkeypatch, tmp_path):
    from services.news.data import DEFAULT_MAX_BYTES, DatasetTables

    monkeypatch.setenv("NEWS_TABLE_MAX_ROWS", "123")
    t = DatasetTables(work_root=tmp_path)
    assert t.max_rows == 123 and t.max_bytes == DEFAULT_MAX_BYTES
    t.close()


# ── calc ────────────────────────────────────────────────────────────────


def _ledger():
    led = Ledger()
    a = led.add(100, label="count A", provenance="sql:a", dataset_id="A")
    b = led.add(40, label="count A2", provenance="sql:b", dataset_id="A")
    pct = led.add(12.5, label="share", provenance="sql:c", unit="pct", dataset_id="A")
    other = led.add(30, label="count B", provenance="sql:d", dataset_id="B")
    return led, a, b, pct, other


@pytest.mark.parametrize("op", ["sum", "diff"])
def test_calc_refuses_mixed_units_and_datasets(op):
    led, a, b, pct, other = _ledger()
    assert led.calc(op, a.id, b.id).value in (140, 60)
    with pytest.raises(ValueError, match="different units"):
        led.calc(op, a.id, pct.id)
    with pytest.raises(ValueError, match="different datasets"):
        led.calc(op, a.id, other.id)


def test_calc_cross_dataset_ratio_still_works_and_b_is_required():
    led, a, _b, _pct, other = _ledger()
    assert led.calc("ratio", a.id, other.id).value == pytest.approx(100 / 30)
    with pytest.raises(ValueError, match="needs two facts"):
        led.calc("diff", a.id)


def test_calc_refusal_reaches_the_writer_as_an_error():
    led, a, _b, pct, _other = _ledger()
    tb = Toolbox(ledger=led, series={}, models={}, catalog={})
    assert "different units" in json.loads(tb.call("calc", {"op": "sum", "a": a.id, "b": pct.id}))["error"]


def test_calc_refuses_a_fact_with_itself():
    led, a, *_ = _ledger()
    for op in ("sum", "diff", "ratio", "pct_change", "share"):
        with pytest.raises(ValueError, match="with itself"):
            led.calc(op, a.id, a.id)


def test_a_self_reusing_calc_chain_describes_fast_and_small():
    import time

    led, a, b, *_ = _ledger()
    prev, cur = a.id, b.id
    for _ in range(30):   # each step reuses both previous results: 2^30 paths unmemoized
        nxt = led.calc("sum", cur, prev).id
        prev, cur = cur, nxt
    for _ in range(2):    # and a scale step that doubles back on its input
        s = led.calc("scale", cur, factor=0.001).id
        cur = led.calc("sum", cur, s).id
    t = time.monotonic()
    text = led.describe(cur)
    md = gates.as_markdown({"headline": "h", "dek": "d", "blocks": [], "charts": [], "sources": [],
                            "fact_ids": led.with_ancestors([cur])}, led)
    assert time.monotonic() - t < 1.0
    assert len(text) <= 1501 and len(md) < 20 * 1600
    assert len(led.with_ancestors([cur])) == len(led.facts) - 2   # pct and other are not ancestors


def test_the_critic_sees_how_derived_numbers_were_computed():
    led, a, b, _pct, _other = _ledger()
    d = led.calc("diff", a.id, b.id)
    pc = led.calc("pct_change", d.id, b.id)
    core = {"headline": "h", "dek": "d", "blocks": [], "charts": [], "sources": [],
            "fact_ids": led.with_ancestors([pc.id])}
    md = gates.as_markdown(core, led)
    assert f"{pc.id} = " in md and "pct_change of [" in md and "diff of [" in md and "count A2" in md
    assert "derived number" not in gates.as_markdown(core)   # no ledger, no list


# ── the stored ledger ───────────────────────────────────────────────────


def test_dump_keeps_printed_facts_and_their_calc_inputs():
    led, a, b, pct, _other = _ledger()
    d = led.calc("diff", a.id, b.id)
    s = led.calc("scale", d.id, factor=0.001)
    dump = led.dump(keep=[s.id, pct.id])
    assert {f["id"] for f in dump["facts"]} == {a.id, b.id, d.id, s.id, pct.id}
    assert dump["fact_count"] == len(led.facts) and len(led.dump()["facts"]) == len(led.facts)
    assert led.dump(keep=[])["facts"] == []


def test_gate_lists_the_facts_the_article_prints():
    series, led, cat, f1 = _setup()
    unused = led.add(5, label="unused", provenance="sql:x", dataset_id="boi-mortgage-rates")
    core, problems = gates.check(gate_draft(f1), ledger=led, series_by_ds=series, catalog=cat,
                                 vocab={"משכנתאות"})
    assert problems == [] and core["fact_ids"] == [f1.id] and unused.id not in core["fact_ids"]


def test_a_stored_article_carries_only_its_printed_facts(tmp_path):
    from services.news.tests.test_llm_pipeline import FakeLLM, _day, _draft

    out, _store, _sig = _day(tmp_path, FakeLLM([_draft()]))
    doc = json.loads((tmp_path / out["published"][0] / "article.json").read_text(encoding="utf-8"))
    assert [f["id"] for f in doc["ledger"]["facts"]] == ["f1"]
    assert doc["ledger"]["fact_count"] > 1   # the seeded signal facts were registered, not stored


# ── the run: catalog and snapshot reads ─────────────────────────────────


def test_live_run_with_an_empty_catalog_fails_and_keeps_the_cursor(live, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setattr(run.catalog_mod, "load_catalog", dict)
    args = [a for a in live if a != "--no-catalog"]
    assert run.main(args) == 1
    s = _summary(capsys)
    assert s["status"] == "failed" and "catalog" in s["error"]
    assert _FakeArticles.cursor == CURSOR


def test_dry_run_with_an_empty_catalog_goes_on(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(run.catalog_mod, "load_catalog", dict)
    monkeypatch.setattr(run, "GcsSnapshots", lambda *_a: run.LocalSnapshots(tmp_path))
    assert run.main(["--signals-only", "--since-hours", "24"]) == 0


class _Store:
    def __init__(self, bad: set[str], ids: list[str]):
        self.bad, self._ids = bad, ids

    def ids(self):
        return self._ids


def test_find_signals_counts_failed_snapshot_reads(monkeypatch):
    ids = [f"d{i}" for i in range(10)]
    st = _Store({"d1", "d2"}, ids)

    def history(store, ds, cutoff, upto=None):
        if ds in store.bad:
            raise OSError("gcs down")
        return run.History(None, None, False)

    monkeypatch.setattr(run, "history", history)
    _, stats = run.find_signals(st, today=__import__("datetime").date(2026, 11, 13), ids=ids)
    assert stats["snapshot_errors"] == 2 and stats["datasets"] == 10


@pytest.mark.parametrize("errors, datasets, held", [
    (0, 400, False), (1, 400, False), (4, 10, False), (5, 10, True), (19, 400, False), (20, 400, True),
    (400, 400, True),
])
def test_snapshot_error_threshold(errors, datasets, held):
    assert run.snapshot_reads_failed({"snapshot_errors": errors, "datasets": datasets}) is held


@pytest.mark.parametrize("errors, advanced", [(1, True), (50, False)])
def test_failed_snapshot_reads_hold_the_cursor(live, monkeypatch, capsys, errors, advanced):  # noqa: F811
    def find(*_a, context=None, **_k):
        context["series"], context["models"] = {}, {}
        return [], {"datasets": 100, "snapshot_errors": errors}

    monkeypatch.setattr(run, "find_signals", find)
    assert run.main(live) == 0
    s = _summary(capsys)
    assert s["cursor_advanced"] is advanced
    assert (_FakeArticles.cursor == CURSOR) is not advanced
    assert ("cursor_held" in s) is not advanced


# ── gates: critic scores, chart text ────────────────────────────────────


class _Critic:
    def __init__(self, reply):
        self.reply = reply

    def chat_json(self, messages, **kw):
        return self.reply


def test_a_huge_integer_score_is_revise_not_a_crash():
    huge = json.loads("9" * 400)
    scores = {k: 5 for k in gates.RUBRIC} | {"news": huge}
    core = {"headline": "h", "dek": "d", "blocks": [], "charts": [], "sources": []}
    v = gates.critique(_Critic({"verdict": "pass", "scores": scores, "issues": [], "fixes": []}), core)
    assert v["verdict"] == "revise"


def _chart_problems(**chart):
    series, led, cat, f1 = _setup()
    d = gate_draft(f1)
    d["charts"][0].update(chart)
    _, problems = gates.check(d, ledger=led, series_by_ds=series, catalog=cat, vocab={"משכנתאות"})
    return problems


def test_arabic_indic_digits_are_no_year_label():
    assert gates._chart_numbers_text("2045", "label") == ""
    assert gates._chart_numbers_text("20٤٥", "label") == "20٤٥"
    assert gates._chart_numbers_text("2024/25", "label") == ""
    assert gates._chart_numbers_text("2024/٢٥", "label") == "2024/٢٥"


@pytest.mark.parametrize("field, value, needle", [
    ("title", "היקף משכנתאות " * 10, "title: 139 characters (at most 90)"),
    ("unit", "מיליארדי שקלים חדשים " * 3, "unit:"),
    ("series", [{"dataset_id": "boi-mortgage-rates", "series_path": "volume.y", "name": "היקף " * 20}],
     "series 0 name: 100 characters"),
    ("title", "Monthly mortgage volume", "too little Hebrew"),
])
def test_chart_text_length_and_hebrew(field, value, needle):
    problems = _chart_problems(**{field: value})
    assert any(needle in p for p in problems), problems


def test_a_hebrew_chart_title_with_an_acronym_passes():
    assert _chart_problems(title="היקף משכנתאות חודשי (בנק ישראל, BOI)") == []


def test_bar_label_length_is_capped():
    series, led, cat, f1 = _setup()
    d = gate_draft(f1)
    d["charts"] = [{"id": "c1", "type": "bar", "title": "היקף משכנתאות", "unit": "מיליארדי ש\"ח",
                    "bars": [{"label": "תווית ארוכה " * 10, "fact": f1.id}]}]
    _, problems = gates.check(d, ledger=led, series_by_ds=series, catalog=cat, vocab={"משכנתאות"})
    assert any("bar 0 label: 120 characters" in p for p in problems), problems


# ── fetch and images ────────────────────────────────────────────────────


@pytest.mark.parametrize("addr", ["64:ff9b::a9fe:a9fe", "64:ff9b::808:808", "::a9fe:a9fe", "::808:808",
                                  "64:ff9b:1::1"])
def test_nat64_and_ipv4_compatible_addresses_are_refused(addr):
    from services.news.fetch import FetchRefused, _check_url
    from services.news.tests.test_safety import _infos

    with pytest.raises(FetchRefused):
        _check_url("https://www.gov.il/a", lambda host, port, proto=0: _infos(addr))


def test_a_public_ipv6_address_still_passes():
    from services.news.fetch import _check_url
    from services.news.tests.test_safety import _infos

    assert _check_url("https://www.gov.il/a", lambda h, p, proto=0: _infos("2606:4700::1111")) == "2606:4700::1111"


def test_hosts_off_the_allowlist_are_never_resolved():
    from services.news.fetch import FetchRefused, fetch_page

    asked = []
    with pytest.raises(FetchRefused, match="allowlist"):
        fetch_page("https://evil.example/a", client=object(), resolve=lambda *a, **k: asked.append(a) or [])
    assert asked == []


def _png(size) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (20, 90, 200)).save(buf, "PNG")
    return buf.getvalue()


class _ImageLLM:
    def __init__(self, raw):
        self.raw = raw

    def image(self, prompt):
        return self.raw


def test_a_4k_hero_is_accepted():
    from services.news import images

    meta, _ = images.hero(_ImageLLM(_png((5504, 3072))), "brief", [1.0, 2.0])
    assert meta["kind"] == "illustration"


def test_a_hero_side_past_the_cap_is_refused(monkeypatch):
    from services.news import images

    monkeypatch.setattr(images, "MAX_HERO_SIDE", 1199)
    meta, _ = images.hero(_ImageLLM(_png((1200, 700))), "brief", [1.0, 2.0])
    assert meta["kind"] == "chart"


def test_tool_log_arguments_are_capped():
    from services.news.tools import LOG_ARG_CHARS

    tb = Toolbox(ledger=Ledger(), series={}, models={}, catalog={})
    tb.call("sql", {"dataset_id": "d", "query": "x" * 50_000})
    assert len(tb.log[0]["args"]["query"]) == LOG_ARG_CHARS
