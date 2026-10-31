"""CLI: preview a recipe's page in the real dataset shell, locally.

One command renders the recipe over `author prepare`'s cached data (one run,
the refresh's own code: compute → template → sanitizer → check.py), stages it
in tmp/preview/, and serves it through `nuxt dev` with the real layout,
Tailwind, explorer, tags and related sidebar:

    python -m services.page_builder.cli.preview <id> [<id>...]
    #   local: http://127.0.0.1:3100/datasets/<page_slug>/
    #   prod : https://govil.ai/datasets/<page_slug>/   (when it is live)

    python -m services.page_builder.cli.preview <id> --watch
    # re-renders whenever recipes/<id>/ changes; the open page reloads itself

    python -m services.page_builder.cli.preview <id> --no-serve   # stage only
    python -m services.page_builder.cli.preview status
    python -m services.page_builder.cli.preview stop

tmp/preview/ is an overlay: the dev server (NUXT_PREVIEW_ROOT) reads a
dataset's files and the manifest there first and falls back to
frontend/public/, so nothing under frontend/ is touched and there is nothing to
restore. The manifest is this checkout's frontend/public/data/manifest.json
(else the main checkout's, so a worktree gets the full corpus) plus every
staged dataset, with tags and related datasets computed the way the publisher
does. `author verify` stages its page here too, so an open preview reloads on
every verify. The server starts once per checkout and keeps running until
`stop`. No Firestore, GCS or network (beyond localhost).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from services.shared.firestore import SourceRecord
from services.shared.slug import slugify

from .. import author
from ..publish import (
    _build_page_slugs,
    _merged_entry,
    _write_manifest,
    _write_search_index,
    dataset_meta_from_source,
)
from ..recipe import RecipeError
from ..related import TOP_K, RelatedIndex
from ..schema import AgentData, DatasetMeta, Manifest
from ..tags import Taxonomy, org_drop_names, pending_tags_path

REPO_ROOT = Path(__file__).resolve().parents[3]
PREVIEW_ROOT = REPO_ROOT / "tmp" / "preview"
FRONTEND = REPO_ROOT / "frontend"
PROD_URL_BASE = "https://govil.ai/datasets"
HOST = "127.0.0.1"
PORTS = range(3100, 3200)        # clear of `npm run dev`'s 3000
SERVER_READY_TIMEOUT_S = 240
WATCH_INTERVAL_S = 0.5


# ── staging ──────────────────────────────────────────────────────────────


def base_manifest_path() -> Optional[Path]:
    """The published corpus to overlay: this checkout's manifest, else the
    main checkout's (worktrees don't carry frontend/public/data/)."""
    rel = Path("frontend/public/data/manifest.json")
    if (REPO_ROOT / rel).is_file():
        return REPO_ROOT / rel
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    main = Path(common).parent / rel
    return main if main.is_file() else None


def _load_base() -> Manifest:
    path = base_manifest_path()
    if path is None:
        return Manifest(generated_at=datetime.now(timezone.utc))
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def _dt(value) -> Optional[datetime]:
    return datetime.fromisoformat(value) if isinstance(value, str) and value else None


def _source_record(dataset_id: str, recipes_root: Path) -> SourceRecord:
    """The sources/<id> doc the publisher would read, from prepare()'s
    source.json (plus the provider's credit block for a provider source)."""
    path = author.AUTHORING_ROOT / dataset_id / "source.json"
    facts = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    modified = _dt(facts.get("metadata_modified"))
    title = facts.get("title") or dataset_id
    src = SourceRecord(
        id=dataset_id,
        title=title,
        slug=facts.get("slug") or slugify(title, fallback=dataset_id),
        notes=facts.get("notes"),
        organization=facts.get("organization") or {},
        license_title=facts.get("license_title"),
        update_frequency=facts.get("update_frequency"),
        tags=facts.get("tags") or [],
        resources=facts.get("resources") or [],
        record_count=facts.get("record_count"),
        metadata_modified=modified,
        analysis_status="succeeded",
        last_analyzed_at=modified or datetime.now(timezone.utc),
        analyzed_metadata_modified=modified,
    )
    provider = author._provider_for_recipe(dataset_id, recipes_root)
    if provider is not None:
        prov = provider[0]
        src.provider = prov.key
        src.source_url = facts.get("source_url")
        src.presentation = prov.presentation().model_dump()
        src.page_slug_suffix = prov.page_slug_suffix(dataset_id)
    return src


def _dataset_tags(tax: Taxonomy, meta: DatasetMeta, agent: Optional[AgentData],
                  drop: frozenset[str]) -> list[str]:
    """Curated tags, else the batch's pending tags.json, else the fallback."""
    if meta.id not in tax.assignments:
        pending = pending_tags_path(meta.id)
        if pending.is_file():
            try:
                return tax.canonicalize(json.loads(pending.read_text(encoding="utf-8")))
            except ValueError:
                pass
    return tax.dataset_tags(meta.id, suggested=agent.suggested_tags if agent else [],
                            ckan=meta.tags_he, drop_names=drop)


def _write_overlay_manifest(root: Path, base: Manifest) -> None:
    """Base corpus + every staged dataset, with publisher tags + related."""
    tax = Taxonomy.load()
    entries = {e.id: e for e in base.datasets}
    staged: list[tuple[DatasetMeta, Optional[AgentData]]] = []
    for d in sorted((root / "datasets").iterdir()):
        if not (d / "data.json").is_file():
            continue
        meta = DatasetMeta.model_validate_json((d / "data.json").read_text(encoding="utf-8"))
        agent_path = d / "agent_data.json"
        agent = (AgentData.model_validate_json(agent_path.read_text(encoding="utf-8"))
                 if agent_path.is_file() else None)
        staged.append((meta, agent))
    drop = org_drop_names([e.organization for e in entries.values()]
                          + [m.organization for m, _ in staged])
    for meta, agent in staged:
        entries[meta.id] = _merged_entry(meta, agent, _dataset_tags(tax, meta, agent, drop))
    index = RelatedIndex(entries.values())
    for meta, _ in staged:
        entries[meta.id].related_ids = [m.id for m in index.top(meta.id, TOP_K)]
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    manifest = base.model_copy(update={
        "generated_at": datetime.now(timezone.utc),
        "datasets": sorted(entries.values(), key=lambda e: e.metadata_modified or oldest,
                           reverse=True),
    })
    # Written aside, then renamed in: the dev server never reads half a file.
    scratch = Path(tempfile.mkdtemp(prefix=".manifest-", dir=root))
    try:
        (root / "data").mkdir(exist_ok=True)
        for written in (_write_manifest(scratch, manifest), _write_search_index(scratch, manifest)):
            os.replace(written, root / "data" / written.name)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def stage(dataset_id: str, page, raw: dict, *, recipes_root: Path = author.RECIPES_ROOT,
          root: Optional[Path] = None) -> Path:
    """Write one rendered page into the preview overlay the way the publisher
    lays out frontend/public/: datasets/<id>/{content.html,data.json,
    agent_data.json} (+ model.json, for reading), data/manifest.json and
    data/search-index.json. Then bump the stamp an open page polls."""
    root = root or PREVIEW_ROOT
    out = root / "datasets" / dataset_id
    out.mkdir(parents=True, exist_ok=True)
    base = _load_base()
    meta = dataset_meta_from_source(_source_record(dataset_id, recipes_root))
    live = next((e for e in base.datasets if e.id == dataset_id), None)
    meta.page_slug = live.page_slug if live and live.page_slug else _build_page_slugs({dataset_id: meta})[dataset_id]

    (out / "content.html").write_text(page.content_html, encoding="utf-8")
    (out / "agent_data.json").write_text(
        json.dumps(page.agent_data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "model.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "data.json").write_text(meta.model_dump_json(exclude_none=True, indent=2), encoding="utf-8")
    (out / "preview.json").write_text(json.dumps({"live": live is not None}), encoding="utf-8")
    # Batch authoring verifies several datasets at once; each rebuild rescans
    # every staged dir, so serializing them is enough for the last to hold all.
    with open(root / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _write_overlay_manifest(root, base)
        (root / "stamp").write_text(str(time.time_ns()), encoding="utf-8")
    return out


def render(dataset_id: str, recipes_root: Path = author.RECIPES_ROOT,
           root: Optional[Path] = None) -> bool:
    """Render one recipe over the local data and stage it. A failure keeps
    the last staged page and returns False."""
    t0 = time.monotonic()
    tag = f"[{dataset_id[:8]}]"
    work = Path(tempfile.mkdtemp(prefix=f"preview-{dataset_id[:8]}-"))
    try:
        recipe, manifest, resources = author.load_local(dataset_id, recipes_root)
        data_dir = author.AUTHORING_ROOT / dataset_id / "data"
        raw, page, _ = author.render_local(recipe, manifest, resources, data_dir, work)
        stage(dataset_id, page, raw, recipes_root=recipes_root, root=root)
    except SystemExit as e:
        print(f"{tag} {e}", file=sys.stderr)
        return False
    except RecipeError as e:
        print(f"{tag} FAIL [{e.reason}] {e}", file=sys.stderr)
        return False
    except Exception as e:  # a broken recipe mid-edit must not kill --watch
        print(f"{tag} FAIL {type(e).__name__}: {e}", file=sys.stderr)
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for w in page.warnings:
        print(f"{tag} warning: {w}")
    print(f"{tag} rendered in {time.monotonic() - t0:.1f}s")
    return True


# ── dev server ───────────────────────────────────────────────────────────


def _server_file(root: Path) -> Path:
    return root / "server.json"


def _read_server(root: Path) -> Optional[dict]:
    try:
        return json.loads(_server_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _get(url: str, timeout: float) -> Optional[int]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            r.read()
            return r.status
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def running_server(root: Optional[Path] = None) -> Optional[dict]:
    root = root or PREVIEW_ROOT
    info = _read_server(root)
    if not info or not _pid_alive(info["pid"]):
        return None
    if _get(f"http://{HOST}:{info['port']}/__preview/stamp", timeout=3) != 200:
        return None
    return info


def _free_port() -> int:
    for port in PORTS:
        with socket.socket() as s:
            # As Node listens: a port in TIME_WAIT after `stop` is free to reuse.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((HOST, port))
            except OSError:
                continue
            return port
    raise SystemExit(f"no free port in {PORTS.start}-{PORTS.stop - 1}")


def ensure_server(root: Optional[Path] = None) -> dict:
    """The checkout's preview server, started (and waited for) if needed.
    Locked, so parallel `preview` calls share one server."""
    root = root or PREVIEW_ROOT
    root.mkdir(parents=True, exist_ok=True)
    with open(root / ".server.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _ensure_server(root)


def _ensure_server(root: Path) -> dict:
    info = running_server(root)
    if info:
        return info
    stale = _read_server(root)
    if stale and _pid_alive(stale["pid"]):  # alive but not answering: replace it
        _kill(stale["pid"])
    nuxt = FRONTEND / "node_modules" / ".bin" / "nuxt"
    if not nuxt.exists():
        raise SystemExit(f"{nuxt} missing — install the frontend deps in the main checkout")
    # `npm run dev`'s predev: viz libs into public/lib/ (gitignored, per checkout).
    subprocess.run(["node", "scripts/copy-libs.mjs"], cwd=FRONTEND, check=True,
                   stdout=subprocess.DEVNULL)
    port = _free_port()
    log_path = root / "server.log"
    env = {**os.environ, "NUXT_PREVIEW_ROOT": str(root.resolve())}
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(
            [str(nuxt), "dev", "--port", str(port), "--host", HOST],
            cwd=FRONTEND, env=env, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
    info = {"pid": proc.pid, "port": port, "started_at": datetime.now(timezone.utc).isoformat()}
    _server_file(root).write_text(json.dumps(info), encoding="utf-8")
    print(f"starting nuxt dev on port {port} (log: {log_path.relative_to(REPO_ROOT)}) ...")
    t0 = time.monotonic()
    while time.monotonic() - t0 < SERVER_READY_TIMEOUT_S:
        if proc.poll() is not None:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            _server_file(root).unlink(missing_ok=True)
            raise SystemExit(f"nuxt dev exited ({proc.returncode}):\n{tail}")
        if _get(f"http://{HOST}:{port}/__preview/stamp", timeout=3) == 200:
            print(f"server ready in {time.monotonic() - t0:.0f}s")
            return info
        time.sleep(1)
    _kill(proc.pid)
    _server_file(root).unlink(missing_ok=True)
    raise SystemExit(f"nuxt dev not ready after {SERVER_READY_TIMEOUT_S}s — see {log_path}")


def _kill(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)  # nuxt dev forks its server; take the group
    except ProcessLookupError:
        return
    for _ in range(50):
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def stop(root: Optional[Path] = None) -> int:
    root = root or PREVIEW_ROOT
    info = _read_server(root)
    if not info:
        print("no preview server recorded")
        return 0
    _kill(info["pid"])
    _server_file(root).unlink(missing_ok=True)
    print(f"stopped preview server (pid {info['pid']}, port {info['port']})")
    return 0


# ── urls / status ────────────────────────────────────────────────────────


def _urls(dataset_id: str, port: Optional[int], root: Path) -> list[str]:
    d = root / "datasets" / dataset_id
    try:
        slug = json.loads((d / "data.json").read_text(encoding="utf-8")).get("page_slug") or dataset_id
        live = json.loads((d / "preview.json").read_text(encoding="utf-8")).get("live")
    except (OSError, ValueError):
        return []
    lines = []
    if port:
        lines.append(f"  local: http://{HOST}:{port}/datasets/{slug}/")
    lines.append(f"  prod : {PROD_URL_BASE}/{slug}/" if live else "  prod : (not live yet)")
    return lines


def _warm(dataset_id: str, port: int, root: Path) -> None:
    """First request of a route compiles it; pay that here, not in the browser."""
    urls = _urls(dataset_id, port, root)
    if urls:
        _get(urllib.parse.quote(urls[0].split(": ", 1)[1], safe=":/"), timeout=120)


def status(root: Optional[Path] = None) -> int:
    root = root or PREVIEW_ROOT
    info = running_server(root)
    print(f"server: http://{HOST}:{info['port']}/ (pid {info['pid']})" if info
          else "server: not running")
    staged = sorted(d.name for d in (root / "datasets").iterdir()) if (root / "datasets").is_dir() else []
    for did in staged:
        print(did)
        for line in _urls(did, info and info["port"], root):
            print(line)
    if not staged:
        print("nothing staged")
    return 0


# ── watch ────────────────────────────────────────────────────────────────


def _watched(dataset_id: str, recipes_root: Path) -> dict[Path, int]:
    """mtimes of what a render reads: the recipe dir, prepare's data
    manifest and the pending tags."""
    paths = [p for p in (recipes_root / dataset_id).rglob("*")
             if p.is_file() and "__pycache__" not in p.parts]
    paths += [author.AUTHORING_ROOT / dataset_id / "data" / "manifest.json",
              pending_tags_path(dataset_id)]
    out = {}
    for p in paths:
        try:
            out[p] = p.stat().st_mtime_ns
        except OSError:
            pass
    return out


def watch(ids: list[str], recipes_root: Path, root: Path) -> int:
    seen = {did: _watched(did, recipes_root) for did in ids}
    print(f"watching {', '.join(d[:8] for d in ids)} — Ctrl-C to stop "
          "(the server keeps running; `preview stop` ends it)")
    try:
        while True:
            time.sleep(WATCH_INTERVAL_S)
            for did in ids:
                now = _watched(did, recipes_root)
                if now != seen[did]:
                    seen[did] = now
                    render(did, recipes_root, root)
    except KeyboardInterrupt:
        return 0


# ── cli ──────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    sys.stdout.reconfigure(line_buffering=True)  # --watch lines show up in a piped log
    if argv[:1] == ["stop"]:
        return stop()
    if argv[:1] == ["status"]:
        return status()
    p = argparse.ArgumentParser(
        prog="python -m services.page_builder.cli.preview",
        description="Render recipes over local data and serve them in the real dataset shell. "
                    "Also: `status`, `stop`.",
    )
    p.add_argument("ids", nargs="+", help="dataset id(s) with recipes/<id>/ and `author prepare` data")
    p.add_argument("--watch", action="store_true", help="re-render on every recipe change")
    p.add_argument("--no-serve", action="store_true", help="stage into tmp/preview/ only")
    p.add_argument("--recipes", type=Path, default=author.RECIPES_ROOT)
    args = p.parse_args(argv)

    root = PREVIEW_ROOT
    ok = [did for did in args.ids if render(did, args.recipes, root)]
    port = None
    if not args.no_serve and (ok or args.watch):
        port = ensure_server(root)["port"]
        for did in ok:
            _warm(did, port, root)
    for did in args.ids:
        lines = _urls(did, port, root)
        if lines:
            print(did)
            for line in lines:
                print(line)
    if args.watch:
        return watch(args.ids, args.recipes, root)
    return 0 if len(ok) == len(args.ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
