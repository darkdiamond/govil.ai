"""The local benchmark must run production's session path, not a lookalike."""
import json
from types import SimpleNamespace

import pytest

from services.page_builder import agent_runner, model_harness
from services.page_builder.agent_runner import ValidatedSession
from services.page_builder.cli.model_test import SnapshotStore, write_snapshot
from services.page_builder.schema import AgentData


def _validated():
    out = SimpleNamespace(
        usage={"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 0, "total_tokens": 3},
        cost={"total_usd": 0.01, "cost_source": "openrouter"},
        iterations=4,
        elapsed_seconds=1.5,
        providers=["Tencent"],
        tool_calls={"bash": 1},
        messages=[],
    )
    return ValidatedSession(
        out=out,
        content_html="<p>hi</p>",
        agent_data=AgentData(summary_he="ש", dataset_kind="registry"),
        attempts=2,
        attempts_cost=0.03,
        prefetch_stats={"files": 1},
        model="m/x",
        reasoning_effort="max",
    )


def test_benchmark_calls_the_production_session_function(monkeypatch, tmp_path):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return _validated()

    monkeypatch.setattr(agent_runner, "run_validated_session", fake)
    res = model_harness.run_test_session(
        dataset_id="d1", title="t", notes="n", org_title="o",
        primary_resource_id=None, out_dir=tmp_path, model="m/x", store="STORE",
        reasoning_effort="max",
    )
    assert seen["store"] == "STORE"
    assert seen["reasoning_effort"] == "max"
    assert res.attempts == 2
    assert (tmp_path / "content.html").read_text() == "<p>hi</p>"
    cost = json.loads((tmp_path / "cost.json").read_text())
    assert cost["attempts"] == 2 and cost["attempts_cost_usd"] == 0.03


def test_failed_session_raises_and_leaves_error_json(monkeypatch, tmp_path):
    def boom(**kw):
        raise RuntimeError("all 3 attempts failed")

    monkeypatch.setattr(agent_runner, "run_validated_session", boom)
    with pytest.raises(RuntimeError):
        model_harness.run_test_session(
            dataset_id="d1", title="t", notes="n", org_title="o",
            primary_resource_id=None, out_dir=tmp_path, model="m/x", store=None,
        )
    assert "all 3 attempts failed" in (tmp_path / "error.json").read_text()


def test_snapshot_round_trip_matches_what_the_store_returned(tmp_path):
    class Store:
        def get_source(self, did):
            return SimpleNamespace(
                id=did, title="T", notes="N", organization={"name": "org"},
                resources=[{"id": "r"}],
            )

        def list_org_sources(self, org, exclude_id=""):
            assert (org, exclude_id) == ("org", "d1")
            return [SimpleNamespace(id="x", title="X", tags=["a"])]

    path = tmp_path / "snap.json"
    write_snapshot(Store(), ["d1"], str(path))
    snap = SnapshotStore(str(path))
    src = snap.get_source("d1")
    assert (src.title, src.resources, src.organization) == ("T", [{"id": "r"}], {"name": "org"})
    assert snap.list_org_sources("org", exclude_id="d1")[0].tags == ["a"]
    assert snap.get_source("missing") is None


def test_success_clears_a_previous_runs_error_json(monkeypatch, tmp_path):
    (tmp_path / "error.json").write_text("{}")
    monkeypatch.setattr(agent_runner, "run_validated_session", lambda **kw: _validated())
    res = model_harness.run_test_session(
        dataset_id="d1", title="t", notes="n", org_title="o",
        primary_resource_id=None, out_dir=tmp_path, model="m/x", store=None,
    )
    assert not (tmp_path / "error.json").exists()
    assert res.wall_seconds is not None

