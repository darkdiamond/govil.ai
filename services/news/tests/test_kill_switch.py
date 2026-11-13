"""The kill switch: the job's NEWS_PUBLISH env and `news_state/control` in the
`news` database. Either one saying off stops a live run; a missing doc follows
the env; a flag that can't be read counts as off."""
from __future__ import annotations

import json

import pytest

from services.news import admin, run
from services.news import store as store_mod
from services.news.tests.test_hourly import CURSOR, _Articles, _full_path, live_gates
from services.news.tests.test_window import _Db


@pytest.fixture
def live(monkeypatch):
    return live_gates(monkeypatch)


def _summary(capsys):
    return json.loads(capsys.readouterr().out.splitlines()[-1])


# ── the run ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("flag", ["off", "OFF", "paused"])
def test_flag_off_stops_a_live_run_before_the_lease(live, monkeypatch, capsys, flag):
    lease, probes = live
    monkeypatch.setattr(_Articles, "publish_flag", flag.strip().lower())
    assert run.main([]) == 0
    s = _summary(capsys)
    assert s["status"] == "disabled" and "news_state/control" in s["reason"]
    assert lease["calls"] == [] and probes == []
    assert _Articles.cursor == CURSOR


def test_unreadable_flag_counts_as_off_and_fails_the_run(live, monkeypatch, capsys, caplog):
    lease, probes = live
    monkeypatch.setattr(_Articles, "publish_flag", RuntimeError("firestore down"))
    assert run.main([]) == 1
    s = _summary(capsys)
    assert s["status"] == "failed" and "kill switch unreadable" in s["error"]
    assert lease["calls"] == [] and probes == []
    assert "treating the kill switch as off" in caplog.text


@pytest.mark.parametrize("flag", [None, "live"])
def test_missing_or_live_flag_follows_the_env(live, monkeypatch, tmp_path, capsys, flag):
    lease, _probes = live
    monkeypatch.setattr(_Articles, "publish_flag", flag)
    _full_path(monkeypatch, tmp_path)
    assert run.main(["--no-catalog", "--no-demand", "--no-tables", "--no-images"]) == 0
    assert _summary(capsys)["status"] in ("idle", "ok")
    assert lease["calls"][0][0] == "acquire"


def test_env_off_wins_over_a_live_flag(live, monkeypatch, capsys):
    monkeypatch.setenv("NEWS_PUBLISH", "off")
    monkeypatch.setattr(_Articles, "publish_flag", "live")
    assert run.main([]) == 0
    assert _summary(capsys)["status"] == "disabled"
    assert _Articles.constructed == 0   # the env is checked first, without Firestore


def test_ad_hoc_live_run_opens_the_store_for_the_flag(live, monkeypatch, capsys):
    monkeypatch.setattr(_Articles, "publish_flag", "off")
    assert run.main(["--since-hours", "2"]) == 0
    assert _summary(capsys)["status"] == "disabled"
    assert _Articles.constructed == 1


def test_signals_only_never_reads_the_flag(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(run, "_kill_switch", lambda *_a: pytest.fail("read the kill switch"))
    monkeypatch.delenv("NEWS_PUBLISH", raising=False)
    assert run.main(["--signals-only", "--models-dir", str(tmp_path), "--no-catalog",
                     "--no-demand", "--json"]) == 0


# ── the store + admin ───────────────────────────────────────────────────

def test_store_reads_and_writes_the_flag():
    db = _Db()
    st = store_mod.FirestoreArticles(client=db)
    assert st.read_publish_flag() is None
    st.set_publish_flag("off")
    assert st.read_publish_flag() == "off"
    assert db.data["news_state/control"]["publish"] == "off"
    st.set_publish_flag("live")
    assert st.read_publish_flag() == "live"
    with pytest.raises(ValueError):
        st.set_publish_flag("on")
    db.data["news_state/control"] = {"at": "x"}   # no field: the env decides
    assert st.read_publish_flag() is None


@pytest.fixture
def admin_db(monkeypatch):
    db = _Db()
    real = store_mod.FirestoreArticles
    monkeypatch.setattr(store_mod, "FirestoreArticles", lambda: real(client=db))
    return db


def test_admin_publish_off_on_status(admin_db, capsys):
    assert admin.main(["publish", "status"]) == 0
    assert "not set" in capsys.readouterr().out
    assert admin.main(["publish", "off"]) == 0
    assert admin_db.data["news_state/control"]["publish"] == "off"
    assert "publish=off" in capsys.readouterr().out
    assert admin.main(["publish", "on"]) == 0
    assert admin_db.data["news_state/control"]["publish"] == "live"
    out = capsys.readouterr()
    assert "publish=live" in out.out and "NEWS_PUBLISH" in out.err


def test_admin_publish_rejects_other_modes(admin_db):
    with pytest.raises(SystemExit):
        admin.main(["publish", "live"])
    assert admin_db.data == {}
