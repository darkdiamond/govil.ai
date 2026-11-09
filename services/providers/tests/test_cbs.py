"""CBS recurring-release provider: release matching, table files, the grid.

HTTP is faked through the `_send` seam (no network). Fixtures in
fixtures/cbs/: `table.xls` and `table.xlsx` hold the same cells (written with
xlwt / openpyxl; the xlsx floats rewritten to full repr, as Excel writes
them), and `visitors_t5_real.xls` is a real CBS table (release 277/2026).
"""
from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

import pytest

from services.providers import (
    ProviderError,
    SourceConfig,
    build_providers,
    provider_for_id,
)
from services.providers.cbs import (
    CbsReleasesProvider,
    cell_text,
    grid_csv,
    normalize_title,
    suggest_regex,
    workbook_grid,
)
from services.providers.sync import sync_provider_sources
from services.providers.tests.sync_helpers import FakeStore, make_repo

pytest.importorskip("python_calamine")

FIX = Path(__file__).parent / "fixtures" / "cbs"
XLS = (FIX / "table.xls").read_bytes()
XLSX = (FIX / "table.xlsx").read_bytes()


class FakeResp:
    def __init__(self, status=200, body=b"", ctype="application/json"):
        self.status_code, self.content = status, body
        self.headers = {"content-type": ctype}

    def json(self):
        return json.loads(self.content)


def item(no, title, when, interval="חודשי", body="<p>152.4 אלף כניסות</p>", year="2026",
         created="2026-01-01T00:00:00Z"):
    return {
        "Title": title, "CbsPubNumber": f"{no}/{year}", "CbsDataPublishDate": when,
        "Created": created, "CbsPublishingFolderLevel1": year, "CbsPublishingFolderLevel2": no,
        "CbsMMDInterval": [{"Label": interval}], "CbsMMDSubjects": [], "cbsBodyText": body,
        "FileRef": f"/he/mediarelease/Pages/{year}/{title.replace(' ', '-')}.aspx",
    }


ITEMS = [
    item("345", "כניסות של מבקרים לישראל באוקטובר 2026", "2026-11-04T11:00:00Z"),
    item("347", "השכר הממוצע ברוטו למשרת שכיר בחודש אוגוסט 2026", "2026-11-04T11:00:00Z"),
    # CbsDataPublishDate null → falls back to Created.
    item("309", "כניסות של מבקרים לישראל בספטמבר 2026", None, created="2026-10-07T06:00:37Z"),
    item("277", "כניסות של מבקרים לישראל באוגוסט 2026", "2026-09-06T10:00:00Z"),
    # The yearly summary is labelled monthly too; excluded by the regex.
    item("006", "כניסות של מבקרים לישראל בשנת 2025", "2026-01-06T11:00:00Z"),
    item("341", "מבחר נתונים לרגל כניסות של מבקרים לישראל", "2026-10-29T11:00:00Z",
         interval="רב שנתי"),
    {"Title": None, "CbsPubNumber": "1/2026"},  # unusable items are dropped
]

FOLDERS = {
    "2026/345": ["28_26_345t1.xlsx", "28_26_345t1.pdf", "28_26_345t11.xlsx",
                 "28_26_345b.pdf", "28_26_345b.docx"],
    "2026/309": ["28_26_309t1.xlsx", "28_26_309t1.pdf"],
    "2026/277": ["28_26_277t1.xls", "28_26_277t1.pdf", "28_26_277b.pdf"],
    "2026/006": ["28_26_006t1.xls"],
    "2026/341": ["27_26_341t1.xlsx"],
    "2026/347": ["26_26_347t1.xlsx"],
}
FILES = {
    "28_26_345t1.xlsx": XLSX, "28_26_309t1.xlsx": XLSX, "28_26_277t1.xls": XLS,
    "28_26_006t1.xls": XLS, "28_26_345t11.xlsx": XLSX,
}

REPORT = {"title_regex": "^כניסות של מבקרים לישראל ב(?!שנת)", "chapter": "28",
          "interval": "חודשי"}


