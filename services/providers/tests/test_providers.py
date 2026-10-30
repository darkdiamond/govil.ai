"""Provider contract, the BoI provider, and the source.json → sources/<id> sync.

HTTP is faked (no network); the store is an in-memory stand-in for the
FirestoreStateStore surface the sync uses.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.page_builder import refresh as rf
from services.providers import (
    ProviderError,
    ProviderSettings,
    SourceConfig,
    build_providers,
    provider_for_id,
)
from services.providers.base import normalize_csv
from services.providers.boi import BoiSdmxProvider
from services.providers.sync import sync_provider_sources

BR_CSV = (
    "﻿SERIES_CODE,FREQ,IR_FV_TYPE,UNIT_MEASURE,TIME_PERIOD,OBS_VALUE,RELEASE_STATUS\r\n"
    "MNT_RIB_BOI_D,D,RIB_BOI,PT,2026-10-29,3.25,YP\r\n"
    "MNT_SHIR_D,D,RIB_SHIR,PT,2026-10-28,3.25,YP\r\n"
    "MNT_RIB_BOI_D,D,RIB_BOI,PT,2026-10-28,3.5,YP\r\n"
)


class FakeResp:
    def __init__(self, status=200, body=b"", ctype="text/csv;charset=UTF-8"):
        self.status_code, self.content = status, body
        self.headers = {"content-type": ctype}

    def json(self):
        return json.loads(self.content)


NAMES = {"MNT_RIB_BOI_D": "ריבית בנק ישראל", "MNT_SHIR_D": "ריבית שי\"ר"}


def names_resp(names=NAMES):
    """BoI's SDMX-JSON answer, reduced to the series-name codelist."""
    body = {"data": {"structures": [{"dimensions": {"series": [
        {"id": "SERIES_CODE", "values": [{"id": k, "name": v} for k, v in names.items()]},
    ]}}]}}
    return FakeResp(200, json.dumps(body, ensure_ascii=False).encode(), "application/json")


@pytest.fixture
def boi(monkeypatch):
    """A BoI provider whose HTTP answers come from `p.answers[url-substring]`."""
    p = BoiSdmxProvider(BoiSdmxProvider.default_settings.model_copy(
        update={"enabled": True, "min_interval_s": 0.0, "retries": 0}))
    p.answers = {}
    p.calls = []

    def fake_get(url, **kw):
        p.calls.append(url)
        if "format=sdmx-json" in url and "names" in p.answers:
            return p.answers["names"]
        for frag, resp in p.answers.items():
            if frag in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        return FakeResp(404, b"<html>", "text/html")

    monkeypatch.setattr("services.providers.base.httpx.get", fake_get)
    p.answers["EXR/1.0/RER_USD_ILS"] = FakeResp(200, b"SERIES_CODE,TIME_PERIOD,OBS_VALUE\nX,1,2\n")
    p.answers["names"] = names_resp()
    return p


def _source(**over) -> SourceConfig:
    d = {"provider": "boi_sdmx", "title": "ריבית בנק ישראל", "tags": ["ריבית"],
         "config": {"resources": [{"id": "boi-br", "name": "ריבית", "dataflow": "BR"}]}}
    d.update(over)
    return SourceConfig.model_validate(d)


# ── settings + registry ──────────────────────────────────────────────────


def test_settings_from_env_override_class_defaults():
    s = ProviderSettings.from_env(
        "boi_sdmx", BoiSdmxProvider.default_settings,
        {"PROVIDER_BOI_SDMX_ENABLED": "true", "PROVIDER_BOI_SDMX_TIMEOUT_S": "30"},
    )
    assert s.enabled is True and s.timeout_s == 30.0
    assert s.base_url == BoiSdmxProvider.default_settings.base_url


def test_providers_are_off_unless_enabled():
    assert build_providers({}) == {}
    on = build_providers({"PROVIDER_BOI_SDMX_ENABLED": "1"})
    assert list(on) == ["boi_sdmx"] and isinstance(on["boi_sdmx"], BoiSdmxProvider)


def test_id_prefix_claims_ids():
    assert provider_for_id("boi-interest-rate") is BoiSdmxProvider
    assert provider_for_id("11111111-2222-3333-4444-555555555555") is None


# ── config ───────────────────────────────────────────────────────────────


