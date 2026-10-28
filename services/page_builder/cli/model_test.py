"""CLI: run any model (via OpenRouter) against one or more CKAN datasets.

Local-only benchmark. It runs production's session path
(`agent_runner.run_validated_session`), whose agent tools are plain
subprocesses, so run it inside the production image via:

    infra/benchmark.sh --source <dataset_id> --model minimax/minimax-m3

A direct `python -m` run refuses to start unless ALLOW_HOST_SANDBOX=1.

Model ids are OpenRouter ids (`<vendor>/<model>` — browse
https://openrouter.ai/models), or `anthropic:claude-…` for the native
calibration path. cost.json reports the actual billed USD for
OpenRouter runs (usage accounting), not a table estimate.

Outputs land in `tmp/model_test/<id>/{content.html,agent_data.json,transcript.json,cost.json}`.
To preview a build inside the actual Nuxt shell — and compare it visually
to the live prod page on govil.ai — use:

    python -m services.page_builder.cli.preview render <id>     # offline file://
    python -m services.page_builder.cli.preview swap <id>       # full Nuxt-shell
    python -m services.page_builder.cli.preview restore <id>

Read-only on prod Firestore. Writes nothing to GCS or Firestore.

Examples:
    infra/benchmark.sh --source <id> --model minimax/minimax-m3
    infra/benchmark.sh --batch <id1> <id2> --model moonshotai/kimi-k2.6
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from services.page_builder.agent_runner import AccountLimitError, related_candidates_for
from services.page_builder.model_harness import TestSessionResult, run_test_session
from services.shared.firestore import FirestoreStateStore, SourceRecord
from services.shared.resources import pick_primary_resource_id

REPO_ROOT = Path(__file__).resolve().parents[3]
PROD_DATASETS_DIR = REPO_ROOT / "frontend" / "public" / "datasets"
DEFAULT_OUT_DIR = REPO_ROOT / "tmp" / "model_test"

log = logging.getLogger(__name__)


def _load_source(store: FirestoreStateStore, dataset_id: str) -> SourceRecord:
    src = store.get_source(dataset_id)
    if src is None:
        raise SystemExit(f"source not found in Firestore: {dataset_id}")
    return src


class SnapshotStore:
    """Read-only stand-in for FirestoreStateStore, backed by a JSON file.

    `infra/benchmark.sh` runs this CLI inside the production image, where
    agent-driven subprocesses can read any file the container can. Mounting
    the developer's Google credentials there would hand them to model-written
    code, so the host dumps the two things a session needs from Firestore
    (the source doc and the same-ministry candidates) with `--snapshot-out`,
    and the container reads that file instead.
    """

    def __init__(self, path: str):
        self._d = json.loads(Path(path).read_text(encoding="utf-8"))

    def get_source(self, dataset_id: str):
        row = self._d.get(dataset_id)
        if row is None:
            return None
        return SimpleNamespace(id=dataset_id, **row["source"])

    def list_org_sources(self, org_name: str, exclude_id: str = "", limit: int = 15):
        # Keyed by dataset: the snapshot already holds exactly what
        # FirestoreStateStore.list_org_sources(org, exclude_id=<it>) returned.
        rows = (self._d.get(exclude_id) or {}).get("org_sources") or []
        return [SimpleNamespace(**r) for r in rows]


def write_snapshot(store: FirestoreStateStore, ids: list[str], path: str) -> None:
    out: dict[str, dict] = {}
    for did in ids:
        src = _load_source(store, did)
        org = src.organization if isinstance(src.organization, dict) else None
        # The exact lookup run_validated_session does, so the container's
        # SnapshotStore replays the same candidates.
        org_sources = related_candidates_for(store, org, did)
        out[did] = {
            "source": {
                "title": src.title,
                "notes": src.notes,
                "organization": src.organization,
                "resources": src.resources,
            },
            "org_sources": org_sources,
        }
    Path(path).write_text(
        json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8"
    )


def _pick_auto_trio() -> list[str]:
    """Pick one dataset each of dataset_kind ∈ {map, timeseries, registry} from
    the already-built prod pages, preferring smaller resources for fast runs."""
    by_kind: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for d in PROD_DATASETS_DIR.iterdir():
        if not d.is_dir():
            continue
        agent_data_path = d / "agent_data.json"
        data_path = d / "data.json"
        if not agent_data_path.exists():
            continue
        try:
            ad = json.loads(agent_data_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        kind = ad.get("dataset_kind") or "misc"
        size_hint = 0
        if data_path.exists():
            try:
                meta = json.loads(data_path.read_text(encoding="utf-8"))
                size_hint = int(meta.get("record_count") or 0)
            except Exception:
                pass
        by_kind[kind].append((size_hint, d.name))

    picks: list[str] = []
    for kind in ("registry", "timeseries", "map"):
        candidates = sorted(by_kind.get(kind) or [])
        if candidates:
            picks.append(candidates[0][1])
    return picks


def _print_summary(res) -> None:
    cost = res.cost_usd
    usage = res.usage
    if cost.get("total_usd") is not None:
        source = cost.get("cost_source") or "?"
        tag = {
            "openrouter": "actual billed",
            "openrouter+api": "actual billed (some fetched from stats API)",
            "openrouter+estimate": "billed + partial table estimate",
        }.get(source, "table estimate")
        cost_line = f"  $: {cost['total_usd']:.4f} ({tag})"
        if (res.attempts or 1) > 1 and res.attempts_cost_usd is not None:
            cost_line += (
                f"; all {res.attempts} attempts: {res.attempts_cost_usd:.4f}"
            )
    else:
        cost_line = f"  $: unknown ({cost.get('note', '')})"
    providers = getattr(res, "providers", None) or []
    provider_line = (
        f"  provider: {', '.join(providers)}\n" if providers else ""
    )
    check = res.host_check
    check_line = (
        "  host check: passed"
        if check == "passed"
        else f"  host check: FAILED — {check[:200]}"
    )
    print(
        f"\n=== {res.dataset_id} (model={res.model}) ===\n"
        f"  out: {res.out_dir}\n"
        f"  attempts: {res.attempts}, iterations: {res.iterations}, "
        f"elapsed: {res.elapsed_seconds:.1f}s"
        f"{f' (wall {res.wall_seconds:.1f}s)' if res.wall_seconds else ''}\n"
        f"  tokens: in={usage['input_tokens']:,} out={usage['output_tokens']:,} "
        f"cached={usage['cache_read_tokens']:,} total={usage['total_tokens']:,}\n"
        f"{provider_line}"
        f"{cost_line}\n"
        f"{check_line}\n"
        f"  files: {res.content_html_path.name}, {res.agent_data_path.name}, "
        f"transcript.json, cost.json"
    )


def _spend(r) -> Optional[float]:
    """Spend across every attempt, not just the validated one — a model that
    needs retries must not look cheaper than it billed.

    attempts_cost_usd sums `total_usd or 0.0`, so it reads 0.0 (not None)
    for an unpriced run; gate on the validated attempt's price, or an
    unpriced model would show up as a priced $0.
    """
    validated = (r.cost_usd or {}).get("total_usd")
    if validated is None:
        return None
    return r.attempts_cost_usd if r.attempts_cost_usd is not None else validated


def _in_container() -> bool:
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


def _require_isolation() -> None:
    """Agent tools are subprocesses of this process (LocalSandbox), as in
    production, so the container is the only thing between model-written
    shell and the developer's home directory. Refuse to run bare."""
    if _in_container() or os.environ.get("ALLOW_HOST_SANDBOX") == "1":
        return
    raise SystemExit(
        "refusing to run agent tools on the host: use infra/benchmark.sh "
        "(runs this CLI in the production image under Podman), or set "
        "ALLOW_HOST_SANDBOX=1 to accept that model-written shell runs as you"
    )