@pytest.fixture
def cbs(monkeypatch):
    p = CbsReleasesProvider(CbsReleasesProvider.default_settings.model_copy(
        update={"enabled": True, "min_interval_s": 0.0, "retries": 0}))
    p.items, p.folders, p.files, p.calls = list(ITEMS), dict(FOLDERS), dict(FILES), []

    def fake_get(url, **kw):
        u = unquote(url)
        p.calls.append(u)
        if "/lists/getbytitle(" in u:
            top = int(u.split("$top=")[1].split("&")[0])
            return FakeResp(200, json.dumps({"value": p.items[:top]}).encode())
        if "GetFolderByServerRelativeUrl(" in u:
            key = u.split("DocLib/")[1].split("'")[0]
            names = p.folders.get(key, [])
            return FakeResp(200, json.dumps(
                {"value": [{"Name": n, "Length": str(len(p.files.get(n, b"x")))} for n in names]}
            ).encode())
        name = u.rsplit("/", 1)[-1]
        if name in p.files:
            return FakeResp(200, p.files[name], "application/octet-stream")
        return FakeResp(404, b"<html>", "text/html")

    monkeypatch.setattr(p, "_send", fake_get)
    return p


def source(config, title="כניסות מבקרים לישראל"):
    return SourceConfig(provider="cbs_releases", title=title, config=config)


def table_cfg(history=1, **res):
    return {"report": REPORT, "history_releases": history,
            "resources": [{"id": "t1", "name": "כניסות", "table": "t1", **res}]}


def resource(p, cfg, i=0, dataset_id="cbs-v") -> dict:
    """Resource `i` as the sync stores it on the source doc."""
    return p.facts(dataset_id, source(cfg), p.parse_config(dataset_id, source(cfg))
                   ).resources[i].model_dump()