def test_parse_config_requires_the_provider_id_prefix(boi):
    with pytest.raises(ProviderError, match="must start with 'boi-'"):
        boi.parse_config("interest-rate", _source())
    assert boi.parse_config("boi-interest-rate", _source()).resources[0].dataflow == "BR"


@pytest.mark.parametrize("res", [
    {"id": "boi-br", "name": "x", "dataflow": "br"},                 # lowercase flow
    {"id": "boi-br", "name": "x", "dataflow": "BR", "key": "a b"},    # bad key
    {"id": "boi-br", "name": "x", "dataflow": "BR", "extra": 1},      # unknown field
])
def test_bad_dataset_config_is_rejected(boi, res):
    with pytest.raises(ValueError):
        boi.parse_config("boi-x", _source(config={"resources": [res]}))


def test_duplicate_resource_ids_are_rejected(boi):
    r = {"id": "boi-br", "name": "x", "dataflow": "BR"}
    with pytest.raises(ValueError, match="unique"):
        boi.parse_config("boi-x", _source(config={"resources": [r, r]}))


def test_facts_carry_org_license_and_csv_urls(boi):
    src = _source(config={"resources": [
        {"id": "boi-br", "name": "x", "dataflow": "BR", "key": "MNT_RIB_BOI_D",
         "startperiod": "2000-01"}]})
    f = boi.facts("boi-interest-rate", src, boi.parse_config("boi-interest-rate", src))
    assert f.organization["name"] == "bank-of-israel" and f.license_title
    assert f.resources[0].url == (
        "https://edge.boi.org.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/"
        "BR/1.0/MNT_RIB_BOI_D?format=csv&startperiod=2000-01"
    )
    assert boi.page_slug_suffix("boi-interest-rate") == "interest-rate"


# ── data ─────────────────────────────────────────────────────────────────


def test_normalize_csv_is_order_and_encoding_independent():
    a = normalize_csv(BR_CSV.encode(), ("SERIES_CODE", "TIME_PERIOD"))
    lines = BR_CSV.lstrip("﻿").splitlines()
    b = normalize_csv(("\n".join([lines[0]] + lines[1:][::-1]) + "\n").encode(),
                      ("SERIES_CODE", "TIME_PERIOD"))
    assert a == b
    assert a.decode().splitlines()[1] == "MNT_RIB_BOI_D,D,RIB_BOI,PT,2026-10-28,3.5,YP"


def _res(boi, **kw):
    src = _source(config={"resources": [{"id": "boi-br", "name": "x", "dataflow": "BR", **kw}]})
    return boi.facts("boi-x", src, boi.parse_config("boi-x", src)).resources[0].model_dump()


def test_preview_and_fetch_share_one_download(boi, tmp_path):
    boi.answers["/BR/1.0/"] = FakeResp(200, BR_CSV.encode())
    res = _res(boi)
    preview_fn, fetch_fn = boi.fetch_fns([res])
    pv = preview_fn("boi-br")
    assert pv["total"] == 3 and pv["fields"][0]["id"] == "SERIES_CODE"
    out = fetch_fn("boi-br", 3, tmp_path / "x.csv", max_bytes=10**6, page_size=1,
                   page_timeout_s=1, deadline=0, sample_target_rows=0, prefer_sample=False)
    assert out.mode == "full" and out.rows == 3
    assert (tmp_path / "x.csv").read_bytes() == boi.csv_bytes(res)
    assert sum("/BR/" in c and "format=csv" in c for c in boi.calls) == 1
    assert preview_fn("unknown") is None


def test_fetch_over_byte_cap_fails(boi, tmp_path):
    boi.answers["/BR/1.0/"] = FakeResp(200, BR_CSV.encode())
    _, fetch_fn = boi.fetch_fns([_res(boi)])
    assert fetch_fn("boi-br", 3, tmp_path / "x.csv", max_bytes=10) is None


@pytest.mark.parametrize("resp", [
    FakeResp(404, b"<html>", "text/html"),
    FakeResp(200, b"<html>", "text/html"),   # an HTML error page with 200
])
def test_bad_answers_are_provider_errors(boi, resp):
    boi.answers["/BR/1.0/"] = resp
    with pytest.raises(ProviderError):
        boi.csv_bytes(_res(boi))