def _run_one(*, dataset_id: str, args, store: FirestoreStateStore):
    _require_isolation()
    src = _load_source(store, dataset_id)
    out_dir = Path(args.out) / dataset_id
    # Same selection as prod: pick_primary_resource_id + prefetch_dataset
    # inside run_test_session (apples-to-apples with the daily pipeline).
    primary_resource_id = pick_primary_resource_id(src.resources or [])

    org_title = ""
    if isinstance(src.organization, dict):
        org_title = src.organization.get("title") or src.organization.get("name") or ""

    print(f"\n--- running {args.model} on {dataset_id} ({src.title!r}) ---")
    try:
        res = run_test_session(
            dataset_id=dataset_id,
            title=src.title or "",
            notes=src.notes or "",
            org_title=org_title,
            primary_resource_id=primary_resource_id,
            resources=src.resources,
            organization=src.organization if isinstance(src.organization, dict) else None,
            store=store,
            out_dir=out_dir,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            quantizations=(
                [q.strip() for q in args.quantizations.split(",") if q.strip()]
                if args.quantizations else None
            ),
        )
    except AccountLimitError:
        # Dead key / exhausted credits: every remaining dataset would hit the
        # same rejection, so stop the batch here, as production does.
        raise
    except Exception as e:
        log.exception("test[%s]: run_test_session failed: %s", dataset_id[:8], e)
        return None

    _print_summary(res)
    print(
        f"  preview: python -m services.page_builder.cli.preview swap {dataset_id}"
    )
    return res


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Page-builder benchmark (any model, production session path; "
                    "run via infra/benchmark.sh)"
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--source", help="single dataset id")
    g.add_argument("--batch", nargs="+", help="multiple dataset ids")
    g.add_argument("--auto-trio", action="store_true",
                   help="auto-pick one map / timeseries / registry from existing prod builds")
    p.add_argument("--model", required=True,
                   help="OpenRouter model id ('minimax/minimax-m3', "
                        "'moonshotai/kimi-k2.6', 'x-ai/grok-4.3', "
                        "'anthropic/claude-sonnet-4-6', ...) or "
                        "'anthropic:claude-...' for the native calibration path")
    p.add_argument("--out", default=str(DEFAULT_OUT_DIR))
    p.add_argument("--reasoning-effort",
                   choices=["none", "minimal", "low", "medium", "high", "xhigh", "max"],
                   help="OpenRouter reasoning.effort override (OpenRouter "
                        "models only); omit to use OPENROUTER_REASONING_EFFORT "
                        "(under infra/benchmark.sh: the live job's value), else "
                        "the model's MODEL_ROUTING default")
    p.add_argument("--quantizations",
                   help="comma-separated OpenRouter quantization filter "
                        "(e.g. 'fp8'), overriding the model's own floor in "
                        "model_harness.MODEL_ROUTING. Use to A/B precision — "
                        "deepseek-v4-flash already defaults to fp8 because its "
                        "provider pool contains fp4 endpoints")
    p.add_argument("--max-iters", type=int, default=30,
                   help="ignored; kept so old command lines still parse")
    p.add_argument("--snapshot-out", metavar="FILE",
                   help="read the datasets from Firestore, write FILE, and exit "
                        "(host side of infra/benchmark.sh)")
    p.add_argument("--snapshot", metavar="FILE",
                   help="use a --snapshot-out file instead of Firestore "
                        "(container side of infra/benchmark.sh)")
    p.add_argument("--project", default=os.environ.get("FIREBASE_PROJECT") or "govdata-il")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.auto_trio:
        ids = _pick_auto_trio()
        if not ids:
            print("no candidates found in frontend/public/datasets/", file=sys.stderr)
            return 2
        print(f"auto-trio picked: {', '.join(ids)}")
    elif args.source:
        ids = [args.source]
    else:
        ids = list(args.batch or [])

    if args.snapshot_out:
        write_snapshot(FirestoreStateStore(project_id=args.project), ids, args.snapshot_out)
        print(f"snapshot of {len(ids)} dataset(s) → {args.snapshot_out}")
        return 0
    _require_isolation()  # before any Firestore client is built
    store = (
        SnapshotStore(args.snapshot)
        if args.snapshot
        else FirestoreStateStore(project_id=args.project)
    )
    results: list[TestSessionResult] = []
    for did in ids:
        res = _run_one(dataset_id=did, args=args, store=store)
        if res is not None:
            results.append(res)

    if results:
        priced = [r for r in results if _spend(r) is not None]
        total = sum(_spend(r) for r in priced)
        suffix = (
            f" + {len(results) - len(priced)} unpriced"
            if len(priced) < len(results) else ""
        )
        print(f"\n=== batch summary: {len(results)}/{len(ids)} ok, "
              f"total $: {total:.4f}{suffix} ===")
    return 0 if len(results) == len(ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
