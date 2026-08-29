"""Account-level provider rejections must fast-fail, not burn the batch.

Regression cover for the 2026-08-11 outage: the OpenRouter key hit its
total spend cap, every session 403'd with "Key limit exceeded", and the
runner treated it as an ordinary per-source flake — 3 instant attempts per
source, 10 sources a day, `failed_attempts` incremented every time. 18 days
later 29 sources were parked at >=3 and the site had not updated once.
"""
from unittest.mock import MagicMock

import pytest

from services.page_builder.agent_runner import (
    AccountLimitError,
    _is_fatal_account_error,
)


class _FakeModelHTTPError(Exception):
    def __init__(self, status_code: int, msg: str = "provider error"):
        super().__init__(msg)
        self.status_code = status_code


KEY_LIMIT_BODY = (
    "status_code: 403, model_name: tencent/hy3, body: {'message': "
    "'Key limit exceeded (total limit). Manage it using "
    "https://openrouter.ai/workspaces/default/keys/29f124d5', 'code': 403}"
)


# --- the exact production shape -------------------------------------------


def test_the_real_403_key_limit_is_fatal():
    assert _is_fatal_account_error(_FakeModelHTTPError(403, KEY_LIMIT_BODY))


def test_wrapped_key_limit_via_cause():
    """agent_runner wraps the provider error in RuntimeError before it
    reaches the pipeline — the chain walk has to see through that."""
    try:
        try:
            raise _FakeModelHTTPError(403, KEY_LIMIT_BODY)
        except Exception as inner:
            raise RuntimeError("all 3 attempts failed for abc") from inner
    except RuntimeError as outer:
        assert _is_fatal_account_error(outer)


def test_string_fallback_without_status_code():
    assert _is_fatal_account_error(Exception(KEY_LIMIT_BODY))


# --- other account-level rejections ---------------------------------------


def test_401_invalid_key_is_fatal():
    assert _is_fatal_account_error(_FakeModelHTTPError(401, "No auth credentials"))


def test_402_insufficient_credits_is_fatal():
    assert _is_fatal_account_error(
        _FakeModelHTTPError(402, "Insufficient credits to run this request")
    )


# --- the discriminations that keep this from over-firing ------------------


def test_403_moderation_is_NOT_an_account_error():
    """OpenRouter returns 403 for moderation-flagged input too. That one IS
    this dataset's fault and must stay an ordinary retryable failure —
    otherwise one unlucky dataset aborts the whole daily batch."""
    assert not _is_fatal_account_error(
        _FakeModelHTTPError(403, "Your input was flagged by moderation")
    )


def test_429_rate_limit_is_NOT_an_account_error():
    """'Rate limit exceeded' contains 'limit exceeded'. A 429 is transient
    congestion with its own backoff path and must not be hijacked here."""
    err = _FakeModelHTTPError(429, "Rate limit exceeded: free-models-per-day")
    assert not _is_fatal_account_error(err)


def test_500_and_validation_errors_are_not_account_errors():
    assert not _is_fatal_account_error(_FakeModelHTTPError(500, "provider down"))
    assert not _is_fatal_account_error(ValueError("Expecting value: line 621"))


def test_account_limit_error_is_a_runtime_error():
    """The pipeline's generic `except Exception` still catches it if the
    dedicated handler is ever removed — fail safe, not silent."""
    assert issubclass(AccountLimitError, RuntimeError)


# --- the loop must not burn the remaining attempts -------------------------


def test_fatal_account_error_stops_after_one_attempt(monkeypatch, tmp_path):
    """The whole point: 1 doomed call, not SESSION_ATTEMPTS of them."""
    from services.page_builder import agent_runner

    calls = {"n": 0}

    def _boom(**kwargs):
        calls["n"] += 1
        raise _FakeModelHTTPError(403, KEY_LIMIT_BODY)

    monkeypatch.setattr(agent_runner, "run_agent_session", _boom)
    monkeypatch.setattr(agent_runner, "prefetch_dataset", lambda *a, **k: [])
    monkeypatch.setattr(agent_runner, "SESSIONS_ROOT", tmp_path)
    monkeypatch.setenv("SESSION_ATTEMPTS", "3")

    store = MagicMock()
    store.list_org_sources.return_value = []

    with pytest.raises(AccountLimitError):
        agent_runner.run_production_session(
            dataset_id="d1",
            title="t",
            notes="",
            org_title="o",
            primary_resource_id="r1",
            gcs_bucket="b",
            store=store,
        )

    assert calls["n"] == 1, f"burned {calls['n']} attempts on an account limit"
