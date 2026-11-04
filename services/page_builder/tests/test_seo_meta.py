"""agent_data.seo: recipe-owned search metadata (schema, check.py, publish)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from services.page_builder import publish
from services.page_builder.schema import AgentData
from services.page_builder.tests.test_publish import _src, _store_mock

_CHECK_PATH = Path(__file__).resolve().parents[3] / "agent" / "skills" / "check.py"
_spec = importlib.util.spec_from_file_location("agent_check_seo", _CHECK_PATH)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

GOOD = {
    "title": "  איתור רופא לפי מספר רישיון  ",
    "description": "חיפוש רופא לפי שם, מספר רישיון או התמחות: 41,203 רופאים מורשים, "
                   "עם פילוח לפי התמחות ושנת רישוי.",
    "name": "פנקס הרופאים",
    "alternate_names": ["רשם הרופאים", "רשם הרופאים", "פינקס רופאים"],
}


def test_seo_is_stripped_and_alternate_names_deduplicated():
    a = AgentData.model_validate({"summary_he": "x", "dataset_kind": "registry", "seo": GOOD})
    assert a.seo.title == "איתור רופא לפי מספר רישיון"
    assert a.seo.alternate_names == ["רשם הרופאים", "פינקס רופאים"]


def test_seo_is_optional():
    assert AgentData.model_validate({"summary_he": "x", "dataset_kind": "misc"}).seo is None
    seo = {"title": "כותרת", "alternate_names": None}
    a = AgentData.model_validate({"summary_he": "x", "dataset_kind": "misc", "seo": seo})
    assert a.seo.alternate_names == []


def test_check_py_accepts_good_seo_and_rejects_a_long_title(capsys):
    check.check_seo(None)
    check.check_seo(GOOD)
    with pytest.raises(SystemExit):
        check.check_seo({**GOOD, "title": "א" * 61})
    assert "seo.title" in capsys.readouterr().out


@pytest.mark.parametrize("bad", [
    {"name": "data.gov.il"},
    {"keywords": []},
    {"alternate_names": "not a list"},
    {"title": "שורה\rשנייה"},
    {"alternate_names": ["שם\nשני"]},
])
def test_check_py_rejects_bad_seo(bad):
    with pytest.raises(SystemExit):
        check.check_seo({**GOOD, **bad})


def _publish(tmp_path, seo):
    src = _src(dataset_id="aaa", with_agent=True)
    src.agent_data["seo"] = seo
    publish.publish(tmp_path, store=_store_mock([src]))
    return json.loads((tmp_path / "datasets/aaa/agent_data.json").read_text())


def test_publish_writes_seo_to_agent_data_json(tmp_path):
    agent = _publish(tmp_path, GOOD)
    assert agent["seo"]["name"] == "פנקס הרופאים"
    assert agent["seo"]["title"] == "איתור רופא לפי מספר רישיון"


def test_publish_drops_only_a_malformed_seo(tmp_path):
    """A builder image older than SeoMeta stores seo unvalidated: a bad one
    costs the seo block, never the page's summary."""
    agent = _publish(tmp_path, {"title": "א" * 200})
    assert "seo" not in agent
    assert agent["summary_he"] == "סיכום של המאגר"