def rows(data: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"))))


# ── registry + config ────────────────────────────────────────────────────


def test_registered_and_off_by_default():
    assert provider_for_id("cbs-visitor-arrivals") is CbsReleasesProvider
    assert "cbs_releases" not in build_providers({})
    assert "cbs_releases" in build_providers({"PROVIDER_CBS_RELEASES_ENABLED": "true"})


@pytest.mark.parametrize("config", [
    {"report": {"title_regex": "(unclosed"}, "resources": [{"id": "a", "name": "a", "table": "t1"}]},
    {"report": {"title_regex": "x"}, "resources": [{"id": "a", "name": "a"}]},  # table w/o stem
    {"report": {"title_regex": "x"}, "resources": [{"id": "a", "name": "a", "table": "1"}]},
    {"report": {"title_regex": "x"},
     "resources": [{"id": "a", "name": "a", "kind": "releases", "table": "t1"}]},
    {"report": {"title_regex": "x"}, "resources": [{"id": "a", "name": "a", "table": "t1"},
                                                    {"id": "a", "name": "b", "table": "t2"}]},
    {"report": {"title_regex": "x", "extra": 1},
     "resources": [{"id": "a", "name": "a", "table": "t1"}]},
    {"report": {"title_regex": "x"},
     "resources": [{"id": "a", "name": "a", "kind": "releases", "optional": True}]},
    {"report": {"title_regex": "x"}, "resources": [{"id": "a", "name": "a", "table": "t3ab"}]},
    {"report": {"title_regex": "x"}, "resources": [{"id": "a", "name": "a", "table": "t3A"}]},
])
def test_bad_configs_rejected(cbs, config):
    with pytest.raises(ValueError):
        cbs.parse_config("cbs-x", source(config))


def test_lettered_stems_and_optional_accepted(cbs):
    cfg = cbs.parse_config("cbs-x", source(table_cfg(table="t3a", optional=True)))
    assert cfg.resources[0].table == "t3a" and cfg.resources[0].optional is True


def test_window_reaches_yearly_reports(cbs):
    from services.providers import cbs as cbs_mod
    assert cbs_mod.LIST_WINDOW >= 1500
    cbs.releases()
    assert f"$top={cbs_mod.LIST_WINDOW}&" in next(c for c in cbs.calls if "/lists/" in c)


def test_id_prefix_enforced(cbs):
    with pytest.raises(ProviderError):
        cbs.parse_config("visitors", source(table_cfg()))


# ── release matching ─────────────────────────────────────────────────────


def test_matching_newest_first_with_filters(cbs):
    got = cbs.matching(REPORT, 10)
    assert [r.pub_no for r in got] == ["345/2026", "309/2026", "277/2026"]
    # Null publish date fell back to Created (Israel-local date).
    assert got[1].date == "2026-10-07"


def test_embargoed_release_is_left_out(cbs):
    """A page item created ahead of its publication time isn't matched yet."""
    cbs.items.insert(0, item("399", "כניסות של מבקרים לישראל בנובמבר 2026",
                             "2999-12-01T09:00:00Z"))
    cbs.folders["2026/399"] = ["28_26_399t1.xlsx"]
    assert cbs.matching(REPORT, 1)[0].pub_no == "345/2026"


def test_regex_alone_also_takes_special_editions(cbs):
    got = cbs.matching({"title_regex": "כניסות של מבקרים לישראל"}, 10)
    assert {r.pub_no for r in got} >= {"006/2026", "341/2026"}


def test_interval_and_chapter_filters(cbs):
    rx = {"title_regex": "כניסות של מבקרים לישראל"}
    assert "341/2026" not in [r.pub_no for r in cbs.matching({**rx, "interval": "חודשי"}, 10)]
    assert "341/2026" not in [r.pub_no for r in cbs.matching({**rx, "chapter": "28"}, 10)]


def test_no_match_raises(cbs):
    with pytest.raises(ProviderError, match="no CBS release"):
        cbs.matching({"title_regex": "^מדד המחירים לצרכן"}, 1)


def test_one_list_query_per_run(cbs):
    cbs.matching(REPORT, 2)
    cbs.matching({"title_regex": "^השכר הממוצע"}, 1)
    assert sum("/lists/getbytitle(" in c for c in cbs.calls) == 1
    cbs.clear_cache()
    cbs.matching(REPORT, 1)
    assert sum("/lists/getbytitle(" in c for c in cbs.calls) == 2


# ── table files ──────────────────────────────────────────────────────────


def test_table_file_prefers_xlsx_and_matches_whole_stem(cbs):
    rel = cbs.matching(REPORT, 1)[0]
    cbs.folders["2026/345"] = ["28_26_345t1.xls", "28_26_345t1.xlsx", "28_26_345t11.xlsx"]
    cbs._folders.clear()
    assert cbs.table_file(rel, "t1")["Name"] == "28_26_345t1.xlsx"
    assert cbs.table_file(rel, "t11")["Name"] == "28_26_345t11.xlsx"
    with pytest.raises(ProviderError, match="no t2"):
        cbs.table_file(rel, "t2")


def test_table_file_lettered_stems_match_exactly(cbs):
    rel = cbs.matching(REPORT, 1)[0]
    cbs.folders["2026/345"] = ["28_26_345t3.xlsx", "28_26_345t3a.xlsx", "28_26_345t13b.xls"]
    cbs._folders.clear()
    assert cbs.table_file(rel, "t3")["Name"] == "28_26_345t3.xlsx"
    assert cbs.table_file(rel, "t3a")["Name"] == "28_26_345t3a.xlsx"
    assert cbs.find_table_file(rel, "t3b") is None
    assert cbs.find_table_file(rel, "t13") is None
    cbs.folders["2026/345"] = ["28_26_345t3a.xlsx"]
    cbs._folders.clear()
    assert cbs.find_table_file(rel, "t3") is None


def test_facts_point_at_latest_file(cbs):
    cfg = table_cfg()
    cfg["resources"].append({"id": "releases", "name": "פרסומים", "kind": "releases"})
    pf = cbs.facts("cbs-v", source(cfg), cbs.parse_config("cbs-v", source(cfg)))
    t1, rel = pf.resources
    assert unquote(t1.url).endswith("/DocLib/2026/345/28_26_345t1.xlsx") and t1.format == "XLSX"
    assert t1.params == {"kind": "table", "report": REPORT, "table": "t1", "history_releases": 1}
    assert rel.format == "HTML" and rel.url.startswith("https://www.cbs.gov.il/he/mediarelease/")
    assert pf.organization["title"] == "הלשכה המרכזית לסטטיסטיקה"
    assert cbs.presentation().explorer is False


# ── the grid ─────────────────────────────────────────────────────────────


def test_xls_and_xlsx_give_identical_grids():
    assert workbook_grid(XLS) == workbook_grid(XLSX)


def test_xls_and_xlsx_give_byte_identical_csv(cbs):
    """Same table in a release that shipped .xlsx and one that shipped .xls."""
    as_xlsx = cbs.csv_bytes(resource(cbs, table_cfg()))
    cbs.clear_cache()
    cbs.folders["2026/345"] = ["28_26_345t1.xls"]
    cbs.files["28_26_345t1.xls"] = XLS
    res = resource(cbs, table_cfg())
    as_xls = cbs.csv_bytes(res)
    assert unquote(res["url"]).endswith(".xls")
    assert as_xls == as_xlsx


def test_grid_cells_and_layout(cbs):
    data = cbs.csv_bytes(resource(cbs, table_cfg()))
    header = data.decode().splitlines()[0].split(",")
    assert header[:5] == ["RELEASE_NO", "RELEASE_DATE", "SHEET_NO", "SHEET", "ROW"]
    assert header[5:] == ["C01", "C02", "C03", "C04", "C05"]  # widest row, padded
    g = rows(data)
    assert {x["RELEASE_NO"] for x in g} == {"345/2026"}
    assert {x["RELEASE_DATE"] for x in g} == {"2026-11-04"}
    by_row = {(x["SHEET_NO"], x["ROW"]): x for x in g}
    assert ("01", "00003") not in by_row  # empty rows skipped, numbering kept
    title = by_row[("01", "00004")]["C01"]
    assert title == "לוח 1. כניסות מבקרים (1) לפי דרך כניסה"  # whitespace + newline collapsed
    data_row = by_row[("01", "00006")]
    assert [data_row[f"C0{i}"] for i in range(1, 6)] == ["2025", "I", "169.79999999999998",
                                                          "152", "-"]
    assert by_row[("01", "00008")]["C03"] == "1e-05"
    assert by_row[("01", "00009")]["C02"] == "2026-11-04"  # date cell → ISO
    assert by_row[("02", "00001")]["SHEET"] == "גיליון2"


def test_history_releases_stack_in_row_order(cbs):
    g = rows(cbs.csv_bytes(resource(cbs, table_cfg(history=3))))
    assert [x["RELEASE_NO"] for x in g if x["ROW"] == "00001" and x["SHEET_NO"] == "01"] == [
        "277/2026", "309/2026", "345/2026"]  # oldest first (RELEASE_DATE sort)
    first = [x["ROW"] for x in g if x["RELEASE_NO"] == "345/2026" and x["SHEET_NO"] == "01"]
    assert first == sorted(first) and first[:3] == ["00001", "00002", "00004"]


def test_history_cache_is_keyed_by_params(cbs):
    r1 = resource(cbs, table_cfg(history=1), dataset_id="cbs-a")
    r3 = resource(cbs, table_cfg(history=3), dataset_id="cbs-b")
    assert r1["url"] == r3["url"]
    assert cbs.version(r1).rows < cbs.version(r3).rows


def test_missing_table_in_older_release_raises(cbs):
    cbs.folders["2026/309"] = ["28_26_309t2.xlsx"]
    with pytest.raises(ProviderError, match="309/2026: no t1"):
        cbs.download(resource(cbs, table_cfg(history=2)))


def test_optional_table_skips_editions_that_lack_it(cbs):
    cbs.folders["2026/309"] = ["28_26_309t2.xlsx"]  # middle edition has no t1
    res = resource(cbs, table_cfg(history=3, optional=True))
    assert res["params"]["optional"] is True
    g = rows(cbs.csv_bytes(res))
    assert {x["RELEASE_NO"] for x in g} == {"345/2026", "277/2026"}


def test_optional_table_missing_everywhere_is_an_empty_grid(cbs):
    for k in ("2026/345", "2026/309", "2026/277"):
        cbs.folders[k] = [n.replace("t1.", "t2.") for n in FOLDERS[k]]
    with pytest.raises(ProviderError, match="no t1"):
        resource(cbs, table_cfg())  # a required table still fails the facts
    res = resource(cbs, table_cfg(history=2, optional=True))
    assert res["format"] == "HTML" and "/Pages/" in unquote(res["url"])  # the release page
    data = cbs.csv_bytes(res)
    assert data.decode().splitlines() == ["RELEASE_NO,RELEASE_DATE,SHEET_NO,SHEET,ROW,C01"]
    assert cbs.version(res).rows == 0
    assert cbs.preview(res)["total"] == 0


def test_optional_brief_says_the_table_is_absent(cbs, tmp_path):
    for k in ("2026/345", "2026/309", "2026/277"):
        cbs.folders[k] = [n.replace("t1.", "t2.") for n in FOLDERS[k]]
    d = resource(cbs, table_cfg(history=2, optional=True))
    out = tmp_path / "1.csv"
    cbs.fetch_to_file(d, out, max_bytes=10**7)
    assert "(optional)" in cbs.brief_section(d, out)
    assert "absent from every edition" in cbs.brief_section(d, out)


def test_bad_workbook_raises(cbs):
    cbs.files["28_26_345t1.xlsx"] = b"not a workbook"
    res = resource(cbs, table_cfg())
    with pytest.raises(ProviderError, match="unreadable workbook"):
        cbs.download(res)
    assert cbs.preview(res) is None  # preview reports a failed download as None


def test_real_cbs_xls_reads_hebrew():
    sheets = workbook_grid((FIX / "visitors_t5_real.xls").read_bytes())
    (_, name, sheet_rows), = sheets
    assert name == "נתוני תרשימים 2-1"
    cells = {c for _, r in sheet_rows for c in r}
    assert {"הלשכה המרכזית לסטטיסטיקה", "פורסם 06/09/2026", "מנוכי עונתיות"} <= cells
    row7 = dict(sheet_rows)[7]
    assert row7[:4] == ["2019", "I", "250", "319.496982975656"]


@pytest.mark.parametrize("v, want", [
    (None, ""), (True, "TRUE"), (False, "FALSE"), (3, "3"), (152.0, "152"), (-0.0, "0"),
    (0.1, "0.1"), (float("nan"), ""), ("  a \n b ", "a b"),
])
def test_cell_text(v, want):
    assert cell_text(v) == want


def test_grid_csv_with_no_rows_has_a_header():
    assert grid_csv([]).decode().splitlines() == ["RELEASE_NO,RELEASE_DATE,SHEET_NO,SHEET,ROW,C01"]


# ── releases resource ────────────────────────────────────────────────────


def test_releases_resource(cbs):
    cfg = {"report": REPORT,
           "resources": [{"id": "releases", "name": "פרסומים", "kind": "releases", "limit": 2}]}
    g = rows(cbs.csv_bytes(resource(cbs, cfg)))
    assert list(g[0]) == ["RELEASE_NO", "RELEASE_DATE", "TITLE", "HEADLINE", "PAGE_URL",
                          "REPORT_PDF_URL"]
    assert [x["RELEASE_NO"] for x in g] == ["309/2026", "345/2026"]
    latest = g[1]
    assert latest["HEADLINE"] == "152.4 אלף כניסות"  # HTML stripped
    assert unquote(latest["REPORT_PDF_URL"]).endswith("/DocLib/2026/345/28_26_345b.pdf")
    assert g[0]["REPORT_PDF_URL"] == ""  # 309 has no written report
    assert unquote(latest["PAGE_URL"]).startswith("https://www.cbs.gov.il/he/mediarelease/Pages/")


# ── liveness, authoring ──────────────────────────────────────────────────


def test_healthcheck(cbs):
    assert cbs.healthy() is True
    assert any("$top=1&" in c for c in cbs.calls)


def test_healthcheck_fails_on_http_error(cbs, monkeypatch):
    monkeypatch.setattr(cbs, "_send", lambda url, **kw: FakeResp(503, b""))
    assert cbs.healthy() is False


def test_probe_is_never_gone(cbs):
    assert cbs.probe_available([{"id": "t1"}]) == "unknown"


def test_brief_section(cbs, tmp_path):
    d = resource(cbs, table_cfg(history=2))
    out = tmp_path / "1.csv"
    cbs.fetch_to_file(d, out, max_bytes=10**7)
    brief = cbs.brief_section(d, out)
    assert "345/2026 `28_26_345t1.xlsx`" in brief and "309/2026 `28_26_309t1.xlsx`" in brief
    assert "**345/2026 (2026-11-04), sheet 01 `לוח 1 table`**" in brief
    assert "| 00006 | 2025 | I | 169.79999999999998 | 152 | - |" in brief
    assert "by label" in cbs.authoring_notes().lower()


# ── catalog ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("title, key", [
    ("כניסות של מבקרים לישראל באוקטובר 2026", "כניסות של מבקרים לישראל"),
    ("כניסות של מבקרים לישראל בספטמבר 2026", "כניסות של מבקרים לישראל"),
    ("השכר הממוצע ברוטו למשרת שכיר בחודש אוגוסט 2026", "השכר הממוצע ברוטו למשרת שכיר"),
    ("רכישות בכרטיסי אשראי על ידי צרכנים פרטיים יולי-ספטמבר 2026",
     "רכישות בכרטיסי אשראי על ידי צרכנים פרטיים"),
    ("רכישות בכרטיסי אשראי על ידי צרכנים פרטיים יוני-אוגוסט 2026",
     "רכישות בכרטיסי אשראי על ידי צרכנים פרטיים"),
    ("חשבונות לאומיים: אומדן שלישי לרבעון השני של שנת 2026", "חשבונות לאומיים אומדן של"),
    ("נתונים מסקר כוח אדם לחודש ספטמבר 2026 (נתונים עיקריים)", "נתונים מסקר כוח אדם"),
    ("הייצור התעשייתי של ענפי התעשייה, הכרייה והחציבה: יוני - אוגוסט 2026",
     "הייצור התעשייתי של ענפי התעשייה הכרייה והחציבה"),
    ("השכלה גבוהה בישראל - נתונים נבחרים לשנת הלימודים תשפ\"ו (2025/26)",
     "השכלה גבוהה בישראל נתונים נבחרים הלימודים"),
])
def test_normalize_title(title, key):
    assert normalize_title(title) == key


