"""CBS Index API provider: paging, base chaining, the normalized CSV.

HTTP is faked through the `_send` seam (no network). fixtures/cbs_index/
cpi_pages.json is a real answer (2026-11-09) for CPI general (120010) from
07-2024, fetched with PageSize=10 as 3 pages: Jul–Dec 2024 are on the 2022
base, Jan 2025 on are on the 2024 base. The API calculator gives 1.074 as the
2022 → 2024 chaining coefficient.
"""
from __future__ import annotations

import copy
import csv
import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from services.providers import (
    ProviderError,
    SourceConfig,
    build_providers,
    provider_for_id,
)
from services.providers.cbs import CbsReleasesProvider
from services.providers.cbs_index import (
    CbsIndexDatasetConfig,
    CbsIndexProvider,
    _dated,
    _factors,
    _links,
    _num,
    rows_csv,
)
from services.providers.sync import sync_provider_sources
from services.providers.tests.sync_helpers import FakeStore, make_repo

FIX = Path(__file__).parent / "fixtures" / "cbs_index"
CPI_PAGES = json.loads((FIX / "cpi_pages.json").read_text(encoding="utf-8"))


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.content = json.dumps(body, ensure_ascii=False).encode()
        self.headers = {"content-type": "application/json"}

    def json(self):
        return json.loads(self.content)


def make_provider(pages_by_codes: dict[str, list[dict]] | None = None, calls=None):
    p = CbsIndexProvider.from_env({"PROVIDER_CBS_INDEX_ENABLED": "true",
                                   "PROVIDER_CBS_INDEX_MIN_INTERVAL_S": "0"})
    pages_by_codes = {"120010": CPI_PAGES} if pages_by_codes is None else pages_by_codes

    def send(url, **_kw):
        if calls is not None:
            calls.append(url)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        pages = pages_by_codes.get(q.get("id", ""))
        if u.path.endswith("/data/price"):
            if pages is None:
                return FakeResp(200, {"month": None, "quarter": None,
                                      "paging": {"total_items": 0, "last_page": 0}})
            if "last" in q:
                return FakeResp(200, pages[0])
            return FakeResp(200, pages[int(q.get("Page", "1")) - 1])
        return FakeResp(404, {"Message": "not found"})

    p._send = send
    return p


