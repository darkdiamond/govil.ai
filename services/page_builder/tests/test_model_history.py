"""Model history: every successful render keeps its page model in GCS
(models/<id>/<ts>.json.gz + latest.json.gz) for the news job. Best effort —
a failed history write never fails the render."""
# ruff: noqa: F811  — `env` is the shared pytest fixture, imported to reuse it
from __future__ import annotations

import gzip
import json

from services.page_builder import refresh as rf
from services.page_builder.tests.test_recipe_refresh import (  # noqa: F401  (fixture)
    DS,
    FIXTURES,
    FakeCkan,
    FakeStore,
    _rows,
    _run,
    _src,
    env,
)
from services.shared import model_history


def _history(env, prefix):
    keys = sorted(k for k in env.staged if k.startswith(f"{prefix}/{DS}/"))
    return keys, {k: json.loads(gzip.decompress(env.staged[k])) for k in keys}


def test_render_stages_model_history(env):
    _run(env, FakeStore(_src()), FakeCkan(_rows([2024, 2025])))
    keys, docs = _history(env, "models")
    assert f"models/{DS}/latest.json.gz" in keys and len(keys) == 2
    latest = docs[f"models/{DS}/latest.json.gz"]
    assert latest["dataset_id"] == DS and latest["rendered_at"]
    assert latest["recipe_version"] >= 1
    assert latest["metadata_modified"].startswith("2026-10-01")
    assert "kpis" in latest["model"] and "tables" not in latest["model"]
    ts_key = next(k for k in keys if not k.endswith("latest.json.gz"))
    assert docs[ts_key] == latest


def test_model_history_failure_never_fails_the_render(env):
    real = env.write_gcs

    def flaky(data, bucket, rel):
        if "/models/" in f"/{rel}":
            raise OSError("bucket down")
        return real(data, bucket, rel)

    store = FakeStore(_src())
    ckan = FakeCkan(_rows([2024, 2025]))
    s = rf.run_refresh(
        store, rf.LocalRecipeRepo(FIXTURES), staging_bucket="bkt",
        work_root=env.tmp / "work", write_gcs=flaky, read_gcs=env.read_gcs,
        preview_fn=ckan.preview, fetch_fn=ckan.fetch,
    )
    assert s["refreshed"] == [DS]
    assert store.states[DS]["refresh_status"] == "succeeded"
    assert f"datasets/{DS}/content.html" in env.staged


def test_no_render_writes_no_history(env):
    store = FakeStore(_src())
    ckan = FakeCkan(_rows([2024, 2025]))
    _run(env, store, ckan)
    before = _history(env, "models")[0]
    _run(env, store, ckan)  # up to date → nothing rendered
    assert _history(env, "models")[0] == before


def test_history_model_drops_tables_and_caps_outsized_values(monkeypatch):
    monkeypatch.setattr(model_history, "MAX_VALUE_BYTES", 50)
    m = {"kpis": {"a": {"value": 1}}, "tables": {"t": [1, 2]},
         "charts": {"small": [1, 2], "big": list(range(100))}, "labels": "x",
         "points": list(range(100))}
    h = model_history.history_model(m)
    assert "tables" not in h and h["labels"] == "x"
    assert h["charts"]["small"] == [1, 2]
    assert set(h["charts"]["big"]) == {"__omitted_bytes__"}
    assert set(h["points"]) == {"__omitted_bytes__"}  # top-level values are capped too


def test_history_written_by_the_refresh_reads_back_in_the_news_job(tmp_path):
    """Round trip across the two packages: `_stage_model_history` writes,
    `news.snapshots` (the only reader) finds the newest render and decodes it."""
    from datetime import UTC, datetime

    from services.news.snapshots import LocalSnapshots, latest_and_baseline

    def write_gcs(data, bucket, rel):
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return f"gs://{bucket}/{rel}"

    mm = datetime(2026, 10, 1, tzinfo=UTC)
    for day, total in ((1, 10), (2, 20)):
        assert rf._stage_model_history(
            DS, {"kpis": {"total": {"value": total}}, "tables": {"t": [1]}},
            bucket="bkt", write_gcs=write_gcs, recipe_version=3, metadata_modified=mm,
            now=datetime(2026, 11, day, 6, tzinfo=UTC))
    store = LocalSnapshots(tmp_path / model_history.PREFIX)
    assert store.ids() == [DS]
    names = store.names(DS)  # newest first; latest.json.gz is not a timestamped name
    assert [ts for ts, _ in names] == ["20261102T060000Z", "20261101T060000Z"]
    latest, base, fresh = latest_and_baseline(store, DS, None)
    assert fresh and latest.dataset_id == DS and latest.recipe_version == 3
    assert latest.rendered_at == "20261102T060000Z" and latest.data_as_of == mm.date()
    assert latest.model == {"kpis": {"total": {"value": 20}}}
    assert base.model == {"kpis": {"total": {"value": 10}}}
