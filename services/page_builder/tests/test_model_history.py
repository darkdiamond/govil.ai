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
    monkeypatch.setattr(rf, "MODEL_HISTORY_MAX_VALUE_BYTES", 50)
    m = {"kpis": {"a": {"value": 1}}, "tables": {"t": [1, 2]},
         "charts": {"small": [1, 2], "big": list(range(100))}, "labels": "x",
         "points": list(range(100))}
    h = rf.history_model(m)
    assert "tables" not in h and h["labels"] == "x"
    assert h["charts"]["small"] == [1, 2]
    assert set(h["charts"]["big"]) == {"__omitted_bytes__"}
    assert set(h["points"]) == {"__omitted_bytes__"}  # top-level values are capped too
