"""CLI: preview an authoring build inside the actual dataset-page shell.

`python -m services.page_builder.author verify <id>` writes the recipe's
rendered body + agent_data to
`tmp/model_test/<id>/{content.html,agent_data.json}` (the directory name is
historical). Two ways to see it
rendered through the real shell (Tailwind, layouts/default.vue, dataset-libs
globals, related-datasets sidebar, metadata cards):

  render  — splices the harness body into the live govil.ai HTML offline.
            No dev server needed; just open the generated file. Fastest
            way to eyeball "does this body work in the real shell".

  swap    — drops the harness files on top of `frontend/public/datasets/<id>/`
            so `npm run dev` serves them at localhost:3000. Lets you see
            related-datasets / sidebar / SEO meta updated to match the
            harness build (render does not). Pair with restore.

Examples:

    python -m services.page_builder.cli.preview render <id>
    # -> writes tmp/model_test/<id>/preview.html, prints file:// URL

    python -m services.page_builder.cli.preview swap <id>
    cd frontend && npm run dev
    # http://localhost:3000/datasets/<id>  vs  https://govil.ai/datasets/<id>
    python -m services.page_builder.cli.preview restore <id>

    python -m services.page_builder.cli.preview status

`--all` applies swap/restore to every dataset under tmp/model_test/.
This tool never touches Firestore or GCS; it is purely a local-FS swap
plus an optional outbound fetch for `render`.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS_OUT_DIR = REPO_ROOT / "tmp" / "model_test"
PROD_DATASETS_DIR = REPO_ROOT / "frontend" / "public" / "datasets"
PROD_URL_BASE = "https://govil.ai/datasets"
LOCAL_URL_BASE = "http://localhost:3000/datasets"

# The dataset shell renders the agent body through `<article ref="bodyEl"
# class="dataset-body" v-html="body" />` (see frontend/pages/datasets/[id].vue).
# In the SSG'd output it lands as exactly one `<article ... class="dataset-body"
# data-v-...>...</article>` element, so we can locate it by the class alone.
DATASET_BODY_OPEN_RE = re.compile(
    r'<article\b[^>]*\bclass="[^"]*\bdataset-body\b[^"]*"[^>]*>',
    re.IGNORECASE,
)
PREVIEW_BANNER_HTML = (
    '<div style="position:fixed;top:0;left:0;right:0;z-index:99999;'
    'background:#0c3058;color:#fff;font-family:Rubik,system-ui,sans-serif;'
    'font-size:.85rem;padding:.4rem 1rem;text-align:center;direction:ltr">'
    '⚙ model-harness preview — body spliced into prod shell, Vue hydration '
    'stripped. Data explorer (עיון בנתונים) + interactive chrome are inert; '
    'sidebar / related-datasets / SEO meta still reflect prod. '
    'For a live shell use: preview swap + npm run dev.'
    '</div>'
)

# Files the page-builder agent owns (per CLAUDE.md). data.json is the scanner's
# and is identical between harness and prod runs for the same dataset, so we leave
# it alone — that also keeps the swap minimal and the restore precise.
SWAP_FILES = ("content.html", "agent_data.json")
BACKUP_DIRNAME = "prod-backup"


@dataclass(frozen=True)
class Paths:
    dataset_id: str
    build_dir: Path
    prod_dir: Path
    backup_dir: Path

    @classmethod
    def for_id(cls, dataset_id: str) -> "Paths":
        return cls(
            dataset_id=dataset_id,
            build_dir=HARNESS_OUT_DIR / dataset_id,
            prod_dir=PROD_DATASETS_DIR / dataset_id,
            backup_dir=HARNESS_OUT_DIR / dataset_id / BACKUP_DIRNAME,
        )

    def build_file(self, name: str) -> Path:
        return self.build_dir / name

    def prod_file(self, name: str) -> Path:
        return self.prod_dir / name

    def backup_file(self, name: str) -> Path:
        return self.backup_dir / name


def _is_swapped(p: Paths) -> bool:
    """A dataset is 'swapped' if its prod-backup dir holds at least one of the
    swap files — restore needs that backup to put things back."""
    return p.backup_dir.is_dir() and any(p.backup_file(f).exists() for f in SWAP_FILES)


def _all_build_ids() -> list[str]:
    if not HARNESS_OUT_DIR.is_dir():
        return []
    return sorted(d.name for d in HARNESS_OUT_DIR.iterdir() if d.is_dir())


def _print_compare_links(dataset_id: str) -> None:
    print(f"  this run : {LOCAL_URL_BASE}/{dataset_id}")
    print(f"  prod     : {PROD_URL_BASE}/{dataset_id}")


def _swap_one(p: Paths) -> bool:
    if not p.build_dir.is_dir():
        print(f"[{p.dataset_id[:8]}] no harness build at {p.build_dir} — skip", file=sys.stderr)
        return False
    missing = [f for f in SWAP_FILES if not p.build_file(f).exists()]
    if missing:
        print(
            f"[{p.dataset_id[:8]}] build dir missing files: {missing} — skip",
            file=sys.stderr,
        )
        return False
    if not p.prod_dir.is_dir():
        print(
            f"[{p.dataset_id[:8]}] no prod page at {p.prod_dir} — skip "
            f"(this dataset has not been published yet)",
            file=sys.stderr,
        )
        return False
    if _is_swapped(p):
        print(
            f"[{p.dataset_id[:8]}] already swapped — restore first to re-swap",
            file=sys.stderr,
        )
        return False

    p.backup_dir.mkdir(parents=True, exist_ok=True)
    for fname in SWAP_FILES:
        prod_f = p.prod_file(fname)
        backup_f = p.backup_file(fname)
        if prod_f.exists():
            shutil.copy2(prod_f, backup_f)
        build_f = p.build_file(fname)
        shutil.copy2(build_f, prod_f)

    print(f"[{p.dataset_id[:8]}] swapped:")
    _print_compare_links(p.dataset_id)
    return True


def _restore_one(p: Paths) -> bool:
    if not _is_swapped(p):
        print(f"[{p.dataset_id[:8]}] not currently swapped — skip", file=sys.stderr)
        return False
    if not p.prod_dir.is_dir():
        print(
            f"[{p.dataset_id[:8]}] prod dir gone — leaving backup at {p.backup_dir}",
            file=sys.stderr,
        )
        return False

    for fname in SWAP_FILES:
        backup_f = p.backup_file(fname)
        prod_f = p.prod_file(fname)
        if backup_f.exists():
            shutil.copy2(backup_f, prod_f)
            backup_f.unlink()
    # Remove backup dir if empty
    try:
        p.backup_dir.rmdir()
    except OSError:
        pass

    print(f"[{p.dataset_id[:8]}] restored")
    return True


def _resolve_ids(arg_ids: list[str], all_flag: bool) -> list[str]:
    if all_flag:
        ids = _all_build_ids()
        if not ids:
            print(f"no harness builds under {HARNESS_OUT_DIR}", file=sys.stderr)
        return ids
    return list(arg_ids)


def _do(action: str, ids: Iterable[str]) -> int:
    fn = _swap_one if action == "swap" else _restore_one
    ok = fail = 0
    for did in ids:
        if fn(Paths.for_id(did)):
            ok += 1
        else:
            fail += 1
    if action == "swap" and ok:
        print(
            "\nopen the URL pairs above to compare. when done, run:\n"
            "  python -m services.page_builder.cli.preview restore "
            + (" ".join(ids) if ok and not fail else "--all")
        )
    return 0 if fail == 0 else 1


def _fetch_prod_html(dataset_id: str, prod_url: str | None = None) -> str:
    # Live pages are served at /datasets/<page_slug>; the id URL only works
    # for legacy entries. Pass --prod-url with the slug URL when the id 404s.
    url = prod_url or f"{PROD_URL_BASE}/{dataset_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "govdata-preview/1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def _splice_body(prod_html: str, harness_body: str) -> str:
    """Replace the article.dataset-body innerHTML in prod_html with harness_body.

    Raises ValueError if the structure isn't what we expect — that means
    the shell template changed and this needs updating.
    """
    open_match = DATASET_BODY_OPEN_RE.search(prod_html)
    if not open_match:
        raise ValueError(
            "no <article class='dataset-body'> in prod HTML — has the "
            "shell template changed?"
        )
    close_idx = prod_html.find("</article>", open_match.end())
    if close_idx < 0:
        raise ValueError("article.dataset-body has no </article>")
    return (
        prod_html[: open_match.end()]
        + "\n"
        + harness_body.rstrip()
        + "\n"
        + prod_html[close_idx:]
    )


def _inject_preview_banner(html: str) -> str:
    """Inject a thin banner just after <body> so the user can never confuse a
    spliced preview with the live page."""
    body_open = re.search(r"<body\b[^>]*>", html, re.IGNORECASE)
    if not body_open:
        return html
    end = body_open.end()
    return html[:end] + PREVIEW_BANNER_HTML + html[end:]


# Rewrite root-relative URLs (`/_nuxt/…`, `/lib/…`, `/icons/…`, `/datasets/…`)
# to absolute govil.ai URLs so the spliced preview works when opened via
# file://. We deliberately leave protocol-relative `//host/…` and
# already-absolute `https?://…` URLs alone.
_ROOT_RELATIVE_ATTR_RE = re.compile(
    r'(\b(?:href|src)\s*=\s*")/(?!/)([^"]*)"',
    re.IGNORECASE,
)


def _rewrite_root_relative(html: str, host: str = "https://govil.ai") -> str:
    return _ROOT_RELATIVE_ATTR_RE.sub(rf'\1{host}/\2"', html)


# Nuxt's client bundle hydrates the page from `_payload.json`, which would
# re-render `<article class="dataset-body" v-html="body" />` with the *prod*
# body and overwrite our splice. Stripping the bundle + payload preload +
# the inlined NUXT data leaves the static SSG HTML alone — chrome still
# displays, but Vue never runs and the splice survives. Inline <script>
# tags inside the agent body (echarts/leaflet init) still execute on
# browser load because they're plain global script tags, not Vue-mounted.
_HYDRATION_TAG_RES = (
    re.compile(r'<script\b[^>]*\bsrc="[^"]*/_nuxt/[^"]*"[^>]*>\s*</script>',
               re.IGNORECASE),
    re.compile(r'<link\b[^>]*\bhref="[^"]*/_nuxt/[^"]*"[^>]*/?>',
               re.IGNORECASE),
    re.compile(r'<link\b[^>]*\bhref="[^"]*_payload\.json[^"]*"[^>]*/?>',
               re.IGNORECASE),
    re.compile(r'<script\b[^>]*\bid="__NUXT_DATA__"[^>]*>.*?</script>',
               re.IGNORECASE | re.DOTALL),
    re.compile(r'<script\b[^>]*\bdata-nuxt-data[^>]*>.*?</script>',
               re.IGNORECASE | re.DOTALL),
)


def _freeze_static(html: str) -> str:
    """Strip Nuxt hydration so the spliced body survives in the browser."""
    for r in _HYDRATION_TAG_RES:
        html = r.sub("", html)
    return html


def _render_one(p: Paths, prod_url: str | None = None) -> bool:
    if not p.build_file("content.html").exists():
        print(
            f"[{p.dataset_id[:8]}] no harness build at {p.build_dir} — skip",
            file=sys.stderr,
        )
        return False
    print(
        f"[{p.dataset_id[:8]}] fetching "
        f"{prod_url or f'{PROD_URL_BASE}/{p.dataset_id}'} ..."
    )
    try:
        prod_html = _fetch_prod_html(p.dataset_id, prod_url=prod_url)
    except Exception as e:
        print(
            f"[{p.dataset_id[:8]}] fetch failed: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return False
    harness_body = p.build_file("content.html").read_text(encoding="utf-8")
    try:
        spliced = _splice_body(prod_html, harness_body)
    except ValueError as e:
        print(f"[{p.dataset_id[:8]}] splice failed: {e}", file=sys.stderr)
        return False
    spliced = _rewrite_root_relative(spliced)
    spliced = _freeze_static(spliced)
    spliced = _inject_preview_banner(spliced)
    out = p.build_dir / "preview.html"
    out.write_text(spliced, encoding="utf-8")
    print(f"[{p.dataset_id[:8]}] wrote {out} ({out.stat().st_size:,} bytes)")
    print(f"  open: file://{out}")
    print(f"  prod: {prod_url or f'{PROD_URL_BASE}/{p.dataset_id}'}")
    return True


def _cmd_render(ids: Iterable[str], prod_url: str | None = None) -> int:
    ids = list(ids)
    if prod_url and len(ids) > 1:
        print("--prod-url only works with a single dataset id", file=sys.stderr)
        return 2
    ok = fail = 0
    for did in ids:
        if _render_one(Paths.for_id(did), prod_url=prod_url):
            ok += 1
        else:
            fail += 1
    return 0 if fail == 0 else 1


def _cmd_status() -> int:
    swapped: list[str] = []
    untouched: list[str] = []
    for did in _all_build_ids():
        if _is_swapped(Paths.for_id(did)):
            swapped.append(did)
        else:
            untouched.append(did)
    if swapped:
        print("currently swapped (prod page replaced by harness build):")
        for did in swapped:
            print(f"  {did}")
            _print_compare_links(did)
    else:
        print("no datasets currently swapped")
    if untouched:
        print(f"\nharness builds available but not swapped ({len(untouched)}):")
        for did in untouched:
            print(f"  {did}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Swap harness-built dataset pages into the live Nuxt tree for preview.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, help_ in (
        ("swap", "replace prod content.html + agent_data.json with the harness build"),
        ("restore", "put the prod files back from prod-backup/"),
        ("render", "fetch the live govil.ai page and splice the harness body into it; "
                   "writes a self-contained preview.html you can open offline"),
    ):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("ids", nargs="*", help="dataset id(s)")
        sp.add_argument("--all", action="store_true",
                        help=f"apply to every harness build under {HARNESS_OUT_DIR.relative_to(REPO_ROOT)}/")
        if name == "render":
            sp.add_argument("--prod-url",
                            help="full live page URL to splice into (use the "
                                 "slug URL when the id-based URL 404s); "
                                 "single id only")

    sub.add_parser("status", help="list datasets currently swapped + available builds")

    args = p.parse_args(argv)

    if args.cmd in ("swap", "restore", "render"):
        ids = _resolve_ids(args.ids, args.all)
        if not ids:
            print("nothing to do — pass dataset ids or --all", file=sys.stderr)
            return 2
        if args.cmd == "render":
            return _cmd_render(ids, prod_url=getattr(args, "prod_url", None))
        return _do(args.cmd, ids)
    return _cmd_status()


if __name__ == "__main__":
    raise SystemExit(main())