def test_suggest_regex():
    assert suggest_regex(["כניסות של מבקרים לישראל באוקטובר 2026",
                          "כניסות של מבקרים לישראל בספטמבר 2026"]) == "^כניסות של מבקרים לישראל "
    assert suggest_regex(["פדיון (מכירות) של רשתות השיווק א", "פדיון (מכירות) של רשתות השיווק ב"]
                         ) == r"^פדיון \(מכירות\) של רשתות השיווק "


# ── sync: the listing-key skip ───────────────────────────────────────────


def _sync(p, store, repo):
    p.clear_cache()
    p.calls.clear()
    return sync_provider_sources(store, repo, providers={"cbs_releases": p})


def _data_calls(p) -> list[str]:
    return [c for c in p.calls if "/lists/getbytitle(" not in c]


@pytest.fixture
def synced(cbs, tmp_path):
    repo = make_repo(tmp_path, {"cbs-v": source(table_cfg(history=2)).model_dump()})
    store = FakeStore()
    s = _sync(cbs, store, repo)
    assert s["changed"] == ["cbs-v"] and _data_calls(cbs)
    assert store.docs["cbs-v"]["provider_listing_key"]
    return cbs, store, repo


def test_unchanged_report_syncs_without_downloads(synced):
    p, store, repo = synced
    doc = dict(store.docs["cbs-v"])
    s = _sync(p, store, repo)
    assert s["synced"] == ["cbs-v"] and s["changed"] == [] and not s["failed"]
    assert _data_calls(p) == []  # only the list query (healthcheck + window)
    assert store.docs["cbs-v"] == doc


