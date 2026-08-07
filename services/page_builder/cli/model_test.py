"""CLI: run any model (via OpenRouter) against one or more CKAN datasets.

Local-only harness. Production Cloud Run / Cloud Build images do not install
the deps this module needs. To run it:

    pip install -r services/page_builder/requirements.txt \\
                -r services/page_builder/requirements-test.txt
    export OPENROUTER_API_KEY=...
    python -m services.page_builder.cli.model_test \\
        --source <dataset_id> --model minimax/minimax-m3

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
    python -m services.page_builder.cli.model_test --source <id> --model minimax/minimax-m3
    python -m services.page_builder.cli.model_test --batch <id1> <id2> --model moonshotai/kimi-k2.6
    python -m services.page_builder.cli.model_test --auto-trio --model anthropic:claude-sonnet-4-6
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

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
        f"  iterations: {res.iterations}, elapsed: {res.elapsed_seconds:.1f}s\n"
        f"  tokens: in={usage['input_tokens']:,} out={usage['output_tokens']:,} "
        f"cached={usage['cache_read_tokens']:,} total={usage['total_tokens']:,}\n"
        f"{provider_line}"
        f"{cost_line}\n"
        f"{check_line}\n"
        f"  files: {res.content_html_path.name}, {res.agent_data_path.name}, "
        f"transcript.json, cost.json"
    )


def _run_one(*, dataset_id: str, args, store: FirestoreStateStore):
    src = _load_source(store, dataset_id)
    out_dir = Path(args.out) / dataset_id
    # Same selection as prod: pick_primary_resource_id + prefetch_dataset
    # inside run_test_session (apples-to-apples with the daily pipeline).
    primary_resource_id = pick_primary_resource_id(src.resources or [])

    org_title = ""
    if isinstance(src.organization, dict):
        org_title = src.organization.get("title") or src.organization.get("name") or ""

    # Same related-candidates block as prod (read-only Firestore query).
    related_candidates: list[dict] = []
    org_name = (src.organization or {}).get("name") or ""
    if org_name:
        try:
            related_candidates = [
                {"id": s.id, "title": s.title, "tags": s.tags}
                for s in store.list_org_sources(org_name, exclude_id=dataset_id)
            ]
        except Exception:
            log.warning("related-candidates lookup failed for %s", dataset_id[:8])

    print(f"\n--- running {args.model} on {dataset_id} ({src.title!r}) ---")
    try:
        res = run_test_session(
            dataset_id=dataset_id,
            title=src.title or "",
            notes=src.notes or "",
            org_title=org_title,
            primary_resource_id=primary_resource_id,
            resources=src.resources,
            related_candidates=related_candidates,
            out_dir=out_dir,
            model=args.model,
            max_iters=args.max_iters,
            reasoning_effort=args.reasoning_effort,
            quantizations=(
                [q.strip() for q in args.quantizations.split(",") if q.strip()]
                if args.quantizations else None
            ),
        )
    except Exception as e:
        log.exception("test[%s]: run_test_session failed: %s", dataset_id[:8], e)
        return None

    _print_summary(res)
    print(
        f"  preview: python -m services.page_builder.cli.preview swap {dataset_id}"
    )
    return res


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Page-builder test harness (any model, Podman sandbox)")
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
                        "models only); omit for the model default, which is "
                        "what production uses")
    p.add_argument("--quantizations",
                   help="comma-separated OpenRouter quantization filter "
                        "(e.g. 'fp8'), overriding the model's own floor in "
                        "model_harness.MODEL_ROUTING. Use to A/B precision — "
                        "deepseek-v4-flash already defaults to fp8 because its "
                        "provider pool contains fp4 endpoints")
    p.add_argument("--max-iters", type=int, default=30)
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

    store = FirestoreStateStore(project_id=args.project)
    results: list[TestSessionResult] = []
    for did in ids:
        res = _run_one(dataset_id=did, args=args, store=store)
        if res is not None:
            results.append(res)

    if results:
        priced = [r for r in results if (r.cost_usd or {}).get("total_usd") is not None]
        total = sum(r.cost_usd["total_usd"] for r in priced)
        suffix = (
            f" + {len(results) - len(priced)} unpriced"
            if len(priced) < len(results) else ""
        )
        print(f"\n=== batch summary: {len(results)}/{len(ids)} ok, "
              f"total $: {total:.4f}{suffix} ===")
    return 0 if len(results) == len(ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
