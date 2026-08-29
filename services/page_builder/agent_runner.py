"""Production session runner — one dataset, end-to-end, self-validating.

Replaces the Anthropic Managed Agents `session_runner`. Flow per dataset:

    1. Host-side CKAN prefetch (`prefetch_dataset`): schema previews + full
       or sampled CSV exports of the dataset's datastore resources, fetched
       once and provisioned into every attempt's sandbox.
    2. Up to SESSION_ATTEMPTS (default 3) attempts, each on a fresh
       LocalSandbox workdir:
         a. run the PydanticAI agent session (model_harness.run_agent_session,
            OpenRouter model from OPENROUTER_MODEL)
         b. validate: both files exist → AgentData schema → sanitizer →
            host-side agent/skills/check.py exit 0 on the SANITIZED body.
       A failed attempt (known MiniMax API flakes, missing outputs, or
       validation) logs and retries; only after all attempts fail does the
       dataset count as failed for this run.
    3. On success only: upload content.html to GCS staging and persist
       agent_data + usage/cost telemetry to the Firestore source doc.

The pipeline marks analysis_status around this call; a raised exception
here → mark_analysis_failed (which increments failed_attempts so the
selector can retry on subsequent days, max 3).
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from services.shared.firestore import FirestoreStateStore
from services.shared.resources import pick_primary_resource_id

from .agent_contract import (
    PrefetchedResource,
    prefetch_dataset,
    run_host_check,
    sanitize_content_html,
)
from .local_sandbox import LocalSandbox
from .model_harness import (
    AGENT_DATA_FILENAME,
    CONTENT_FILENAME,
    AgentSessionOutput,
    run_agent_session,
)
from .schema import AgentData

log = logging.getLogger(__name__)

DEFAULT_MODEL = "tencent/hy3"
SESSIONS_ROOT = Path(os.environ.get("SESSIONS_ROOT", "/tmp/sessions"))


@dataclass
class ProdSessionResult:
    dataset_id: str
    model: str
    session_id: str
    attempts: int
    elapsed_seconds: float
    usage: dict[str, int]
    cost: dict
    written: list[str] = field(default_factory=list)

    # Back-compat accessors for pipeline summary fields.
    @property
    def events_seen(self) -> int:
        return 0


class AccountLimitError(RuntimeError):
    """The account/key — not this dataset — is what the provider rejected.

    Raised instead of the generic all-attempts-failed RuntimeError when
    OpenRouter refuses the request for a reason no dataset can influence:
    a dead key, exhausted credits, or a key spend cap. Retrying is not just
    futile, it is destructive — the source did nothing wrong, so it must
    not spend `failed_attempts` on a condition it cannot outlive.

    2026-08-11 is why this type exists: the key hit its $10 total cap, and
    for 18 days the batch treated the resulting 403 as an ordinary flake —
    3 instant attempts x 10 sources every morning, `failed_attempts`
    incremented each pass, until 29 sources sat parked at >=3 and the site
    had not published a page since.
    """


# Account-level rejections on the completions endpoint. 401 (bad or
# disabled key) and 402 (out of credits) are unambiguous. 403 is NOT — it
# is also what a moderation block returns — so it only counts when the body
# names a limit/credit problem. Keeping that distinction is the difference
# between "the account is down, stop the batch" and "one unlucky dataset
# tripped moderation", which must stay an ordinary retryable failure.
_ACCOUNT_STATUS_CODES = (401, 402)
_ACCOUNT_LIMIT_MARKERS = (
    "key limit exceeded",
    "insufficient credits",
    "more credits are required",
    "negative credit balance",
    "quota exceeded",
)


def _names_account_limit(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _ACCOUNT_LIMIT_MARKERS)


def _is_fatal_account_error(err: BaseException) -> bool:
    """True when the provider rejected us for an account-level reason.

    Walks __cause__/__context__ like `_is_rate_limited` — by the time the
    pipeline sees it the provider error is wrapped in a RuntimeError.

    429 is excluded up front: "Rate limit exceeded" would otherwise trip the
    marker sniff, and a rate limit is transient congestion with its own
    backoff path, not a dead account.
    """
    if _is_rate_limited(err):
        return False
    seen: set[int] = set()
    e: Optional[BaseException] = err
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        code = getattr(e, "status_code", None)
        if code in _ACCOUNT_STATUS_CODES:
            return True
        if code == 403 and _names_account_limit(str(e)):
            return True
        e = e.__cause__ or e.__context__
    return _names_account_limit(str(err))


def _is_rate_limited(err: BaseException) -> bool:
    """True when the failure is an HTTP 429 anywhere in the exception chain.

    PydanticAI surfaces provider errors as ModelHTTPError with a
    `status_code` attribute; other layers may wrap it, so walk
    __cause__/__context__ before falling back to a string sniff.
    """
    seen: set[int] = set()
    e: Optional[BaseException] = err
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if getattr(e, "status_code", None) == 429:
            return True
        e = e.__cause__ or e.__context__
    return "429" in str(err)


def _validation_failure_hint(e: BaseException) -> Optional[str]:
    """A retry-worthy diagnostic for VALIDATION failures only.

    API flakes (malformed tool JSON, finish_reason=error, HTTP errors)
    return None — a clean fresh context is precisely how those are
    absorbed, and the flake isn't actionable by the model.
    """
    from pydantic import ValidationError

    if isinstance(e, ValidationError):
        return f"agent_data.json failed AgentData schema validation: {str(e)[:400]}"
    if isinstance(e, RuntimeError):
        msg = str(e)
        if "self-check failed" in msg or "did not produce both output files" in msg:
            return msg[:400]
    if isinstance(e, ValueError):
        return f"output validation failed: {str(e)[:400]}"
    return None


def _write_gcs(data: bytes, bucket: str, relpath: str) -> str:
    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(bucket).blob(relpath)
    blob.upload_from_string(data, content_type="text/html; charset=utf-8")
    return f"gs://{bucket}/{relpath}"


def run_production_session(
    *,
    dataset_id: str,
    title: str,
    notes: str,
    org_title: str,
    resources: Optional[list] = None,
    organization: Optional[dict] = None,
    primary_resource_id: Optional[str] = None,
    gcs_bucket: str,
    store: Optional[FirestoreStateStore] = None,
    model: Optional[str] = None,
) -> ProdSessionResult:
    if not gcs_bucket:
        raise ValueError("gcs_bucket is required")
    model = model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    attempts_max = int(os.environ.get("SESSION_ATTEMPTS", "3"))
    retry_feedback = (
        (os.environ.get("RETRY_FEEDBACK") or "").strip().lower()
        in ("1", "true", "yes", "on")
    )
    reasoning_effort = (
        (os.environ.get("OPENROUTER_REASONING_EFFORT") or "").strip() or None
    )
    rate_limit_backoff_s = int(os.environ.get("RATE_LIMIT_BACKOFF_S", "60"))
    store = store or FirestoreStateStore()
    session_id = f"or-{uuid.uuid4().hex[:12]}"
    started = time.monotonic()

    if resources and not primary_resource_id:
        primary_resource_id = pick_primary_resource_id(resources)
    if not resources and primary_resource_id:
        # Legacy caller with a bare resource id — synthesize the minimal
        # record prefetch_dataset needs (a wrong datastore_active guess
        # just costs one failed preview → schema-less session, as before).
        resources = [
            {
                "id": primary_resource_id,
                "name": "",
                "format": "CSV",
                "datastore_active": True,
            }
        ]

    SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    # Prefetch once per source (schema previews + data files); the same
    # files are provisioned into every attempt's sandbox. Raises
    # ResourceRestrictedError only when the PRIMARY resource is 403-parked.
    prefetch_dir = Path(
        tempfile.mkdtemp(prefix=f"{dataset_id[:8]}-prefetch-", dir=SESSIONS_ROOT)
    )
    prefetched: list[PrefetchedResource] = []
    try:
        prefetched = prefetch_dataset(resources, prefetch_dir)
    except Exception:
        shutil.rmtree(prefetch_dir, ignore_errors=True)
        raise
    if prefetched:
        log.info(
            "session[%s]: prefetched %d resource(s): %s (%s bytes total)",
            dataset_id[:8],
            len(prefetched),
            ", ".join(
                f"{p.sandbox_filename or p.resource_id[:8]}:{p.mode}"
                for p in prefetched
            ),
            f"{sum(p.host_path.stat().st_size for p in prefetched if p.host_path):,}",
        )
    # Same-ministry related candidates from our own index — the agent picks
    # related_ids from this list instead of 3-5 CKAN discovery calls (each
    # of which replays the whole transcript as input tokens). Best-effort:
    # an empty list just re-enables the agent's package_search fallback.
    related_candidates: list[dict] = []
    try:
        org_name = (organization or {}).get("name") or ""
        if org_name:
            related_candidates = [
                {"id": s.id, "title": s.title, "tags": s.tags}
                for s in store.list_org_sources(org_name, exclude_id=dataset_id)
            ]
    except Exception:
        log.exception("related-candidates lookup failed for %s", dataset_id)

    prefetch_stats = {
        "files": sum(1 for p in prefetched if p.host_path),
        "total_bytes": sum(
            p.host_path.stat().st_size for p in prefetched if p.host_path
        ),
        "sampled": sum(1 for p in prefetched if p.mode == "sample"),
    }

    last_err: Optional[BaseException] = None
    out: Optional[AgentSessionOutput] = None
    content_html: Optional[str] = None
    agent_data: Optional[AgentData] = None
    attempts = 0
    failure_hint: Optional[str] = None

    # Spend across ALL attempts, including ones that returned output but
    # failed validation — the closest match to the OpenRouter dashboard.
    # Attempts that die mid-run (API error) never return usage, so their
    # spend stays invisible here; the dashboard remains the authority.
    attempts_cost = 0.0

    try:
        for attempt in range(1, attempts_max + 1):
            attempts = attempt
            workdir = Path(
                tempfile.mkdtemp(
                    prefix=f"{dataset_id[:8]}-a{attempt}-", dir=SESSIONS_ROOT
                )
            )
            sandbox = LocalSandbox.create(workdir)
            try:
                out = run_agent_session(
                    sandbox=sandbox,
                    model=model,
                    dataset_id=dataset_id,
                    title=title,
                    notes=notes,
                    org_title=org_title,
                    primary_resource_id=primary_resource_id,
                    outputs_dir=str(workdir / "outputs"),
                    check_script=str(workdir / "check.py"),
                    prefetched=prefetched,
                    data_dir=str(workdir / "data"),
                    previous_failure=failure_hint,
                    related_candidates=related_candidates,
                    reasoning_effort=reasoning_effort,
                )
                attempts_cost += out.cost.get("total_usd") or 0.0
                agent_data = AgentData.model_validate_json(out.agent_data_raw)
                content_html = sanitize_content_html(
                    out.content_html_raw, dataset_id=dataset_id
                )
                run_host_check(
                    content_html,
                    agent_data.model_dump_json(exclude_none=True),
                    workdir,
                )
                log.info(
                    "session[%s]: attempt %d/%d validated (iters=%d, $%.4f %s)",
                    dataset_id[:8], attempt, attempts_max, out.iterations,
                    out.cost.get("total_usd") or 0.0, out.cost.get("cost_source"),
                )
                break
            except Exception as e:
                last_err = e
                # An account-level rejection is not a flake and cannot be
                # retried out of: every remaining attempt (and every other
                # source in the batch) would get the same 403. Bail on the
                # first one so a dead key costs 1 call, not SESSION_ATTEMPTS
                # x DAILY_CAP, and so the caller can tell "the account is
                # down" apart from "this dataset failed".
                if _is_fatal_account_error(e):
                    log.error(
                        "session[%s]: account-level provider rejection on "
                        "attempt %d — aborting without retry: %s",
                        dataset_id[:8], attempt, str(e)[:300],
                    )
                    raise AccountLimitError(
                        f"provider rejected the account while building "
                        f"{dataset_id}: {e}"
                    ) from e
                # RETRY_FEEDBACK: hand the next (fresh-context) attempt the
                # validation diagnostic so it doesn't re-trip the same rule.
                # API flakes keep passing None — fresh is how they're absorbed.
                failure_hint = (
                    _validation_failure_hint(e) if retry_feedback else None
                )
                log.warning(
                    "session[%s]: attempt %d/%d failed%s: %s",
                    dataset_id[:8], attempt, attempts_max,
                    " (hint→retry)" if failure_hint else "",
                    str(e)[:300],
                )
                # Rate limits are transient congestion, not model flakes —
                # an instant retry just burns the remaining attempts inside
                # the same 429 window. Back off (linear per attempt) so the
                # window can pass. Non-429 failures keep retrying instantly.
                if attempt < attempts_max and _is_rate_limited(e):
                    delay = rate_limit_backoff_s * attempt
                    log.info(
                        "session[%s]: rate-limited — backing off %ds before "
                        "attempt %d/%d",
                        dataset_id[:8], delay, attempt + 1, attempts_max,
                    )
                    time.sleep(delay)
            finally:
                sandbox.kill()
        else:
            raise RuntimeError(
                f"all {attempts_max} attempts failed for {dataset_id}; "
                f"last error: {last_err}"
            ) from last_err
    finally:
        shutil.rmtree(prefetch_dir, ignore_errors=True)

    assert out is not None and content_html is not None and agent_data is not None

    written = [
        _write_gcs(
            content_html.encode("utf-8"),
            gcs_bucket,
            f"datasets/{dataset_id}/{CONTENT_FILENAME}",
        )
    ]
    store.set_agent_data(
        dataset_id, agent_data.model_dump(mode="json", exclude_none=True)
    )

    elapsed = round(time.monotonic() - started, 2)
    try:
        store.set_session_usage(
            dataset_id,
            usage={
                **out.usage,
                "actual_cost_usd": out.cost.get("total_usd"),
                "attempts_cost_usd": round(attempts_cost, 6),
                "cost_source": out.cost.get("cost_source"),
                "cost_breakdown": out.cost.get("breakdown"),
                "model": model,
                "reasoning_effort": reasoning_effort,
                "attempts": attempts,
                "prefetch": prefetch_stats,
            },
            model_requests=out.iterations,
            elapsed_s=elapsed,
            session_id=session_id,
            agent_version=None,
        )
    except Exception:
        # Telemetry failure must never fail a run.
        log.exception("failed to persist last_usage for %s", dataset_id)

    log.info(
        "session[%s]: done in %.1fs (attempts=%d, tokens=%s, cost=%s)",
        dataset_id[:8], elapsed, attempts, out.usage.get("total_tokens"),
        out.cost.get("total_usd"),
    )
    return ProdSessionResult(
        dataset_id=dataset_id,
        model=model,
        session_id=session_id,
        attempts=attempts,
        elapsed_seconds=elapsed,
        usage=out.usage,
        cost=out.cost,
        written=written,
    )
