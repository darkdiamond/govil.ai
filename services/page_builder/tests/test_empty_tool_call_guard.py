"""Fail fast when the model wedges on empty tool calls.

Observed in production 2026-08-06: the model emits a `bash` call with no
`command`, the harness raises ModelRetry, and it emits another — six times in
a row in one session. With `retries=5` each of those is a full-transcript
replay at reasoning effort max (~2 min each in prod), so a wedged model burnt
~14 minutes and then discarded twelve productive tool calls anyway when the
attempt restarted. Nothing has ever recovered mid-run; only a fresh workdir
does. So nudge once, then bail.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic_ai import ModelRetry

from services.page_builder.model_harness import (
    EmptyToolCallLoop,
    _empty_call_limit,
    _note_empty_tool_call,
)


def _deps() -> MagicMock:
    d = MagicMock()
    d.empty_calls = 0
    return d


def test_first_empty_call_is_a_retryable_nudge():
    deps = _deps()
    with pytest.raises(ModelRetry) as e:
        _note_empty_tool_call(deps, "bash", "abc12345")
    assert "non-empty" in str(e.value)
    assert deps.empty_calls == 1


def test_second_consecutive_empty_call_ends_the_attempt():
    deps = _deps()
    with pytest.raises(ModelRetry):
        _note_empty_tool_call(deps, "bash", "abc12345")
    with pytest.raises(EmptyToolCallLoop) as e:
        _note_empty_tool_call(deps, "bash", "abc12345")
    assert "bash" in str(e.value)


def test_terminal_error_is_not_a_model_retry():
    """It must escape the agent loop, not feed another round trip into it."""
    deps = _deps()
    deps.empty_calls = 5
    with pytest.raises(EmptyToolCallLoop) as e:
        _note_empty_tool_call(deps, "code_execution", "abc12345")
    assert not isinstance(e.value, ModelRetry)


def test_counter_reset_restores_the_nudge():
    """A stray empty call followed by real work must not poison the session."""
    deps = _deps()
    with pytest.raises(ModelRetry):
        _note_empty_tool_call(deps, "bash", "abc12345")
    deps.empty_calls = 0  # what a successful tool call does
    with pytest.raises(ModelRetry):
        _note_empty_tool_call(deps, "bash", "abc12345")


def test_limit_is_env_tunable(monkeypatch):
    monkeypatch.setenv("MAX_EMPTY_TOOL_CALLS", "4")
    assert _empty_call_limit() == 4


def test_limit_survives_a_garbage_env_value(monkeypatch):
    monkeypatch.setenv("MAX_EMPTY_TOOL_CALLS", "not-a-number")
    assert _empty_call_limit() == 2


def test_limit_never_drops_below_one(monkeypatch):
    """0 would fail the attempt before the model is ever told what went wrong."""
    monkeypatch.setenv("MAX_EMPTY_TOOL_CALLS", "0")
    assert _empty_call_limit() == 1