def test_new_edition_forces_a_full_sync(synced):
    p, store, repo = synced
    p.items.insert(0, item("380", "כניסות של מבקרים לישראל בנובמבר 2026", "2026-11-07T11:00:00Z"))
    p.folders["2026/380"] = ["28_26_380t1.xls"]
    p.files["28_26_380t1.xls"] = XLS
    s = _sync(p, store, repo)
    assert any("380t1.xls" in c for c in _data_calls(p))
    assert s["changed"] == ["cbs-v"]  # 380 + 345 stacked instead of 345 + 309


def test_edited_headline_forces_a_full_sync(synced):
    p, store, repo = synced
    p.items[0] = item("345", ITEMS[0]["Title"], "2026-11-04T11:00:00Z", body="<p>תוקן</p>")
    _sync(p, store, repo)
    assert _data_calls(p)


def test_source_json_edit_forces_a_full_sync(synced, tmp_path):
    p, store, repo = synced
    (tmp_path / "cbs-v" / "source.json").write_text(
        json.dumps(source(table_cfg(history=2), title="כותרת חדשה").model_dump(), ensure_ascii=False))
    _sync(p, store, repo)
    assert _data_calls(p) and store.docs["cbs-v"]["title"] == "כותרת חדשה"


def test_stale_verification_forces_a_full_sync(synced):
    p, store, repo = synced
    store.docs["cbs-v"]["provider_verified_at"] = datetime.now(UTC) - timedelta(days=8)
    _sync(p, store, repo)
    assert _data_calls(p)
    assert datetime.now(UTC) - store.docs["cbs-v"]["provider_verified_at"] < timedelta(minutes=1)