def test_server_errors_are_retried(boi, monkeypatch):
    boi.settings = boi.settings.model_copy(update={"retries": 1})
    monkeypatch.setattr("services.providers.base.time.sleep", lambda s: None)
    seq = [FakeResp(503, b"", "text/html"), FakeResp(200, BR_CSV.encode()), names_resp()]
    monkeypatch.setattr("services.providers.base.httpx.get", lambda url, **kw: seq.pop(0))
    assert boi.version(_res(boi)).rows == 3


# ── liveness ─────────────────────────────────────────────────────────────


def test_probe_available(boi):
    res = _res(boi)
    boi.answers["/BR/1.0/"] = FakeResp(200, BR_CSV.encode())
    assert boi.probe_available([res]) == "alive"
    boi.answers["/BR/1.0/"] = FakeResp(404, b"<html>", "text/html")
    assert boi.probe_available([res]) == "gone"
    boi.answers["/BR/1.0/"] = FakeResp(500, b"", "text/html")
    assert boi.probe_available([res]) == "unknown"


def test_a_404_is_not_gone_while_the_service_is_down(boi):
    boi.answers.clear()  # health series 404s too: an outage, not a removal
    assert boi.probe_available([_res(boi)]) == "unknown"


# ── sync ─────────────────────────────────────────────────────────────────


class FakeStore:
    """The save_provider_source contract, in memory (mirrors firestore.py)."""

    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.clock = datetime(2026, 10, 29, tzinfo=timezone.utc)

    def save_provider_source(self, dataset_id, payload):
        old = self.docs.get(dataset_id)
        hashes = lambda rs: {r["id"]: r["hash"] for r in rs or []}  # noqa: E731
        changed = old is None or hashes(old["resources"]) != hashes(payload["resources"])
        doc = dict(old or {"analysis_status": "never"})
        doc.update(payload, metadata_modified=self.clock if changed else old["metadata_modified"])
        self.docs[dataset_id] = doc
        return changed


def _repo(tmp_path, sources: dict[str, dict]):
    for i, s in sources.items():
        d = tmp_path / i
        d.mkdir()
        (d / "recipe.json").write_text("{}")
        (d / "source.json").write_text(json.dumps(s, ensure_ascii=False))
    (tmp_path / "11111111-ckan").mkdir()
    (tmp_path / "11111111-ckan" / "recipe.json").write_text("{}")
    return rf.LocalRecipeRepo(tmp_path)


def test_sync_creates_then_only_bumps_on_new_content(boi, tmp_path):
    boi.answers["/BR/1.0/"] = FakeResp(200, BR_CSV.encode())
    repo = _repo(tmp_path, {"boi-interest-rate": _source().model_dump()})
    assert repo.provider_source_ids() == ["boi-interest-rate"]
    store = FakeStore()
    s = sync_provider_sources(store, repo, providers={"boi_sdmx": boi})
    assert s["changed"] == ["boi-interest-rate"] and not s["failed"]
    doc = store.docs["boi-interest-rate"]
    assert doc["provider"] == "boi_sdmx" and doc["record_count"] == 3
    assert doc["resources"][0]["datastore_active"] is False and doc["resources"][0]["hash"]
    assert doc["presentation"]["explorer"] is False
    assert doc["page_slug_suffix"] == "interest-rate"
    first = doc["metadata_modified"]

    boi.clear_cache()
    store.clock = datetime(2026, 10, 30, tzinfo=timezone.utc)
    s = sync_provider_sources(store, repo, providers={"boi_sdmx": boi})
    assert s["changed"] == [] and store.docs["boi-interest-rate"]["metadata_modified"] == first

    boi.clear_cache()
    boi.answers["/BR/1.0/"] = FakeResp(200, (BR_CSV + "MNT_SHIR_D,D,RIB_SHIR,PT,2026-10-29,3.25,YP\n").encode())
    s = sync_provider_sources(store, repo, providers={"boi_sdmx": boi})
    assert s["changed"] == ["boi-interest-rate"]
    assert store.docs["boi-interest-rate"]["metadata_modified"] == store.clock


