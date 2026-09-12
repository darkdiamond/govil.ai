"""Quick model eval: run a candidate model on a few live datasets, compare by eye.

One command, no write-up required:

    python -m services.page_builder.cli.eval_quick --model <openrouter-id>

What it does:
  1. Picks datasets — `--recent N` (default 3) most-recently *analyzed* sources
     that are live on govil.ai, or an explicit `--sources id1 id2 ...`.
  2. Runs each through the prod-parity harness (`run_test_session` — same
     system prompt, same prefetch, same sandbox, same self-check) — identical
     to what `cli/model_test` does; this is just the simpler front door.
  3. Splices each candidate body into the live prod page shell
     (`preview.render`) and builds ONE compare page: candidate vs live,
     side by side, with the billed cost per dataset.
  4. Opens it in your browser. You judge with your eyes. Costs are printed.

Artifacts land in `tmp/eval_quick/<model>/<dataset_id>/` (gitignored; agent
output embeds raw dataset content). Read-only on prod Firestore; writes
nothing to GCS. No fact-checking pass, no README tables — for the deep
method see docs/MODEL_EVAL.md.
"""
from __future__ import annotations

import argparse
import html
import json
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from services.page_builder.cli.model_test import _load_source, _run_one
from services.shared.firestore import FirestoreStateStore

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "tmp" / "eval_quick"
PROD_URL_BASE = "https://govil.ai/datasets"


def _slug_url(dataset_id: str) -> str:
    """Resolve /datasets/<id> to the canonical slug URL (follows the 301)."""
    import urllib.request

    req = urllib.request.Request(
        f"{PROD_URL_BASE}/{dataset_id}", headers={"User-Agent": "govdata-eval-quick/1"}
    )
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception:
        return f"{PROD_URL_BASE}/{dataset_id}"
    return req.get_full_url()


def pick_recent_live(store: FirestoreStateStore, n: int) -> list[str]:
    """Most-recently-analyzed succeeded sources that are actually live (200)."""
    import urllib.error
    import urllib.request

    rows = sorted(store.iter_succeeded_sources(), key=lambda s: str(s.last_analyzed_at or ""), reverse=True)
    picks: list[str] = []
    for s in rows:
        if len(picks) >= n:
            break
        url = f"{PROD_URL_BASE}/{s.id}"
        try:
            urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "govdata-eval-quick/1"}), timeout=15
            )
        except urllib.error.HTTPError as e:
            print(f"  skip {s.id[:8]} ({(s.title or '')[:40]}): live check {e.code}")
            continue
        except Exception as e:
            print(f"  skip {s.id[:8]} ({(s.title or '')[:40]}): live check {type(e).__name__}")
            continue
        picks.append(s.id)
        print(f"  picked {s.id[:8]} — {(s.title or '')[:60]}")
    if len(picks) < n:
        print(f"warning: only {len(picks)} of {n} requested datasets are live-and-recent")
    return picks


def _model_tag(model: str) -> str:
    return model.replace("/", "-")


def build_compare_page(out_dir: Path, model: str, results: list, dataset_ids: list[str]) -> Path:
    """One page: per-dataset candidate|live iframes + a cost table."""
    rows = []
    total_cost = 0.0
    all_priced = True
    for res in results:
        cost = res.cost_usd or {}
        c = cost.get("total_usd")
        if c is not None:
            total_cost += c
        else:
            all_priced = False
        check = "✓" if res.host_check == "passed" else f"✗ {html.escape(res.host_check[:60])}"
        live_url = _slug_url(res.dataset_id)
        # compare page sits inside the model dir; preview.html is a sibling
        # of it (one level down per dataset) — keep src relative to here.
        prev_rel = f"{res.dataset_id}/preview.html"
        src = _load_source(FirestoreStateStore(project_id="govdata-il"), res.dataset_id)
        title = html.escape(src.title or res.dataset_id)
        rows.append(f"""
  <section>
    <h2>{title} <code>{res.dataset_id[:12]}…</code></h2>
    <p class=meta>${c:.4f} · {res.elapsed_seconds:.0f}s · in {res.usage['input_tokens']:,} / out {res.usage['output_tokens']:,} · host-check {check} ·
       <a href="{prev_rel}" target="_blank">candidate alone</a> ·
       <a href="{live_url}" target="_blank">live alone</a></p>
    <div class="panes">
      <iframe src="{prev_rel}" title="candidate"></iframe>
      <iframe src="{live_url}" title="live"></iframe>
    </div>
  </section>""")

    suffix = "" if all_priced else " (some runs unpriced)"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>eval-quick: {html.escape(model)}</title>