def test_recheck_days_zero_always_downloads(synced):
    p, store, repo = synced
    p.settings = p.settings.model_copy(update={"listing_recheck_days": 0})
    _sync(p, store, repo)
    assert _data_calls(p)


def test_listing_key_ignores_unrelated_releases(cbs):
    cfg = cbs.parse_config("cbs-v", source(table_cfg()))
    before = cbs.listing_key("cbs-v", source(table_cfg()), cfg)
    cbs.clear_cache()
    cbs.items.insert(0, item("390", "מדד המחירים לצרכן", "2026-11-15T11:00:00Z"))
    assert cbs.listing_key("cbs-v", source(table_cfg()), cfg) == before


def test_files_landing_late_in_a_fresh_release_move_the_key(synced):
    # CBS lists the page before its tables land: the full sync skips the
    # empty release (chapter filter), and the key must move once they arrive.
    p, store, repo = synced
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    p.items.insert(0, item("390", "כניסות של מבקרים לישראל בנובמבר 2026", now))
    p.folders["2026/390"] = []
    s = _sync(p, store, repo)
    assert s["changed"] == [] and not s["failed"]  # still the 345 + 309 stack
    _sync(p, store, repo)
    assert [c for c in _data_calls(p) if "DocLib" in c and "Files?" not in c] == []  # no downloads

    p.folders["2026/390"] = ["28_26_390t1.xls"]
    p.files["28_26_390t1.xls"] = XLS
    s = _sync(p, store, repo)
    assert any("390t1.xls" in c for c in _data_calls(p)) and s["changed"] == ["cbs-v"]
