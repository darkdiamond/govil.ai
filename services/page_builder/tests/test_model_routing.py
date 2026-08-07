"""Per-model provider routing + serving-provider capture.

Two things are under test:

1. The quantization floor is **per model**, not global. deepseek-v4-flash is
   the only model whose OpenRouter pool contains fp4 endpoints (DeepInfra,
   Io Net), so it gets an fp8 floor; hy3 (4x fp8, 1x bf16) and minimax-m3 must
   keep an untouched provider set — a blanket filter would exclude hy3's bf16
   endpoint, which is *higher* precision than fp8.
2. The serving provider is recorded, so a run's output can be attributed to a
   precision level. Its absence is what made the 2026-08-07 eval ambiguous.

Run: pytest services/page_builder/tests/test_model_routing.py
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from services.page_builder import model_harness as mh


@dataclass
class FakeResponse:
    kind: str = "response"
    provider_details: Optional[dict] = None


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """These tests are about defaults — keep ambient env out of them."""
    monkeypatch.delenv("OPENROUTER_QUANTIZATIONS", raising=False)
    monkeypatch.delenv("OPENROUTER_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-used")


def _settings(model: str, effort=None, quants=None) -> dict:
    _, settings = mh._build_pydantic_model(model, effort, quants)
    return settings


# ------------------------------------------------------- routing floors

def test_deepseek_flash_gets_fp8_floor():
    s = _settings("deepseek/deepseek-v4-flash-0731")
    assert s["openrouter_provider"] == {"quantizations": ["fp8"]}


def test_require_parameters_is_never_sent():
    """OpenRouter 404s this request when require_parameters is set (bisected
    2026-08-07), so no routing row may reintroduce it."""
    for model in ("deepseek/deepseek-v4-flash-0731", "tencent/hy3"):
        assert "require_parameters" not in _settings(model).get(
            "openrouter_provider", {}
        )
    assert not any(
        "require_parameters" in cfg for cfg in mh.MODEL_ROUTING.values()
    )


def test_routing_matches_by_family_prefix():
    """A future dated revision must inherit the floor without a code change."""
    s = _settings("deepseek/deepseek-v4-flash-99999999")
    assert s["openrouter_provider"]["quantizations"] == ["fp8"]


@pytest.mark.parametrize(
    "model", ["tencent/hy3", "minimax/minimax-m3", "openai/gpt-5.6-luna"]
)
def test_other_models_get_no_provider_block(model):
    """Prod routing must be untouched: hy3's bf16 endpoint stays eligible."""
    assert "openrouter_provider" not in _settings(model)


def test_explicit_quantizations_override_the_floor():
    """The A/B lever: reproduce fp4 deliberately."""
    s = _settings("deepseek/deepseek-v4-flash-0731", None, ["fp4"])
    assert s["openrouter_provider"]["quantizations"] == ["fp4"]


def test_env_override_applies_to_a_model_without_a_floor(monkeypatch):
    monkeypatch.setenv("OPENROUTER_QUANTIZATIONS", "fp8, bf16")
    s = _settings("tencent/hy3")
    assert s["openrouter_provider"] == {"quantizations": ["fp8", "bf16"]}


# ------------------------------------------------------ effort precedence

def test_effort_precedence_explicit_beats_env_and_floor(monkeypatch):
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "low")
    assert mh.resolve_reasoning_effort(
        "deepseek/deepseek-v4-flash-0731", "high") == "high"


def test_effort_precedence_env_beats_floor(monkeypatch):
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "low")
    assert mh.resolve_reasoning_effort("deepseek/deepseek-v4-flash-0731") == "low"


def test_deepseek_defaults_to_max_effort():
    assert mh.resolve_reasoning_effort("deepseek/deepseek-v4-flash-0731") == "max"


def test_model_without_a_floor_has_no_effort_default():
    assert mh.resolve_reasoning_effort("tencent/hy3") is None


def test_resolved_effort_reaches_the_request():
    s = _settings("deepseek/deepseek-v4-flash-0731",
                  mh.resolve_reasoning_effort("deepseek/deepseek-v4-flash-0731"))
    assert s["openrouter_reasoning"] == {"effort": "max"}


# --------------------------------------------------- provider capture

def test_collects_distinct_providers_in_first_seen_order():
    msgs = [
        FakeResponse(provider_details={"downstream_provider": "DeepInfra"}),
        FakeResponse(provider_details={"downstream_provider": "BaseTen"}),
        FakeResponse(provider_details={"downstream_provider": "DeepInfra"}),
    ]
    assert mh._collect_providers(msgs) == ["DeepInfra", "BaseTen"]


def test_provider_capture_tolerates_missing_details():
    msgs = [
        FakeResponse(provider_details=None),
        FakeResponse(provider_details={"cost": 0.01}),  # no provider key
        FakeResponse(kind="request", provider_details={"downstream_provider": "X"}),
        FakeResponse(provider_details={"downstream_provider": "Novita"}),
    ]
    assert mh._collect_providers(msgs) == ["Novita"]


def test_no_providers_is_empty_not_error():
    assert mh._collect_providers([]) == []
