"""Tests for services.scanner.models parsing of CKAN responses."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.scanner.models import Dataset

# Shared with frontend/tests/security-belts.test.mjs, which runs the same
# vectors through frontend/utils/resource-url.ts (the render-time mirror).
_URL_VECTORS = json.loads(
    (Path(__file__).resolve().parents[3] / "frontend" / "tests" / "fixtures"
     / "resource-url-vectors.json").read_text(encoding="utf-8")
)["vectors"]


def _ckan_package(resources: list[dict]) -> dict:
    return {
        "id": "abc-123",
        "name": "test-dataset",
        "title": "מאגר בדיקה",
        "resources": resources,
    }


def test_from_ckan_response_parses_datastore_active():
    ds = Dataset.from_ckan_response(_ckan_package([
        {
            "id": "rid-1",
            "name": "main",
            "format": "csv",
            "url": "https://data.gov.il/dataset/x/resource/rid-1/download/x.csv",
            "datastore_active": True,
        },
        {
            "id": "rid-2",
            "name": "pdf",
            "format": "pdf",
            "url": "https://data.gov.il/dataset/x/resource/rid-2/download/x.pdf",
            # key absent — must default to False, not crash
        },
    ]))
    by_id = {r.id: r for r in ds.resources}
    assert by_id["rid-1"].datastore_active is True
    assert by_id["rid-2"].datastore_active is False


def test_from_ckan_response_keeps_file_hash():
    ds = Dataset.from_ckan_response(_ckan_package([
        {"id": "rid-1", "url": "https://data.gov.il/x.csv",
         "hash": "1f02d8a3201f29b85ca9239863a0cb2f"},
        {"id": "rid-2", "url": "https://data.gov.il/y.csv", "hash": ""},  # API-pushed
    ]))
    by_id = {r.id: r for r in ds.resources}
    assert by_id["rid-1"].hash == "1f02d8a3201f29b85ca9239863a0cb2f"
    assert by_id["rid-2"].hash is None


@pytest.mark.parametrize(("url", "expected"), _URL_VECTORS)
def test_public_resource_url_shared_vectors(url, expected):
    from services.shared.ckan import public_resource_url as f

    assert f(url) == expected


def test_public_resource_url_non_string_is_blank():
    from services.shared.ckan import public_resource_url as f

    assert f(None) == ""
    assert f(123) == ""


def test_dataset_with_script_resource_url_is_blanked():
    from services.scanner.models import Dataset

    ds = Dataset.from_ckan_response(_ckan_package([
        {"id": "rid-1", "name": "x", "format": "csv", "url": "javascript:alert(document.domain)"},
    ]))
    assert ds.resources[0].url == ""


_FULL_RESOURCE = {
    "id": "rid-1",
    "name": "main",
    "format": "csv",
    "url": "https://data.gov.il/dataset/x/resource/rid-1/download/x.csv",
}
_FULL_ORG = {"id": "org-1", "name": "moh", "title": "משרד הבריאות"}


@pytest.mark.parametrize("field", ["id", "name", "format", "url"])
def test_null_resource_string_fields_parse(field):
    ds = Dataset.from_ckan_response(_ckan_package([{**_FULL_RESOURCE, field: None}]))
    assert getattr(ds.resources[0], field) == ""


@pytest.mark.parametrize("field", ["id", "name", "title"])
def test_null_organization_string_fields_parse(field):
    pkg = {**_ckan_package([]), "organization": {**_FULL_ORG, field: None}}
    ds = Dataset.from_ckan_response(pkg)
    assert getattr(ds.organization, field) == ""


@pytest.mark.parametrize("field", ["name", "title"])
def test_null_dataset_string_fields_parse(field):
    ds = Dataset.from_ckan_response({**_ckan_package([]), field: None})
    assert getattr(ds, field) == ""


@pytest.mark.parametrize("value", [None, "", "missing"])
def test_dataset_without_id_is_unparseable(value):
    pkg = _ckan_package([])
    if value == "missing":
        del pkg["id"]
    else:
        pkg["id"] = value
    with pytest.raises(ValueError, match="no id"):
        Dataset.from_ckan_response(pkg)


@pytest.mark.parametrize("value", [None, "x", 5, {"a": 1}])
def test_null_or_odd_collections_parse(value):
    ds = Dataset.from_ckan_response({**_ckan_package(value), "tags": value})
    assert ds.tags == []
    assert ds.resources == []


def test_non_dict_collection_entries_are_skipped():
    pkg = {
        **_ckan_package([None, "junk", _FULL_RESOURCE]),
        "tags": [None, "junk", {"name": "בריאות"}, {"name": None}],
    }
    ds = Dataset.from_ckan_response(pkg)
    assert ds.tags == ["בריאות", ""]
    assert [r.id for r in ds.resources] == ["rid-1"]


def test_well_formed_input_unchanged():
    pkg = {
        **_ckan_package([_FULL_RESOURCE]),
        "organization": _FULL_ORG,
        "tags": [{"name": "בריאות"}],
    }
    ds = Dataset.from_ckan_response(pkg)
    assert (ds.id, ds.name, ds.title) == ("abc-123", "test-dataset", "מאגר בדיקה")
    assert (ds.organization.id, ds.organization.name, ds.organization.title) == (
        "org-1", "moh", "משרד הבריאות")
    assert ds.tags == ["בריאות"]
    r = ds.resources[0]
    assert (r.id, r.name, r.format, r.url) == (
        "rid-1", "main", "CSV",
        "https://data.gov.il/dataset/x/resource/rid-1/download/x.csv")