def test_sync_failures_leave_the_doc_and_the_run_alone(boi, tmp_path):
    repo = _repo(tmp_path, {
        "boi-a": _source().model_dump(),
        "boi-bad": {"provider": "boi_sdmx", "title": ""},          # invalid
        "boi-off": _source(provider="cbs_api").model_dump(),       # not enabled
        "wrong-prefix": _source().model_dump(),
    })
    store = FakeStore()
    s = sync_provider_sources(store, repo, providers={"boi_sdmx": boi})  # BR answers 404
    reasons = {f["id"]: f["reason"] for f in s["failed"]}
    assert reasons == {"boi-a": "provider_error", "boi-bad": "invalid_config",
                       "wrong-prefix": "provider_error"}
    assert s["skipped"] == [{"id": "boi-off", "reason": "provider_disabled:cbs_api"}]
    assert store.docs == {}


def test_sync_skips_an_unhealthy_provider(boi, tmp_path):
    boi.answers.clear()
    repo = _repo(tmp_path, {"boi-a": _source().model_dump()})
    s = sync_provider_sources(FakeStore(), repo, providers={"boi_sdmx": boi})
    assert s["skipped"] == [{"id": "boi-a", "reason": "provider_unhealthy:boi_sdmx"}]


def test_sync_with_nothing_enabled_reads_nothing():
    class Boom:
        def provider_source_ids(self):
            raise AssertionError("must not read the repo")
    assert sync_provider_sources(FakeStore(), Boom(), providers={})["synced"] == []


# ── refresh + reconcile + selector dispatch ──────────────────────────────


def test_refresh_of_a_provider_doc_never_calls_ckan(boi, monkeypatch, tmp_path):
    from services.page_builder.recipe import RecipeError

    def ckan(*a, **k):
        raise AssertionError("CKAN must not be called for a provider source")

    monkeypatch.setattr(rf, "fetch_resource_preview", ckan)
    monkeypatch.setattr(rf, "fetch_resource_records_to_file", ckan)
    monkeypatch.setattr(rf, "probe_inputs",
                        lambda recipe, resources, preview_fn: (_ for _ in ()).throw(
                            RecipeError("stop", reason="schema_changed")))
    seen = {}

    def build_page(recipe, resources, work_root, *, probe=None, after_fetch=None, **kw):
        seen.update(kw, resources=resources)
        raise RecipeError("stop here", reason="fetch_failed")

    monkeypatch.setattr(rf, "build_page", build_page)
    res = _res(boi)
    src = SimpleNamespace(id="boi-x", provider="boi_sdmx", resources=[res],
                          metadata_modified=None, title="x")
    store = SimpleNamespace(mark_refresh_failed=lambda *a, **k: None)
    recipe = SimpleNamespace(manifest=SimpleNamespace(recipe_version=1))
    out = rf.refresh_one(src, recipe, store=store, preview=True, staging_bucket="b",
                         work_root=tmp_path, trigger="never_refreshed", notify=False,
                         providers={"boi_sdmx": boi})
    assert out.reason == "fetch_failed"
    assert seen["resources"][0]["datastore_active"] is True
    assert seen["preview_fn"].__qualname__.endswith("preview_fn")


def test_refresh_skips_a_doc_whose_provider_is_disabled(tmp_path):
    src = SimpleNamespace(id="boi-x", provider="boi_sdmx", resources=[])
    recipe = SimpleNamespace(manifest=SimpleNamespace(recipe_version=1))
    out = rf.refresh_one(src, recipe, store=None, preview=True, staging_bucket="b",
                         work_root=tmp_path, trigger="never_refreshed", providers={})
    assert (out.status, out.reason) == ("skipped", "provider_disabled:boi_sdmx")


def test_reconcile_asks_the_provider_not_ckan(boi):
    import asyncio

    from services.page_builder.reconcile import probe_one

    class NoCkan:
        async def probe_resource(self, rid):
            raise AssertionError("CKAN probed for a provider source")
        probe_package = probe_resource

    boi.answers["/BR/1.0/"] = FakeResp(404, b"<html>", "text/html")
    src = SimpleNamespace(id="boi-x", provider="boi_sdmx", resources=[_res(boi)])
    assert asyncio.run(probe_one(NoCkan(), src, {"boi_sdmx": boi})) == "gone"
    assert asyncio.run(probe_one(NoCkan(), src, {})) == "unknown"


