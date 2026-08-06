"""The page-builder agent loop — shared by production and local testing.

Drives any model through the agent tool surface (`bash`,
`code_execution`, `web_fetch`, `web_search`) using **PydanticAI**, on a
pluggable sandbox backend:

- production (`agent_runner.py`): `LocalSandbox` — subprocesses with a
  private per-session workdir inside the builder container.
- local testing (`run_test_session` + `cli/model_test.py`):
  `PodmanSandbox` — a rootless Podman container (needs the extra deps
  in requirements-test.txt).

Single implementation per concern (per `feedback_one_path_default` memory):

- Agent loop  : PydanticAI `Agent` (`run_agent_session`)
- web_fetch   : `httpx`
- web_search  : `duckduckgo-search` (DDG)
- System prompt: `agent/system-prompt.md` (canonical, hand-edited);
  per-session paths arrive via the user message (OUTPUTS_DIR /
  CHECK_SCRIPT) so the prompt stays byte-identical across sessions
  for provider prefix caching.

The `model` parameter accepts two forms:
- `<vendor>/<model>` — an OpenRouter model id (`minimax/minimax-m3`,
  `moonshotai/kimi-k2.6`, `x-ai/grok-4.3`, `anthropic/claude-sonnet-4-6`,
  …; browse https://openrouter.ai/models). Routed via PydanticAI's
  `OpenRouterModel`; needs `OPENROUTER_API_KEY`. Usage accounting is on,
  so `cost.json` carries the **actual billed USD** (incl. provider cache
  discounts — the hand-priced estimates were ~6× off for MiniMax direct
  because its compat endpoint hides cache reads). `reasoning_details`
  round-trip on history replay, which interleaved-thinking models
  (MiniMax, Kimi) need for stable tool loops.
- `anthropic:claude-…` — PydanticAI's native Anthropic provider; needs
  `ANTHROPIC_API_KEY`. Kept for calibration runs; cost falls back to the
  static Anthropic price table.

`run_agent_session` returns RAW outputs — validation/persistence belong
to the caller (`agent_runner` in prod; `run_test_session` writes local
artifacts and touches neither Firestore nor GCS).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn, Optional, Sequence

import httpx
from pydantic_ai import Agent, ModelRetry, RunContext

from .agent_contract import (
    CHECK_SCRIPT_PATH,
    PrefetchedResource,
    build_user_message,
    fetch_resource_preview,
    prefetch_dataset,
    run_host_check,
    sanitize_content_html,
)
from .schema import AgentData

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_PROMPT_PATH = REPO_ROOT / "agent" / "system-prompt.md"
# Fixed paths used by the Podman test harness (one session per container,
# so they never collide). Production (LocalSandbox) passes per-session
# paths instead.
CHECK_SCRIPT_IN_SANDBOX = "/tmp/session/uploads/check.py"
DATA_DIR_IN_SANDBOX = "/tmp/session/data"

CONTENT_FILENAME = "content.html"
AGENT_DATA_FILENAME = "agent_data.json"
OUTPUTS_DIR_IN_SANDBOX = "/tmp/session/outputs"

# Browser UA the data.gov.il WAF requires (data_gov_il_api_quirks memory).
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

STDOUT_CAP_BYTES = 100_000
WEB_FETCH_CAP_BYTES = 200_000
SEARCH_SNIPPET_CAP = 2_000

# Fallback prices ($/1M tokens). Cost is assembled per response, most
# accurate source first: inline OpenRouter usage accounting (with BYOK —
# our MiniMax setup — the credits `cost` is ~0/None and the real spend is
# `upstream_inference_cost`; both are summed), then the /api/v1/generation
# stats endpoint for responses that arrive without cost fields, then this
# table (cache-aware: cached input priced at the `cached` rate). The
# table is also the only source for the native `anthropic:` path.
PRICE_TABLE: dict[str, dict[str, float]] = {
    "minimax/minimax-m3":          {"input": 0.30, "cached": 0.06, "output": 1.20},
    "anthropic:claude-sonnet-4-6": {"input": 3.00, "cached": 0.30, "output": 15.00},
    "anthropic:claude-haiku-4-5":  {"input": 1.00, "cached": 0.10, "output": 5.00},
    "anthropic:claude-opus-4-7":   {"input": 5.00, "cached": 0.50, "output": 25.00},
}


def _truncate(s: str | list[str], cap: int) -> str:
    if isinstance(s, list):
        s = "".join(s)
    if len(s) <= cap:
        return s
    return s[:cap] + f"\n... [truncated {len(s) - cap} bytes]"


def _exec_to_dict(exe) -> dict:
    """Convert a `_Execution` (PodmanSandbox) into the JSON-able dict the
    PydanticAI tool layer returns to the model."""
    return {
        "stdout": _truncate(exe.logs.stdout or "", STDOUT_CAP_BYTES),
        "stderr": _truncate(exe.logs.stderr or "", STDOUT_CAP_BYTES),
        "error": (
            {"name": exe.error.name, "value": exe.error.value}
            if exe.error else None
        ),
    }


@dataclass
class Deps:
    """Live resources injected into every tool call via RunContext."""
    sandbox: Any                   # PodmanSandbox
    httpx_client: httpx.Client
    bash_calls: int = 0
    code_calls: int = 0
    fetch_calls: int = 0
    search_calls: int = 0
    # Consecutive tool calls that arrived with no payload. Reset by any
    # successful call — see `_note_empty_tool_call`.
    empty_calls: int = 0
    # Used only for verbose log labelling; harmless if left default.
    dataset_id: str = ""


class EmptyToolCallLoop(RuntimeError):
    """The model is wedged emitting tool calls with no payload.

    Deliberately NOT a ModelRetry: it has to escape the agent loop rather
    than buy the model another round trip. `agent_runner` catches it and
    restarts the session on a fresh workdir, which is the only thing
    observed to clear this state.
    """


def _empty_call_limit() -> int:
    """Consecutive empty calls tolerated before the attempt is abandoned.

    Floor of 1 so the model always gets told what was wrong at least once
    before the attempt dies.
    """
    try:
        return max(1, int(os.environ.get("MAX_EMPTY_TOOL_CALLS", "2")))
    except ValueError:
        return 2


def _note_empty_tool_call(deps: Any, tool: str, dataset_id: str) -> NoReturn:
    """Handle a tool call that arrived with no payload. Always raises.

    One empty call is worth a nudge — models occasionally emit one and
    recover on the next turn. A *run* of them is a wedge: in prod each extra
    round trip replays the whole transcript at reasoning effort max (~2 min
    apiece), and with the agent's retries=5 that burnt ~14 minutes per
    occurrence before discarding the attempt's work anyway. Fail fast
    instead; the fresh-workdir restart is what actually recovers.
    """
    deps.empty_calls += 1
    limit = _empty_call_limit()
    if deps.empty_calls >= limit:
        log.warning(
            "test[%s]: %s — %d consecutive empty calls (limit %d), abandoning "
            "attempt instead of burning more round trips",
            dataset_id[:8], tool, deps.empty_calls, limit,
        )
        raise EmptyToolCallLoop(
            f"{tool} received {deps.empty_calls} consecutive calls with an "
            f"empty payload — the model is not making progress; restarting "
            f"the session on a fresh workdir"
        )
    raise ModelRetry(
        f"{tool} requires a non-empty payload. The sandbox is persistent — "
        "there is nothing to restart. If you have completed all "
        "investigation and written content.html and agent_data.json to the "
        "outputs directory, end the run by returning a final assistant "
        "message instead of calling a tool."
    )


def _log_stall_diagnostics(messages: Any, dataset_id: str, *, last: int = 5) -> None:
    """Log finish_reason + output-token counts for the final few responses.

    The two stall modes look identical from outside: a tool call whose
    arguments arrive empty, and a final turn carrying only a ThinkingPart.
    They separate on `finish_reason` — a `length` stop means the completion
    budget (shared with reasoning tokens at effort=max) ran out mid-call,
    which is a max_tokens problem rather than a prompt problem. Without this
    the distinction is unrecoverable from logs after the fact.
    """
    try:
        responses = [
            m for m in messages if getattr(m, "kind", None) == "response"
        ][-last:]
        for i, m in enumerate(responses, 1):
            details = getattr(m, "provider_details", None)
            details = details if isinstance(details, dict) else {}
            usage = getattr(m, "usage", None)
            parts = [type(p).__name__ for p in getattr(m, "parts", [])]
            log.warning(
                "session[%s]: response[-%d] finish_reason=%s native=%s "
                "output_tokens=%s parts=%s",
                dataset_id[:8],
                len(responses) - i + 1,
                getattr(m, "finish_reason", None),
                details.get("native_finish_reason"),
                getattr(usage, "output_tokens", None),
                ",".join(parts) or "(none)",
            )
    except Exception:  # diagnostics must never mask the real failure
        log.warning("session[%s]: stall diagnostics unavailable", dataset_id[:8])


def _summarize_arg(s: str, cap: int = 80) -> str:
    """One-line preview of a tool argument for log lines."""
    s = (s or "").strip().replace("\n", " ⏎ ")
    return s if len(s) <= cap else s[:cap - 1] + "…"


def _summarize_run_result(d: dict) -> str:
    """One-line outcome summary for bash/code_execution result dicts."""
    out = (d.get("stdout") or "")
    err = (d.get("stderr") or "")
    err_tag = f" stderr={len(err)}B" if err else ""
    err_flag = f" error={d['error']!r}" if d.get("error") else ""
    return f"stdout={len(out)}B{err_tag}{err_flag}"


@dataclass
class TestSessionResult:
    dataset_id: str
    model: str
    out_dir: Path
    content_html_path: Path
    agent_data_path: Path
    transcript_path: Path
    cost_path: Path
    iterations: int
    elapsed_seconds: float
    usage: dict[str, int]
    cost_usd: dict[str, float]
    sandbox_files: list[str] = field(default_factory=list)
    host_check: str = "passed"


# Base64 chunk size per bash command when provisioning files into the
# sandbox. Podman exec rejects args past ~128 KB ("Argument list too
# long" at 466 KB, observed 2026-07-10), so stay well under that.
_PROVISION_CHUNK_B64_CHARS = 60_000


def _provision_file(sandbox, data: bytes, target: str) -> None:
    """Write `data` to `target` inside the sandbox.

    LocalSandbox exposes its workdir on the host, so targets under it are
    written directly (prod's data-prefetch CSV lands in one syscall).
    Otherwise (Podman) fall back to a base64 round-trip — the session has
    no file-write API (see _Files.read for the inverse) — chunked to stay
    under the exec arg limit.
    """
    import base64

    workdir = getattr(sandbox, "workdir", None)
    if workdir is not None:
        try:
            t = Path(target).resolve()
            wd = Path(workdir).resolve()
            if t.is_relative_to(wd):
                t.parent.mkdir(parents=True, exist_ok=True)
                t.write_bytes(data)
                return
        except OSError as e:
            log.warning(
                "direct write of %s failed (%s) — falling back to base64", target, e
            )

    b64 = base64.b64encode(data).decode("ascii")
    target_dir = target.rsplit("/", 1)[0]
    exe = sandbox.run_code(
        f"mkdir -p {target_dir} && : > {target}.b64", language="bash", timeout=30
    )
    if exe.error:
        raise RuntimeError(
            f"failed to provision {target} in sandbox: {exe.error.value}: "
            f"{exe.logs.stderr}"
        )
    for i in range(0, len(b64), _PROVISION_CHUNK_B64_CHARS):
        chunk = b64[i : i + _PROVISION_CHUNK_B64_CHARS]
        exe = sandbox.run_code(
            f"printf %s {chunk} >> {target}.b64", language="bash", timeout=60
        )
        if exe.error:
            raise RuntimeError(
                f"failed to provision {target} in sandbox: {exe.error.value}: "
                f"{exe.logs.stderr}"
            )
    exe = sandbox.run_code(
        f"base64 -d < {target}.b64 > {target} && rm {target}.b64",
        language="bash",
        timeout=60,
    )
    if exe.error:
        raise RuntimeError(
            f"failed to provision {target} in sandbox: {exe.error.value}: "
            f"{exe.logs.stderr}"
        )


# Base64 fallback is O(size/60KB) exec calls — fine for a check script,
# unusable for a 150 MB CSV. Above this, a missing fast path is an error.
_PROVISION_B64_MAX_BYTES = 5_000_000


def _provision_path(sandbox, src: Path, target: str) -> None:
    """Provision a host file into the sandbox at `target`, cheaply.

    LocalSandbox (prod): hardlink into the workdir — zero-copy across the
    up-to-3 attempts that reuse one prefetched file — falling back to a
    plain copy across filesystems. PodmanSandbox: `copy_to_runtime`
    (tar upload; the broken-tar quirk only affects copy FROM the runtime).
    Last resort: the chunked-base64 writer, small files only.
    """
    workdir = getattr(sandbox, "workdir", None)
    if workdir is not None:
        try:
            t = Path(target).resolve()
            if t.is_relative_to(Path(workdir).resolve()):
                t.parent.mkdir(parents=True, exist_ok=True)
                t.unlink(missing_ok=True)
                try:
                    os.link(src, t)
                except OSError:
                    import shutil

                    shutil.copyfile(src, t)
                return
        except OSError as e:
            log.warning(
                "direct provision of %s failed (%s) — trying sandbox copy", target, e
            )
    copy_in = getattr(sandbox, "copy_in", None)
    if copy_in is not None:
        copy_in(src, target)
        return
    size = src.stat().st_size
    if size > _PROVISION_B64_MAX_BYTES:
        raise RuntimeError(
            f"no fast provisioning path for {target} ({size} bytes) — "
            "base64 fallback is only for small files"
        )
    _provision_file(sandbox, src.read_bytes(), target)


def _provision_check_script(sandbox, target: str = CHECK_SCRIPT_IN_SANDBOX) -> None:
    """Copy agent/skills/check.py into the sandbox at `target` — the
    CHECK_SCRIPT path the session's user message advertises. check.py is
    argv-driven, so any path works.
    """
    if not CHECK_SCRIPT_PATH.exists():
        raise FileNotFoundError(
            f"{CHECK_SCRIPT_PATH} missing — the system prompt's self-check "
            "step depends on it"
        )
    _provision_file(sandbox, CHECK_SCRIPT_PATH.read_bytes(), target)
    exe = sandbox.run_code(
        f"python3 -c \"import ast; ast.parse(open('{target}').read())\"",
        language="bash",
        timeout=30,
    )
    if exe.error:
        raise RuntimeError(
            f"provisioned check.py failed to parse: {exe.error.value}: "
            f"{exe.logs.stderr}"
        )


def _load_system_prompt() -> str:
    if not SYSTEM_PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"{SYSTEM_PROMPT_PATH} missing — the canonical agent system "
            "prompt must ship with the code (and the container image)"
        )
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def _build_pydantic_model(
    model_id: str, reasoning_effort: Optional[str] = None
) -> tuple[Any, dict[str, Any]]:
    """Resolve a model id to (PydanticAI model handle, model_settings).

    Two accepted forms:
    - `<vendor>/<model>` — OpenRouter id, routed via `OpenRouterModel`
      with usage accounting enabled (actual billed cost lands in each
      response's `provider_details['cost']`). Needs OPENROUTER_API_KEY.
    - `anthropic:<model>` — PydanticAI's native Anthropic provider,
      kept for harness-vs-Managed-Agents calibration runs.

    The settings dict always carries the load-bearing `max_tokens`
    ceiling (see _build_agent) plus any provider-specific keys.
    `reasoning_effort` (OpenAI-style: none/minimal/low/medium/high/xhigh)
    is forwarded as OpenRouter's `reasoning.effort`; None keeps the
    model's default (what production runs use).
    """
    base_settings: dict[str, Any] = {"max_tokens": 16384}

    if "/" in model_id:
        from pydantic_ai.models.openrouter import OpenRouterModel
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                f"model={model_id!r} is an OpenRouter id but "
                "OPENROUTER_API_KEY is not set"
            )
        # Richer prefetched data → bigger pages → the single write-content
        # heredoc response can push past 16384 and get its tool call dropped
        # mid-stream (same pydantic-ai truncation class as the 4096→16384
        # bump; two observed 2026-07-10 sessions died exactly at that step).
        # Raised 32768 → 128000 on 2026-08-06. At
        # OPENROUTER_REASONING_EFFORT=max the reasoning trace draws on this
        # same completion budget, so a turn can spend the whole allowance
        # thinking and then emit a truncated tool call (empty `command`) or
        # nothing but a ThinkingPart — the two stall modes that cost ~47% of
        # session time that day.
        #
        # 128000 is hy3's advertised max_completion_tokens (context is
        # 262144, so a full-size completion still leaves ~134k for the
        # prompt). Do NOT set this to the 131072 that the older comment
        # here implied: that exceeds the completion ceiling. Check
        # `top_provider.max_completion_tokens` from
        # https://openrouter.ai/api/v1/models before changing models.
        # Costs nothing unless actually generated. Env-overridable to bisect.
        base_settings["max_tokens"] = int(
            os.environ.get("OPENROUTER_MAX_TOKENS", "128000")
        )
        # `usage.include` asks OpenRouter for usage accounting: the final
        # response carries billed cost + cached-token counts, which the
        # OpenRouterModel maps into provider_details / RequestUsage.
        base_settings["openrouter_usage"] = {"include": True}
        if reasoning_effort:
            base_settings["openrouter_reasoning"] = {"effort": reasoning_effort}
        return (
            OpenRouterModel(model_id, provider=OpenRouterProvider(api_key=api_key)),
            base_settings,
        )

    if model_id.startswith("anthropic:"):
        if reasoning_effort:
            raise RuntimeError(
                "reasoning_effort is only supported on the OpenRouter path"
            )
        return model_id, base_settings

    raise RuntimeError(
        f"model={model_id!r} not recognized. Use an OpenRouter id "
        "(<vendor>/<model>, e.g. minimax/minimax-m3 — browse "
        "https://openrouter.ai/models) or anthropic:<model> for the "
        "native calibration path."
    )


def _build_agent(
    *, model, system_prompt: str, model_settings: dict[str, Any]
) -> Agent[Deps, str]:
    # retries=5 + an explicit max_tokens ceiling (in model_settings, set by
    # _build_pydantic_model). The token bump is a real bug-fix, not a
    # defensive knob: Anthropic's streaming adapter (and the corresponding
    # PydanticAI parser path) drops tool_use input arguments when the
    # response hits max_tokens mid-stream, leaving the tool call with
    # `input={}`. Pre-1.91 PydanticAI silently surfaced the truncated
    # call to the agent loop, which then looked like the model emitting
    # empty bash calls. Sonnet's bash heredocs (multi-KB python scripts in
    # `cat <<PY ... PY`) routinely push past 4096 — the previous default.
    # See pydantic-ai #3118 + PR #3137.
    # retries=2 (was 5) is the backstop for wedge loops the `bash` guard
    # can't see. `code_execution` takes a required `code: str`, so a call
    # with empty arguments is rejected by PydanticAI's own validation and
    # retried internally without ever reaching the tool body — that path
    # burnt all five retries in prod on 2026-08-06. ModelRetry is raised in
    # exactly one place in this module (empty `bash`), so lowering the
    # budget costs no legitimate recovery.
    agent = Agent(
        model=model,
        deps_type=Deps,
        system_prompt=system_prompt,
        retries=2,
        model_settings=model_settings,
    )

    @agent.tool
    def bash(
        ctx: RunContext[Deps],
        command: str | None = None,
        restart: bool = False,
    ) -> dict:
        """Run a shell command inside the sandbox (state persists between calls).

        Args:
            command: shell command. cwd, exported env, and written files persist.
            restart: ignored — the sandbox already provides a fresh persistent
                shell per session. Accepted only for compatibility with models
                trained on the Anthropic Managed Agents bash tool surface.
        """
        ctx.deps.bash_calls += 1
        n = ctx.deps.bash_calls
        ds = ctx.deps.dataset_id[:8]
        if not command:
            log.info(
                "test[%s]: bash#%d empty call (restart=%s)", ds, n, restart,
            )
            _note_empty_tool_call(ctx.deps, "bash", ds)  # always raises
        ctx.deps.empty_calls = 0
        log.info("test[%s]: bash#%d $ %s", ds, n, _summarize_arg(command))
        t0 = time.monotonic()
        out = _exec_to_dict(ctx.deps.sandbox.run_code(command, language="bash", timeout=120))
        log.info(
            "test[%s]: bash#%d done in %.1fs — %s",
            ds, n, time.monotonic() - t0, _summarize_run_result(out),
        )
        return out

    @agent.tool
    def code_execution(ctx: RunContext[Deps], code: str) -> dict:
        """Execute Python in the sandbox.

        Args:
            code: Python source.
        """
        ctx.deps.code_calls += 1
        n = ctx.deps.code_calls
        ds = ctx.deps.dataset_id[:8]
        log.info("test[%s]: python#%d >>> %s", ds, n, _summarize_arg(code))
        t0 = time.monotonic()
        out = _exec_to_dict(ctx.deps.sandbox.run_code(code, language="python", timeout=120))
        log.info(
            "test[%s]: python#%d done in %.1fs — %s",
            ds, n, time.monotonic() - t0, _summarize_run_result(out),
        )
        return out

    @agent.tool
    def web_fetch(ctx: RunContext[Deps], url: str) -> dict:
        """Fetch a URL over HTTPS, returning the text body (HTML/JSON/etc).

        Args:
            url: fully-qualified http(s) URL.
        """
        ctx.deps.fetch_calls += 1
        n = ctx.deps.fetch_calls
        ds = ctx.deps.dataset_id[:8]
        log.info("test[%s]: fetch#%d %s", ds, n, _summarize_arg(url, cap=120))
        t0 = time.monotonic()
        try:
            r = ctx.deps.httpx_client.get(
                url,
                headers={"User-Agent": BROWSER_UA, "Accept": "*/*"},
                timeout=30.0,
                follow_redirects=True,
            )
        except httpx.HTTPError as e:
            log.info(
                "test[%s]: fetch#%d failed in %.1fs — %s",
                ds, n, time.monotonic() - t0, type(e).__name__,
            )
            return {"status": 0, "error": f"{type(e).__name__}: {e}", "text": ""}
        body = _truncate(r.text, WEB_FETCH_CAP_BYTES)
        log.info(
            "test[%s]: fetch#%d done in %.1fs — status=%d body=%dB",
            ds, n, time.monotonic() - t0, r.status_code, len(body),
        )
        return {
            "status": r.status_code,
            "content_type": r.headers.get("content-type", ""),
            "url": str(r.url),
            "text": body,
        }

    @agent.tool
    def web_search(ctx: RunContext[Deps], query: str, max_results: int = 5) -> dict:
        """Search the public web (DuckDuckGo), returning titles + URLs + snippets.

        Args:
            query: search query (any language).
            max_results: 1-10.
        """
        ctx.deps.search_calls += 1
        n = ctx.deps.search_calls
        ds = ctx.deps.dataset_id[:8]
        max_results = max(1, min(int(max_results or 5), 10))
        log.info("test[%s]: search#%d %r (max=%d)", ds, n, _summarize_arg(query), max_results)
        t0 = time.monotonic()
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddg:
                hits = list(ddg.text(query, max_results=max_results))
        except Exception as e:
            log.info(
                "test[%s]: search#%d failed in %.1fs — %s",
                ds, n, time.monotonic() - t0, type(e).__name__,
            )
            return {"error": f"{type(e).__name__}: {e}", "results": []}
        results = [
            {
                "title": h.get("title", ""),
                "url": h.get("href") or h.get("url") or "",
                "snippet": _truncate(h.get("body") or h.get("snippet") or "", SEARCH_SNIPPET_CAP),
            }
            for h in hits[:max_results]
        ]
        log.info(
            "test[%s]: search#%d done in %.1fs — %d results",
            ds, n, time.monotonic() - t0, len(results),
        )
        return {"results": results}

    return agent


def _serialize_messages(messages: list) -> list[dict]:
    out = []
    for m in messages:
        try:
            out.append(m.model_dump(mode="json"))
        except Exception:
            out.append({"_repr": repr(m)})
    return out


def _safe_dump(obj) -> dict:
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return {}


def _extract_usage(result_usage) -> dict[str, int]:
    u = result_usage if isinstance(result_usage, dict) else _safe_dump(result_usage)
    input_tokens = int(u.get("input_tokens") or u.get("request_tokens") or 0)
    output_tokens = int(u.get("output_tokens") or u.get("response_tokens") or 0)
    total = int(u.get("total_tokens") or (input_tokens + output_tokens))
    # PydanticAI's RequestUsage/RunUsage carry cache counts as top-level
    # fields; the `details` sub-dict only holds leftover provider extras.
    details = u.get("details") or {}
    cache_read = int(
        u.get("cache_read_tokens")
        or details.get("cache_read_input_tokens")
        or details.get("cached_tokens")
        or details.get("prompt_cache_hit_tokens")
        or 0
    )
    cache_write = int(
        u.get("cache_write_tokens")
        or details.get("cache_creation_input_tokens")
        or details.get("cache_write_tokens")
        or 0
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
    }


GENERATION_API_URL = "https://openrouter.ai/api/v1/generation"


def _fetch_generation_cost(
    gen_id: str, api_key: str, *, retries: int = 4, backoff_s: float = 1.0
) -> Optional[float]:
    """Authoritative billed USD for one generation, from OpenRouter's
    stats endpoint. `total_cost` is the OpenRouter credits charged; with
    BYOK (our MiniMax setup) that is ~0 and the real spend is
    `upstream_inference_cost` — sum both. Stats lag the response
    (observed live: 404 AND 200-with-null-cost for ~2-3s), so not-ready
    shapes are retried with backoff. Returns None on give-up — the
    caller estimates instead.
    """
    for attempt in range(retries):
        if attempt:
            time.sleep(backoff_s * attempt)
        try:
            r = httpx.get(
                GENERATION_API_URL,
                params={"id": gen_id},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
            if r.status_code == 404:  # stats not materialized yet
                continue
            r.raise_for_status()
            data = (r.json() or {}).get("data") or {}
            total_cost = data.get("total_cost")
            upstream = data.get("upstream_inference_cost")
            if total_cost is not None or upstream is not None:
                return float(total_cost or 0.0) + float(upstream or 0.0)
        except Exception as e:
            log.debug("generation stats fetch failed for %s: %s", gen_id, e)
    return None


def _estimate_response_cost(
    prices: dict[str, float], response_usage
) -> Optional[float]:
    u = _extract_usage(response_usage or {})
    cached = u["cache_read_tokens"]
    uncached_input = max(u["input_tokens"] - cached, 0)
    return (
        uncached_input * prices["input"]
        + cached * prices["cached"]
        + u["output_tokens"] * prices["output"]
    ) / 1_000_000


def _compute_cost(*, model: str, usage: dict[str, int], messages: list) -> dict[str, Any]:
    """Assemble the run's billed USD per response, most-accurate source
    first: inline OpenRouter usage accounting (`provider_details['cost']`,
    net of cache discounts) → the `/api/v1/generation` stats endpoint for
    responses that intermittently arrive without cost fields → a
    cache-aware PRICE_TABLE estimate. `cost_source` records the mix.
    """
    prices = PRICE_TABLE.get(model)
    api_key = os.environ.get("OPENROUTER_API_KEY") if "/" in model else None

    responses = [m for m in messages if getattr(m, "kind", None) == "response"]
    total = 0.0
    inline = fetched = estimated = 0
    missing: list[Any] = []
    for m in responses:
        details = getattr(m, "provider_details", None)
        if not isinstance(details, dict):
            missing.append(m)
            continue
        # OpenRouter credits charged. With BYOK this is ~0 and the real
        # spend is what the upstream provider bills — sum both.
        cost = details.get("cost")
        upstream = details.get("upstream_inference_cost")
        if cost is not None or upstream is not None:
            total += float(cost or 0.0) + float(upstream or 0.0)
            inline += 1
        else:
            missing.append(m)

    if missing and "/" in model:
        log.warning(
            "%d/%d responses carried no OpenRouter cost for model=%s — "
            "fetching generation stats", len(missing), len(responses), model,
        )
    for m in missing:
        gen_id = getattr(m, "provider_response_id", None)
        cost = (
            _fetch_generation_cost(gen_id, api_key)
            if gen_id and api_key
            else None
        )
        if cost is not None:
            total += cost
            fetched += 1
        elif prices is not None:
            total += _estimate_response_cost(prices, getattr(m, "usage", None))
            estimated += 1

    breakdown = {
        "responses": len(responses),
        "inline": inline,
        "fetched": fetched,
        "estimated": estimated,
    }
    covered = inline + fetched + estimated
    note = None
    if covered == 0:
        if prices is None:
            return {
                "tokens_usd": None,
                "total_usd": None,
                "cost_source": None,
                "breakdown": breakdown,
                "note": "no OpenRouter cost in responses and model not in PRICE_TABLE",
            }
        # No per-response data at all (e.g. odd message shapes) — fall
        # back to a run-level table estimate from aggregate usage.
        total = _estimate_response_cost(prices, usage)
        breakdown["estimated"] = estimated = len(responses) or 1
    elif covered < len(responses):
        # Unpriced model with responses we couldn't cost — keep the
        # partial sum but flag the gap instead of silently undercounting.
        note = f"{len(responses) - covered} responses unpriced"

    if estimated == 0 and fetched == 0:
        source = "openrouter"
    elif estimated == 0:
        source = "openrouter+api"
    elif inline or fetched:
        source = "openrouter+estimate"
    else:
        source = "price_table"
    out: dict[str, Any] = {
        "tokens_usd": round(total, 6),
        "total_usd": round(total, 6),  # only cost component
        "cost_source": source,
        "breakdown": breakdown,
    }
    if note:
        out["note"] = note
    return out


@dataclass
class AgentSessionOutput:
    """Raw result of one agent session — not yet validated or persisted."""
    content_html_raw: str
    agent_data_raw: bytes
    usage: dict[str, int]
    cost: dict[str, Any]
    iterations: int
    tool_calls: dict[str, int]
    messages: list
    elapsed_seconds: float


def run_agent_session(
    *,
    sandbox,
    model: str,
    dataset_id: str,
    title: str,
    notes: str,
    org_title: str,
    primary_resource_id: Optional[str],
    outputs_dir: str,
    check_script: str,
    pre_fetched_schema: Optional[dict] = None,
    prefetched: Sequence[PrefetchedResource] = (),
    data_dir: Optional[str] = None,
    previous_failure: Optional[str] = None,
    related_candidates: Sequence[dict] = (),
    reasoning_effort: Optional[str] = None,
) -> AgentSessionOutput:
    """Drive one agent session on an already-created sandbox.

    Shared by production (`agent_runner`, LocalSandbox) and the local
    test harness (`run_test_session`, PodmanSandbox). Provisions
    check.py at `check_script` and every prefetched data file under
    `data_dir`, runs the PydanticAI loop, and returns the RAW outputs +
    telemetry — validation, sanitizing, and persistence are the caller's
    responsibility.
    """
    system_prompt = _load_system_prompt()
    data_files = [p for p in prefetched if p.host_path and p.sandbox_filename]
    if data_files and not data_dir:
        raise ValueError("prefetched data files require data_dir")
    user_msg = build_user_message(
        dataset_id=dataset_id,
        title=title,
        notes=notes,
        org_title=org_title,
        primary_resource_id=primary_resource_id,
        outputs_dir=outputs_dir,
        check_script=check_script,
        pre_fetched_schema=pre_fetched_schema,
        prefetched=prefetched,
        data_dir=data_dir,
        previous_failure=previous_failure,
        related_candidates=related_candidates,
    )
    httpx_client = httpx.Client()
    deps = Deps(sandbox=sandbox, httpx_client=httpx_client, dataset_id=dataset_id)
    started = time.monotonic()
    try:
        _provision_check_script(sandbox, check_script)
        for p in data_files:
            target = f"{data_dir.rstrip('/')}/{p.sandbox_filename}"
            _provision_path(sandbox, p.host_path, target)
            log.info(
                "session[%s]: provisioned %s (%s, %d rows) at %s",
                dataset_id[:8], p.sandbox_filename, p.mode, p.rows, target,
            )
        py_model, model_settings = _build_pydantic_model(model, reasoning_effort)
        agent = _build_agent(
            model=py_model, system_prompt=system_prompt, model_settings=model_settings
        )
        log.info("session[%s]: agent.run_sync model=%s", dataset_id[:8], model)
        result = agent.run_sync(user_msg, deps=deps)
        elapsed = time.monotonic() - started

        od = outputs_dir.rstrip("/")
        try:
            content_html_bytes = sandbox.files.read(f"{od}/{CONTENT_FILENAME}")
            agent_data_bytes = sandbox.files.read(f"{od}/{AGENT_DATA_FILENAME}")
        except Exception as e:
            # Diagnose before raising: did the agent write elsewhere, or did
            # its final response lose a tool call (max_tokens truncation)?
            try:
                exe = sandbox.run_code(
                    f"find /tmp/session /tmp/work {od} -maxdepth 3 -type f "
                    "2>/dev/null | head -40",
                    language="bash",
                    timeout=15,
                )
                log.warning(
                    "session[%s]: outputs missing; sandbox files:\n%s",
                    dataset_id[:8], (exe.logs.stdout or "(none)")[:1500],
                )
            except Exception:
                pass
            try:
                parts = getattr(result.all_messages()[-1], "parts", [])
                log.warning(
                    "session[%s]: final message parts: %s",
                    dataset_id[:8],
                    "; ".join(
                        f"{type(p).__name__}:{str(getattr(p, 'content', ''))[:200]}"
                        for p in parts
                    )[:1200],
                )
            except Exception:
                pass
            _log_stall_diagnostics(result.all_messages(), dataset_id)
            raise RuntimeError(
                f"agent did not produce both output files: {e}"
            ) from e
    finally:
        try:
            httpx_client.close()
        except Exception:
            pass

    messages = result.all_messages()
    usage = _extract_usage(result.usage)
    iterations = sum(
        1 for m in messages
        if hasattr(m, "parts") and any(
            type(p).__name__ in ("ToolCallPart", "ToolReturnPart") for p in m.parts
        )
    )
    return AgentSessionOutput(
        content_html_raw=(
            content_html_bytes.decode("utf-8")
            if isinstance(content_html_bytes, (bytes, bytearray))
            else str(content_html_bytes)
        ),
        agent_data_raw=(
            bytes(agent_data_bytes)
            if isinstance(agent_data_bytes, (bytes, bytearray))
            else str(agent_data_bytes).encode("utf-8")
        ),
        usage=usage,
        cost=_compute_cost(model=model, usage=usage, messages=messages),
        iterations=iterations,
        tool_calls={
            "bash": deps.bash_calls,
            "code_execution": deps.code_calls,
            "web_fetch": deps.fetch_calls,
            "web_search": deps.search_calls,
        },
        messages=messages,
        elapsed_seconds=round(elapsed, 2),
    )


def run_test_session(
    *,
    dataset_id: str,
    title: str,
    notes: str,
    org_title: str,
    primary_resource_id: Optional[str],
    out_dir: Path,
    model: str,
    resources: Optional[list] = None,
    related_candidates: Sequence[dict] = (),
    max_iters: int = 30,  # noqa: ARG001 - PydanticAI controls retries; kept for caller parity
    reasoning_effort: Optional[str] = None,
) -> TestSessionResult:
    """Local test run: Podman sandbox, artifacts written to `out_dir`.

    Manual-run only — never imported by production code.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    from .podman_sandbox import PodmanSandbox

    # Same host-side schema + data prefetch as run_production_session — the
    # user message must be identical for an apples-to-apples model comparison.
    pre_fetched_schema: Optional[dict] = None
    prefetched: list[PrefetchedResource] = []
    if resources:
        prefetched = prefetch_dataset(resources, out_dir / "prefetch")
        log.info(
            "test[%s]: prefetched %d resource(s): %s",
            dataset_id[:8],
            len(prefetched),
            ", ".join(f"{p.sandbox_filename or p.resource_id[:8]}({p.mode})"
                      for p in prefetched) or "-",
        )
    elif primary_resource_id:
        # Legacy caller without the full resource list — schema-only.
        pre_fetched_schema = fetch_resource_preview(primary_resource_id)

    log.info(
        "test[%s]: starting Podman sandbox + model=%s%s",
        dataset_id[:8], model,
        f" (reasoning_effort={reasoning_effort})" if reasoning_effort else "",
    )
    sandbox = PodmanSandbox.create()
    try:
        out = run_agent_session(
            sandbox=sandbox,
            model=model,
            dataset_id=dataset_id,
            title=title,
            notes=notes,
            org_title=org_title,
            primary_resource_id=primary_resource_id,
            outputs_dir=OUTPUTS_DIR_IN_SANDBOX,
            check_script=CHECK_SCRIPT_IN_SANDBOX,
            pre_fetched_schema=pre_fetched_schema,
            prefetched=prefetched,
            data_dir=DATA_DIR_IN_SANDBOX,
            related_candidates=related_candidates,
            reasoning_effort=reasoning_effort,
        )
        sandbox_files: list[str] = []
        try:
            for entry in sandbox.files.list(OUTPUTS_DIR_IN_SANDBOX):
                sandbox_files.append(getattr(entry, "name", str(entry)))
        except Exception:
            pass
    finally:
        try:
            sandbox.kill()
        except Exception as e:
            log.warning("test[%s]: sandbox.kill failed: %s", dataset_id[:8], e)

    content_html = sanitize_content_html(out.content_html_raw, dataset_id=dataset_id)
    agent_data = AgentData.model_validate_json(out.agent_data_raw)

    # Same authoritative gate as production (agent_runner). Single attempt
    # here — a failure is reported, not retried, so eval runs surface it.
    try:
        run_host_check(
            content_html, agent_data.model_dump_json(exclude_none=True), out_dir
        )
        host_check = "passed"
    except Exception as e:
        host_check = str(e)
        log.warning("test[%s]: %s", dataset_id[:8], host_check[:300])

    content_html_path = out_dir / CONTENT_FILENAME
    agent_data_path = out_dir / AGENT_DATA_FILENAME
    transcript_path = out_dir / "transcript.json"
    cost_path = out_dir / "cost.json"

    content_html_path.write_text(content_html, encoding="utf-8")
    agent_data_path.write_text(
        json.dumps(agent_data.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    transcript_path.write_text(
        json.dumps(_serialize_messages(out.messages), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    cost_path.write_text(
        json.dumps(
            {
                "model": model,
                "reasoning_effort": reasoning_effort,
                "elapsed_seconds": out.elapsed_seconds,
                "usage": out.usage,
                "cost_usd": out.cost,
                "tool_calls": out.tool_calls,
                "sandbox_files": sandbox_files,
                "host_check": host_check,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return TestSessionResult(
        dataset_id=dataset_id,
        model=model,
        out_dir=out_dir,
        content_html_path=content_html_path,
        agent_data_path=agent_data_path,
        transcript_path=transcript_path,
        cost_path=cost_path,
        iterations=out.iterations,
        elapsed_seconds=out.elapsed_seconds,
        usage=out.usage,
        cost_usd=out.cost,
        sandbox_files=sandbox_files,
        host_check=host_check,
    )