<style>
body {{ font-family: Rubik, system-ui, sans-serif; margin: 0; padding: 1.5rem; background: #f1f7ff; color: #0c3058; }}
h1 {{ font-size: 1.3rem; margin: 0 0 .25rem; }}
.lede {{ color: #6c757d; margin: 0 0 1.25rem; font-size: .9rem; }}
section {{ background: #fff; border: 1px solid #c3cfe7; border-radius: .5rem; padding: 1rem; margin-bottom: 1.5rem; }}
h2 {{ font-size: 1.05rem; margin: 0 0 .2rem; direction: rtl; text-align: start; }}
.meta {{ color: #6c757d; font-size: .85rem; margin: 0 0 .6rem; }}
.panes {{ display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }}
.panes iframe {{ width: 100%; height: 80vh; border: 1px solid #c3cfe7; border-radius: .3rem; background: #fff; }}
@media (max-width: 900px) {{ .panes {{ grid-template-columns: 1fr; }} .panes iframe {{ height: 70vh; }} }}
code {{ background: #f0f4fa; padding: .05rem .3rem; border-radius: .2rem; }}
</style></head><body>
<h1>eval-quick — {html.escape(model)}</h1>
<p class=lede>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · prod-parity harness · left = candidate, right = live prod · total billed <b>${total_cost:.4f}</b>{suffix}</p>
{''.join(rows)}
</body></html>"""
    out = out_dir / f"compare-{_model_tag(model)}.html"
    out.write_text(page, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Quick side-by-side model eval (prod harness)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--sources", nargs="+", help="dataset ids (default: --recent)")
    g.add_argument("--recent", type=int, default=3,
                   help="how many most-recent live datasets to use (default 3)")
    p.add_argument("--model", required=True, help="OpenRouter model id, e.g. 'z-ai/glm-5.3-flash'")
    p.add_argument("--reasoning-effort", default="max",
                   help="reasoning effort (default 'max' = prod parity)")
    p.add_argument("--quantizations", help="OpenRouter quantization filter, e.g. 'fp8'")
    p.add_argument("--max-iters", type=int, default=30)
    p.add_argument("--project", default="govdata-il")
    p.add_argument("--no-open", action="store_true", help="don't open the browser")
    args = p.parse_args(argv)

    store = FirestoreStateStore(project_id=args.project)

    if args.sources:
        ids = args.sources
        print(f"datasets (explicit): {', '.join(i[:8] for i in ids)}")
    else:
        print(f"picking {args.recent} most-recent live datasets …")
        ids = pick_recent_live(store, args.recent)
        if not ids:
            print("no live datasets found", file=__import__("sys").stderr)
            return 2

    out_dir = OUT_DIR / _model_tag(args.model)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for did in ids:
        one = SimpleNamespace(out=str(out_dir), model=args.model, max_iters=args.max_iters,
                              reasoning_effort=args.reasoning_effort,
                              quantizations=args.quantizations)
        res = _run_one(dataset_id=did, args=one, store=store)
        if res is not None:
            results.append(res)

    if not results:
        print("all runs failed — nothing to compare", file=__import__("sys").stderr)
        return 1

    # Splice each candidate body into the live prod shell → preview.html
    # (same rendering as `cli.preview render`, but into our out_dir).
    from services.page_builder.cli.preview import (
        _fetch_prod_html, _freeze_static, _inject_preview_banner,
        _rewrite_root_relative, _splice_body,
    )
    for res in results:
        body = (out_dir / res.dataset_id / "content.html").read_text(encoding="utf-8")
        live_html = _fetch_prod_html(res.dataset_id)
        spliced = _rewrite_root_relative(_freeze_static(_inject_preview_banner(
            _splice_body(live_html, body))))
        out = out_dir / res.dataset_id / "preview.html"
        out.write_text(spliced, encoding="utf-8")
        print(f"  preview: {out.relative_to(REPO_ROOT)}")

    compare = build_compare_page(out_dir, args.model, results, ids)
    print(f"\ncompare page: {compare}")
    priced = [(r, (r.cost_usd or {}).get("total_usd")) for r in results]
    total = sum(c for _, c in priced if c is not None)
    print(f"total billed: ${total:.4f}" + ("" if all(c is not None for _, c in priced) else " (partial)"))
    if not args.no_open:
        webbrowser.open(f"file://{compare}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())