def rows(data: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"))))


def resource(p, **cfg):
    cfg = {"id": "cpi", "name": "מדד המחירים לצרכן", "codes": [120010], **cfg}
    src = SourceConfig(provider="cbs_index", title="מדד המחירים לצרכן",
                       config={"resources": [cfg]})
    parsed = p.parse_config("cbs-index-cpi", src)
    return p.facts("cbs-index-cpi", src, parsed).resources[0].model_dump()


# ── config ────────────────────────────────────────────────────────────────


def test_config_validation():
    ok = {"resources": [{"id": "cpi", "name": "x", "codes": [120010], "start": "01-1990"}]}
    assert CbsIndexDatasetConfig.model_validate(ok).resources[0].frequency == "both"
    bad = [
        {"resources": []},
        {"resources": [{"id": "cpi", "name": "x", "codes": []}]},
        {"resources": [{"id": "cpi", "name": "x", "codes": [1, 1]}]},
        {"resources": [{"id": "cpi", "name": "x", "codes": [1], "start": "1990-01"}]},
        {"resources": [{"id": "cpi", "name": "x", "codes": [1], "frequency": "year"}]},
        {"resources": [{"id": "a", "name": "x", "codes": [1]},
                       {"id": "a", "name": "y", "codes": [2]}]},
        {"resources": [{"id": "cpi", "name": "x", "codes": [1], "extra": 1}]},
    ]
    for cfg in bad:
        with pytest.raises(ValueError):
            CbsIndexDatasetConfig.model_validate(cfg)


def test_registry_and_longest_prefix():
    assert "cbs_index" not in build_providers({})
    assert "cbs_index" in build_providers({"PROVIDER_CBS_INDEX_ENABLED": "true"})
    assert provider_for_id("cbs-index-cpi") is CbsIndexProvider
    assert provider_for_id("cbs-hotel-nights") is CbsReleasesProvider
    assert provider_for_id("11111111-ckan") is None


def test_parse_config_rejects_wrong_prefix():
    p = make_provider()
    src = SourceConfig(provider="cbs_index", title="t",
                       config={"resources": [{"id": "a", "name": "a", "codes": [1]}]})
    with pytest.raises(ProviderError):
        p.parse_config("cbs-cpi", src)


def test_facts_share_cbs_credit_and_link_csv_export():
    p = make_provider()
    res = resource(p, start="07-2024")
    q = parse_qs(urlparse(res["url"]).query)
    assert q["format"] == ["csv"] and q["id"] == ["120010"] and q["startPeriod"] == ["07-2024"]
    assert res["params"] == {"codes": [120010], "start": "07-2024", "frequency": "both"}
    src = SourceConfig(provider="cbs_index", title="t",
                       config={"resources": [{"id": "a", "name": "a", "codes": [1]}]})
    facts = p.facts("cbs-index-x", src, p.parse_config("cbs-index-x", src))
    assert facts.organization == CbsReleasesProvider.ORGANIZATION
    assert facts.license_title == CbsReleasesProvider.LICENSE_TITLE
    assert p.presentation().explorer is False
    assert p.page_slug_suffix("cbs-index-cpi") == "cpi"


# ── download ──────────────────────────────────────────────────────────────


def test_download_pages_and_chains_across_bases():
    calls = []
    p = make_provider(calls=calls)
    data = p.csv_bytes(resource(p, start="07-2024"))
    data_calls = [u for u in calls if "Page=" in u]
    chain_calls = [u for u in calls if "last=1" in u]
    assert len(data_calls) == 3  # every page, once, without the ~6x coef payload
    assert not any("coef" in u for u in data_calls)
    assert len(chain_calls) == 1 and "coef=true" in chain_calls[0]
    out = rows(data)
    assert len(out) == 27
    assert [r["TIME_PERIOD"] for r in out[:2]] == ["2024-07", "2024-08"]  # sorted by DATE
    by = {r["TIME_PERIOD"]: r for r in out}
    dec, jan, last = by["2024-12"], by["2025-01"], by["2026-09"]
    assert dec["VALUE"] == "108.4" and dec["BASE_DESC"] == "2022 ממוצע"
    # 2022 → 2024 coefficient 1.074 (the API calculator agrees).
    assert float(dec["VALUE_CHAINED"]) == pytest.approx(108.4 / 1.074, abs=1e-4)
    assert jan["VALUE_CHAINED"] == jan["VALUE"] == "101.5"
    assert last["VALUE_CHAINED"] == "105.3" and last["CHAIN_BASE"] == "2024 ממוצע"
    # The published m/m change survives chaining (within rounding).
    assert float(jan["VALUE_CHAINED"]) / float(dec["VALUE_CHAINED"]) - 1 == pytest.approx(
        float(jan["PERCENT"]) / 100, abs=0.0006)
    assert {r["FREQ"] for r in out} == {"M"} and dec["DATE"] == "2024-12-01"
    assert dec["NAME_HE"] == "מדד המחירים לצרכן - כללי"


def test_csv_is_deterministic_under_page_order():
    p1, p2 = make_provider(), make_provider({"120010": CPI_PAGES})
    a = p1.csv_bytes(resource(p1, start="07-2024"))
    rev = copy.deepcopy(CPI_PAGES)
    for page in rev:
        page["month"][0]["date"].reverse()
    p2 = make_provider({"120010": rev})
    assert p2.csv_bytes(resource(p2, start="07-2024")) == a


def test_unknown_code_fails_the_download():
    p = make_provider({})
    with pytest.raises(ProviderError, match="no both rows for code"):
        p.csv_bytes(resource(p, codes=[999999]))


def test_api_error_body_fails():
    p = make_provider({"120010": [{"Message": "Error: Price Data"}]})
    with pytest.raises(ProviderError, match="CBS Index API error"):
        p.csv_bytes(resource(p))


def _strip_coefficients(pages):
    for page in pages:
        for r in page["month"][0]["date"]:
            r["prevBase"] = []
    return pages


def test_switch_without_coefficient_is_linked_by_percent():
    # Seasonal produce: CBS sometimes publishes no coefficient for a switch.
    exact = {r["TIME_PERIOD"]: float(r["VALUE_CHAINED"])
             for r in rows(rows_csv(CPI_PAGES, [120010], "both"))}
    bridged = {r["TIME_PERIOD"]: float(r["VALUE_CHAINED"])
               for r in rows(rows_csv(_strip_coefficients(copy.deepcopy(CPI_PAGES)),
                                      [120010], "both"))}
    assert exact.keys() == bridged.keys()
    for tp, v in exact.items():
        assert bridged[tp] == pytest.approx(v, rel=1.5e-3), tp
    assert bridged["2025-01"] == exact["2025-01"]  # the newest base is untouched


def test_switch_in_a_seasonal_gap_is_linked_by_percent_year():
    # Oranges: no coefficient, and the month before the switch is out of season.
    a = _row("month", 2024, 1, "A", 200.0)
    b = _row("month", 2025, 1, "B", 100.0)
    b["percent"], b["percentYear"] = None, 10.0
    page = {"month": [_series(1, "month", [b, a])], "paging": {"last_page": 1}}
    out = {r["TIME_PERIOD"]: r for r in rows(rows_csv([page], [1], "month"))}
    assert float(out["2024-01"]["VALUE_CHAINED"]) == pytest.approx(200 / (200 * 1.1 / 100))


def test_unlinkable_switch_leaves_older_rows_unchained():
    pages = _strip_coefficients(copy.deepcopy(CPI_PAGES))
    for page in pages:
        for r in page["month"][0]["date"]:
            if r["currBase"]["baseDesc"] == "2024 ממוצע":
                r["percent"] = r["percentYear"] = None  # no coefficient, no change
    out = {r["TIME_PERIOD"]: r for r in rows(rows_csv(pages, [120010], "both"))}
    assert out["2024-12"]["VALUE"] and out["2024-12"]["VALUE_CHAINED"] == ""
    assert out["2024-07"]["VALUE_CHAINED"] == ""
    assert out["2025-01"]["VALUE_CHAINED"] and out["2025-01"]["CHAIN_BASE"] == "2024 ממוצע"


def _series(code, freq, rows_):
    return {"code": code, "name": f"code {code}", "date": rows_}


def _row(freq, year, n, base, value, prev=None):
    return {"year": year, freq: n, "percent": 0.1, "percentYear": 1.0,
            "currBase": {"baseDesc": base, "value": value}, "prevBase": prev}


def test_monthly_and_quarterly_rows_chain_to_the_newest_base():
    # Housing-like: quarterly to 1993 on base 1987, monthly after on base 1993.
    chain = [{"coeff": 3.736, "baseDesc": "1987 ממוצע", "value": 0},
             {"coeff": 1.484, "baseDesc": "1985 ממוצע", "value": 0}]
    page = {"month": [_series(40010, "month", [_row("month", 1994, 1, "1993 ממוצע", 104.0, chain)])],
            "quarter": [_series(40010, "quarter", [_row("quarter", 1993, 4, "1987 ממוצע", 373.6,
                                                        chain[1:])])],
            "paging": {"last_page": 1}}
    out = rows(rows_csv([page], [40010], "both"))
    q = next(r for r in out if r["FREQ"] == "Q")
    assert q["TIME_PERIOD"] == "1993-Q4" and q["DATE"] == "1993-10-01"
    assert float(q["VALUE_CHAINED"]) == pytest.approx(100.0)
    assert q["CHAIN_BASE"] == "1993 ממוצע"
    only_m = rows(rows_csv([page], [40010], "month"))
    assert {r["FREQ"] for r in only_m} == {"M"}


def test_code_split_across_pages_is_merged():
    a = {"month": [_series(1, "month", [_row("month", 2026, 2, "B", 101.0)])],
         "paging": {"last_page": 2}}
    b = {"month": [_series(1, "month", [_row("month", 2026, 1, "B", 100.0)]),
                   _series(2, "month", [_row("month", 2026, 1, "B", 50.0)])],
         "paging": {"last_page": 2}}
    out = rows(rows_csv([a, b], [1, 2], "month"))
    assert [(r["CODE"], r["TIME_PERIOD"]) for r in out] == [
        ("1", "2026-02"), ("1", "2026-01"), ("2", "2026-01")]


def test_duplicate_period_fails():
    r = _row("month", 2026, 1, "B", 100.0)
    page = {"month": [_series(1, "month", [r, dict(r)])], "paging": {"last_page": 1}}
    with pytest.raises(ProviderError, match="duplicate"):
        rows_csv([page], [1], "month")


def test_chain_factors_multiply_coefficients():
    newest = _row("month", 2026, 1, "C", 100.0,
                  [{"coeff": 2.0, "baseDesc": "B"}, {"coeff": 3.0, "baseDesc": "A"}])
    links = _links(_dated([("month", newest)]), [])
    assert _factors("C", links) == {"C": 1.0, "B": 2.0, "A": 6.0}


def test_links_are_the_union_of_every_rows_coefficients():
    # 150010-like: the newest row stops at B; an older row on B carries B → A.
    newest = _row("month", 2026, 1, "C", 100.0, [{"coeff": 2.0, "baseDesc": "B"}])
    older = _row("month", 2023, 1, "B", 100.0, [{"coeff": 3.0, "baseDesc": "A"}])
    links = _links(_dated([("month", newest)]), _dated([("month", older)]))
    assert _factors("C", links) == {"C": 1.0, "B": 2.0, "A": 6.0}


def test_num_never_uses_exponents():
    assert _num(105.3) == "105.3"
    assert _num(100.0) == "100"
    assert _num(0.0000123456789) == "0.0000123456789"
    assert _num(0.0000123456789, sig=7) == "0.00001234568"
    assert _num(None) == "" and _num("") == ""
    assert _num(-0.5) == "-0.5"


# ── liveness ──────────────────────────────────────────────────────────────


def test_healthcheck_and_probe():
    p = make_provider()
    assert p.healthy()
    alive = [resource(p)]
    assert p.probe_available(alive) == "alive"
    gone = [{**alive[0], "params": {**alive[0]["params"], "codes": [999999]}}]
    assert p.probe_available(gone) == "gone"
    assert p.probe_available([]) == "unknown"


def test_probe_is_unknown_when_api_is_down():
    p = make_provider({})  # health code answers nothing
    assert not p.healthy()
    assert p.probe_available([{"id": "x", "params": {"codes": [1]}}]) == "unknown"


# ── authoring + sync ──────────────────────────────────────────────────────


def test_brief_section(tmp_path):
    p = make_provider()
    res = resource(p, start="07-2024")
    f = tmp_path / "cpi.csv"
    f.write_bytes(p.csv_bytes(res))
    brief = p.brief_section(res, f)
    assert "120010" in brief and "2024-07" in brief and "2026-09" in brief
    assert "| 2 |" in brief  # two bases
    assert "VALUE_CHAINED" in p.authoring_notes()


def test_sync_writes_the_source_doc(tmp_path):
    src = {"provider": "cbs_index", "title": "מדד המחירים לצרכן", "tags": ["מחירים"],
           "config": {"resources": [{"id": "cpi", "name": "מדד", "codes": [120010],
                                     "start": "07-2024"}]}}
    repo = make_repo(tmp_path, {"cbs-index-cpi": src})
    store = FakeStore()
    summary = sync_provider_sources(store, repo, providers={"cbs_index": make_provider()})
    assert summary["changed"] == ["cbs-index-cpi"], summary
    doc = store.docs["cbs-index-cpi"]
    assert doc["provider"] == "cbs_index" and doc["record_count"] == 27
    assert doc["page_slug_suffix"] == "cpi"
    assert doc["presentation"]["source_name_he"] == "הלשכה המרכזית לסטטיסטיקה"
    assert doc["resources"][0]["hash"]


def test_same_codes_different_frequency_do_not_share_the_cache():
    chain = [{"coeff": 3.736, "baseDesc": "1987 ממוצע", "value": 0}]
    page = {"month": [_series(40010, "month", [_row("month", 1994, 1, "1993 ממוצע", 104.0,
                                                    chain)])],
            "quarter": [_series(40010, "quarter", [_row("quarter", 1993, 4, "1987 ממוצע",
                                                        373.6)])],
            "paging": {"last_page": 1}}
    p = make_provider({"40010": [page]})
    monthly = resource(p, codes=[40010], frequency="month")
    quarterly = resource(p, codes=[40010], frequency="quarter")
    assert monthly["url"] == quarterly["url"]  # the CSV export can't tell them apart
    assert {r["FREQ"] for r in rows(p.csv_bytes(monthly))} == {"M"}
    assert {r["FREQ"] for r in rows(p.csv_bytes(quarterly))} == {"Q"}


def test_published_figures_pass_through_exactly():
    page = {"month": [_series(1, "month", [_row("month", 2026, 1, "B", 1234567.85)])],
            "paging": {"last_page": 1}}
    (r,) = rows(rows_csv([page], [1], "month"))
    assert r["VALUE"] == "1234567.85"  # published: never re-rounded
    assert r["VALUE_CHAINED"] == "1234568"  # computed: 7 significant digits


def test_chain_comes_from_the_chain_pages():
    data = {"month": [_series(1, "month", [_row("month", 2026, 1, "B", 100.0),
                                           _row("month", 2025, 12, "A", 200.0)])],
            "paging": {"last_page": 1}}
    chain = {"month": [_series(1, "month", [_row("month", 2026, 1, "B", 100.0,
                                                 [{"coeff": 2.0, "baseDesc": "A"}])])],
             "paging": {"last_page": 1}}
    by = {r["TIME_PERIOD"]: r for r in rows(rows_csv([data], [1], "month", [chain]))}
    assert by["2025-12"]["VALUE_CHAINED"] == "100"
    # Data pages alone carry no coefficient: the switch is linked by PERCENT (0.1).
    alone = {r["TIME_PERIOD"]: r for r in rows(rows_csv([data], [1], "month"))}
    assert float(alone["2025-12"]["VALUE_CHAINED"]) == pytest.approx(200 / (200 * 1.001 / 100))
    with pytest.raises(ProviderError, match="no row with chaining"):
        rows_csv([data], [1], "month", [{"month": None, "paging": {}}])


def test_brief_names_quarters_by_time_period(tmp_path):
    page = {"quarter": [_series(40010, "quarter", [_row("quarter", 1993, 4, "B", 1.0),
                                                   _row("quarter", 1993, 1, "B", 1.0)])],
            "paging": {"last_page": 1}}
    p = make_provider({"40010": [page]})
    res = resource(p, codes=[40010], frequency="quarter")
    f = tmp_path / "q.csv"
    f.write_bytes(p.csv_bytes(res))
    brief = p.brief_section(res, f)
    assert "| 1993-Q1 | 1993-Q4 |" in brief
