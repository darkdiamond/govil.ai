"""Tests for services.scanner.models parsing of CKAN responses."""
from __future__ import annotations

from services.scanner.models import Dataset


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


def test_public_resource_url_rewrites_gated_hosts_and_locale_prefix():
    from services.scanner.models import _public_resource_url as f

    path = "dataset/x/resource/y/download/a.csv"
    assert f(f"https://e.data.gov.il/{path}") == f"https://data.gov.il/{path}"
    assert f(f"https://aws-e.data.gov.il/{path}") == f"https://data.gov.il/{path}"
    assert f(f"https://e.data.gov.il/he/{path}") == f"https://data.gov.il/{path}"
    assert f(f"https://data.gov.il/en/{path}") == f"https://data.gov.il/{path}"
    # Non-CKAN hosts keep their locale segments.
    assert f("https://www.gov.il/he/Departments/x") == "https://www.gov.il/he/Departments/x"
    assert f("") == ""