def test_publisher_carries_the_credit_block_and_readable_slug():
    from services.page_builder.publish import (
        _build_page_slugs,
        dataset_meta_from_source,
    )
    from services.shared.firestore import SourceRecord

    boi = BoiSdmxProvider(BoiSdmxProvider.default_settings)
    src = SourceRecord(
        id="boi-interest-rate", title="ריבית בנק ישראל", slug="ribit",
        organization=dict(BoiSdmxProvider.ORGANIZATION), provider="boi_sdmx",
        source_url="https://www.boi.org.il/x", presentation=boi.presentation().model_dump(),
        page_slug_suffix="interest-rate",
        resources=[{"id": "boi-br", "name": "x", "format": "CSV", "url": "https://e/x.csv",
                    "datastore_active": False}],
    )
    meta = dataset_meta_from_source(src)
    assert meta.source.source_name_he == "בנק ישראל" and meta.source.explorer is False
    assert meta.source.source_url == "https://www.boi.org.il/x"
    ckan = SourceRecord(id="0b3e1f2a-1111-2222-3333-444444444444", title="רישיונות עסק", slug="r")
    slugs = _build_page_slugs({m.id: m for m in (meta, dataset_meta_from_source(ckan))})
    assert slugs["boi-interest-rate"] == "ריבית-בנק-ישראל-interest-rate"
    assert slugs[ckan.id] == "רישיונות-עסק-0b3e1f2a"
    assert dataset_meta_from_source(ckan).source is None


def test_selector_never_queues_a_provider_doc():
    from services.page_builder import selector

    doc = SimpleNamespace(id="boi-x", provider="boi_sdmx", authoring_status=None,
                          analysis_status="never", page_path=None,
                          metadata_modified=datetime(2026, 10, 29, tzinfo=timezone.utc))
    store = SimpleNamespace(list_never_analyzed=lambda limit: [doc],
                            list_failed_retryable=lambda limit, max_attempts: [],
                            iter_changed_sources=lambda: iter([]))
    assert selector.pick_authoring_candidates(store, 10) == []


def test_download_adds_boi_hebrew_series_names(boi):
    boi.answers["/BR/1.0/"] = FakeResp(200, BR_CSV.encode())
    lines = boi.csv_bytes(_res(boi)).decode().splitlines()
    assert lines[0].startswith("SERIES_CODE,SERIES_NAME_HE,FREQ")
    assert lines[1].startswith("MNT_RIB_BOI_D,ריבית בנק ישראל,D")
    assert any(ln.startswith('MNT_SHIR_D,"ריבית שי""ר",D') for ln in lines)


def test_unreadable_series_names_fail_the_download(boi):
    boi.answers["/BR/1.0/"] = FakeResp(200, BR_CSV.encode())
    boi.answers["names"] = FakeResp(200, b"{}", "application/json")
    with pytest.raises(ProviderError, match="series names"):
        boi.csv_bytes(_res(boi))


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://www.boi.org.il/",
                                 "data:text/html,x", 'https://x/"onmouseover=1'])
def test_source_url_must_be_plain_https(url):
    with pytest.raises(ValueError):
        _source(source_url=url)
    assert _source(source_url="https://www.boi.org.il/roles/").source_url


def test_an_unexpected_error_fails_one_dataset_not_the_sync(boi, tmp_path, monkeypatch):
    boi.answers["/BR/1.0/"] = FakeResp(200, BR_CSV.encode())
    repo = _repo(tmp_path, {"boi-a": _source().model_dump(), "boi-b": _source().model_dump()})
    real = boi.version
    calls = []

    def flaky(res):
        calls.append(res["id"])
        if len(calls) == 1:
            raise RuntimeError("boom")  # not a ProviderError/ValueError
        return real(res)

    monkeypatch.setattr(boi, "version", flaky)
    store = FakeStore()
    s = sync_provider_sources(store, repo, providers={"boi_sdmx": boi})
    assert [f["id"] for f in s["failed"]] == ["boi-a"] and s["synced"] == ["boi-b"]


def test_one_retired_series_does_not_make_a_dataset_gone(boi):
    a = _res(boi)
    b = {**a, "id": "boi-other", "url": a["url"] + "&x=1",
         "params": {**a["params"], "dataflow": "EXR"}}
    boi.answers["/BR/1.0/"] = FakeResp(200, BR_CSV.encode())
    boi.answers["/EXR/1.0/"] = FakeResp(404, b"<html>", "text/html")
    assert boi.probe_available([a, b]) == "unknown"
