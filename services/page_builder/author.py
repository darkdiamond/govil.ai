"""Local authoring kit — how a recipe gets written (by you, with Claude Code).

Authoring runs on your machine, once per dataset; nothing here runs in the
cloud. The `/author-dataset` skill (.claude/skills/author-dataset/SKILL.md)
drives these commands:

    prepare <id>   read the source doc (Firestore, read-only), fetch every
                   datastore resource IN FULL into tmp/authoring/<id>/data/,
                   write BRIEF.md (facts, schemas, samples, related candidates).
                   A provider source (recipes/<id>/source.json) is read from
                   that file and fetched from its provider — no Firestore.
    verify <id>    the gate before a PR — runs the recipe exactly as the
                   nightly refresh will, then: determinism, robustness on
                   perturbed data, template lint, PII grep. Writes the page
                   to tmp/model_test/<id>/ so `cli.preview render|swap` works.
    queue          datasets waiting for a recipe (issues the job opened);
                   --legacy adds published pages that have no recipe yet

tmp/authoring/ holds raw dataset content (it can include personal contact
details) — it is gitignored and must never be committed. Only
recipes/<id>/ is.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import random
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from .agent_contract import FetchLimitExceeded, FetchOutcome
from .recipe import (
    COMPUTE_FILENAME,
    MANIFEST_FILENAME,
    RESOURCE_NAME_COLUMN,
    TEMPLATE_FILENAME,
    Recipe,
    RecipeError,
    dump_model,
    kpi_format_findings,
    lint_template,
)
from .refresh import fetch_inputs, render_page, run_compute

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHORING_ROOT = REPO_ROOT / "tmp" / "authoring"
PREVIEW_OUT_ROOT = REPO_ROOT / "tmp" / "model_test"
RECIPES_ROOT = REPO_ROOT / "recipes"

# Perturbations every recipe must survive (see `verify`).
TRUNCATE_FRACTION = 0.7
SHUFFLE_SEED = 1729


def _paths(dataset_id: str) -> dict[str, Path]:
    root = AUTHORING_ROOT / dataset_id
    return {
        "root": root,
        "data": root / "data",
        "manifest": root / "data" / "manifest.json",
        "source": root / "source.json",
        "brief": root / "BRIEF.md",
        "out": PREVIEW_OUT_ROOT / dataset_id,
    }


# ── prepare ──────────────────────────────────────────────────────────────


def _source_facts(src) -> dict:
    return {
        "id": src.id,
        "title": src.title,
        "slug": src.slug,
        "notes": src.notes,
        "organization": src.organization,
        "tags": src.tags,
        "update_frequency": src.update_frequency,
        "license_title": src.license_title,
        "record_count": src.record_count,
        "metadata_modified": src.metadata_modified.isoformat() if src.metadata_modified else None,
        "resources": src.resources,
        "analysis_status": src.analysis_status,
        "page_path": src.page_path,
        "existing_agent_data": src.agent_data,
    }


def _provider_for_recipe(dataset_id: str, recipes_root: Path = RECIPES_ROOT):
    """`(provider, source_config)` when recipes/<id>/source.json declares a
    non-CKAN source, else None. Authoring is local, so the provider is built
    from env whether or not the job has it enabled."""
    from services.providers import PROVIDER_CLASSES, SOURCE_CONFIG_FILENAME, SourceConfig

    path = recipes_root / dataset_id / SOURCE_CONFIG_FILENAME
    if not path.is_file():
        return None
    source = SourceConfig.model_validate_json(path.read_text(encoding="utf-8"))
    cls = PROVIDER_CLASSES.get(source.provider)
    if cls is None:
        raise SystemExit(f"{path}: unknown provider {source.provider!r} "
                         f"(known: {', '.join(PROVIDER_CLASSES)})")
    return cls.from_env(), source


def _fetch_or_skip(fetch: Callable, *args, **kwargs) -> tuple[Any, Optional[str]]:
    """(fetch(...), None), or (None, limit) when it stopped at a limit; the
    limit is kept as the manifest entry's `skipped`."""
    try:
        return fetch(*args, **kwargs), None
    except FetchLimitExceeded as e:
        return None, e.limit


def _skip_note(entry: dict) -> str:
    return f" (skipped: over {entry['skipped']})" if entry.get("skipped") else ""


def _prepare_provider(dataset_id: str, provider, source) -> Path:
    """prepare() for a provider source: facts from source.json + the
    provider, data from the provider — no Firestore needed."""
    p = _paths(dataset_id)
    if p["data"].exists():
        shutil.rmtree(p["data"])
    p["data"].mkdir(parents=True)
    cfg = provider.parse_config(dataset_id, source)
    pf = provider.facts(dataset_id, source, cfg)
    resources = [r.model_dump() for r in pf.resources]
    manifest, sections = [], {}
    for i, res in enumerate(resources, 1):
        preview, skipped = _fetch_or_skip(provider.preview, res)
        preview = preview or {}
        dest = p["data"] / f"{i}.csv"
        out = None
        if not skipped:
            out, skipped = _fetch_or_skip(
                provider.fetch_to_file, res, dest, max_bytes=provider.settings.max_bytes
            )
        entry = {
            "resource_id": res["id"],
            "name": res["name"],
            "format": res["format"],
            "fields": [f["id"] for f in preview.get("fields") or []],
            "field_types": {f["id"]: f.get("type") for f in preview.get("fields") or []},
            "total": int(preview.get("total") or 0),
            "file": dest.name if out else None,
            "rows": out.rows if out else 0,
            **({"skipped": skipped} if skipped else {}),
        }
        manifest.append(entry)
        if out:
            sections[res["id"]] = provider.brief_section(res, dest)
        print(f"  {res['id']} {res['name'][:50]!r}: {entry['rows']:,} rows{_skip_note(entry)}",
              file=sys.stderr)
    p["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    facts = {
        "id": dataset_id,
        "title": pf.title,
        "notes": pf.notes,
        "organization": pf.organization,
        "tags": pf.tags,
        "update_frequency": pf.update_frequency,
        "license_title": pf.license_title,
        "record_count": sum(m["rows"] for m in manifest),
        "metadata_modified": None,
        "resources": resources,
        "provider": provider.key,
        "provider_label": provider.label,
        "source_url": pf.source_url,
        "provider_sections": sections,
        "provider_notes": provider.authoring_notes(),
    }
    p["source"].write_text(json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    p["brief"].write_text(_brief(facts, manifest, [], p), encoding="utf-8")
    return p["brief"]


def prepare(dataset_id: str) -> Path:
    from services.shared.firestore import FirestoreStateStore
    from services.shared.resources import select_prefetch_resources

    from .agent_contract import fetch_resource_preview, fetch_resource_records_to_file
    from .refresh import _env_int, _DEFAULT_MAX_BYTES, _DEFAULT_MAX_RECORDS

    provider = _provider_for_recipe(dataset_id)
    if provider is not None:
        return _prepare_provider(dataset_id, *provider)

    store = FirestoreStateStore()
    src = store.get_source(dataset_id)
    if src is None:
        raise SystemExit(f"{dataset_id}: no sources/ doc — run the scanner first")
    p = _paths(dataset_id)
    if p["data"].exists():
        shutil.rmtree(p["data"])
    p["data"].mkdir(parents=True)
    facts = _source_facts(src)
    p["source"].write_text(json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    import time

    max_records = _env_int("REFRESH_MAX_RECORDS", _DEFAULT_MAX_RECORDS)
    max_bytes = _env_int("REFRESH_MAX_BYTES", _DEFAULT_MAX_BYTES)
    modified = {r.get("id"): r.get("last_modified") for r in src.resources or []}
    manifest = []
    for i, res in enumerate(select_prefetch_resources(src.resources or []), 1):
        preview = fetch_resource_preview(res["id"]) or {}
        total = int(preview.get("total") or 0)
        lm = modified.get(res["id"])
        entry = {
            "resource_id": res["id"],
            "name": res.get("name") or "",
            "format": res.get("format") or "",
            # `pick: "latest"` orders by it; verify must see what prod sees.
            "last_modified": lm.isoformat() if hasattr(lm, "isoformat") else lm,
            "fields": [f["id"] for f in preview.get("fields") or [] if f["id"] != "_id"],
            "field_types": {f["id"]: f.get("type") for f in preview.get("fields") or [] if f["id"] != "_id"},
            "total": total,
            "file": None,
            "rows": 0,
        }
        if 0 < total <= max_records:
            dest = p["data"] / f"{i}.csv"
            out, skipped = _fetch_or_skip(
                fetch_resource_records_to_file, res["id"], total, dest,
                max_bytes=max_bytes, page_size=25_000, page_timeout_s=60.0,
                deadline=time.monotonic() + 900, sample_target_rows=0, prefer_sample=False,
            )
            if skipped:
                entry["skipped"] = skipped
            if out is not None:
                entry.update(file=dest.name, rows=out.rows)
        manifest.append(entry)
        print(f"  {res['id'][:8]} {entry['name'][:50]!r}: {entry['rows']:,}/{total:,} rows"
              f"{_skip_note(entry)}", file=sys.stderr)
    p["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    related = []
    org = (src.organization or {}).get("name") or ""
    if org:
        related = [
            {"id": s.id, "title": s.title, "tags": s.tags}
            for s in store.list_org_sources(org, exclude_id=dataset_id)
        ]
    p["brief"].write_text(_brief(facts, manifest, related, p), encoding="utf-8")
    return p["brief"]


def _sample_rows(path: Path, n: int = 5) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        out = []
        for i, row in enumerate(csv.DictReader(f)):
            if i >= n:
                break
            out.append({k: (v[:80] if isinstance(v, str) else v) for k, v in row.items()})
        return out


def _brief(facts: dict, manifest: list[dict], related: list[dict], p: dict) -> str:
    provider = facts.get("provider")
    head = [
        f"# Authoring brief — {facts['title']}",
        "",
        f"- dataset_id: `{facts['id']}`",
        f"- organization: {(facts.get('organization') or {}).get('title', '')}",
    ]
    if provider:
        head += [
            f"- source: {facts.get('provider_label')} (provider `{provider}`, "
            f"recipes/{facts['id']}/source.json)",
            f"- source page: {facts.get('source_url')}",
            f"- update_frequency: {facts.get('update_frequency')}",
            f"- tags: {', '.join(facts.get('tags') or [])}",
            "",
            "## Source notes (source.json)",
        ]
    else:
        head += [
            f"- CKAN metadata_modified: {facts['metadata_modified']}",
            f"- update_frequency: {facts.get('update_frequency')}",
            f"- tags: {', '.join(facts.get('tags') or [])}",
            f"- live page: {'yes — https://govil.ai/' + (facts.get('page_path') or '') if facts.get('page_path') else 'none yet'}",
            f"- data.gov.il: https://data.gov.il/dataset/{facts['id']}",
            "",
            "## CKAN notes",
        ]
    lines = head + [
        "",
        (facts.get("notes") or "").strip()[:3000],
        "",
        "## Data files (FULL exports; read with dtype=str, keep_default_na=False)",
        "",
    ]
    for m in manifest:
        if m["file"]:
            status = f"`data/{m['file']}` — {m['rows']:,} rows"
        elif m.get("skipped") == "bytes":
            status = (f"NOT fetched ({m['total']:,} rows — export over the byte cap; "
                      "fetch only the `columns` the page reads, or set recipe `limits`)")
        elif m.get("skipped") == "wall_budget":
            status = (f"NOT fetched ({m['total']:,} rows — export ran out of wall budget; "
                      "fewer `columns`, or a recipe `limits.wall_budget_s`)")
        else:
            status = f"NOT fetched ({m['total']:,} rows — over REFRESH_MAX_RECORDS or empty)"
        lines += [
            f"### {m['name'] or m['resource_id']}",
            f"- resource_id: `{m['resource_id']}` ({m['format']})",
            f"- {status}",
            f"- columns: {json.dumps(m['field_types'], ensure_ascii=False)}",
        ]
        if m["file"]:
            lines += ["- sample:", "```json",
                      json.dumps(_sample_rows(p['data'] / m['file']), ensure_ascii=False, indent=1),
                      "```"]
        section = (facts.get("provider_sections") or {}).get(m["resource_id"])
        if section:
            lines += ["", section]
        lines.append("")
    if facts.get("provider_notes"):
        lines += [f"## Source rules ({facts.get('provider_label')})", "",
                  facts["provider_notes"], ""]
    if facts.get("existing_agent_data"):
        lines += ["## Current page's agent_data (legacy cloud agent)", "", "```json",
                  json.dumps(facts["existing_agent_data"], ensure_ascii=False, indent=1), "```", ""]
    if related:
        lines += ["## related_ids candidates (same ministry)", "", "```json",
                  json.dumps(related, ensure_ascii=False, indent=1), "```", ""]
    lines += [
        "## Write",
        "",
        f"`recipes/{facts['id']}/` → `{MANIFEST_FILENAME}`, `{COMPUTE_FILENAME}`, `{TEMPLATE_FILENAME}`",
        f"then `python -m services.page_builder.author verify {facts['id']}`.",
    ]
    return "\n".join(lines) + "\n"


# ── verify ───────────────────────────────────────────────────────────────


class _LocalCkan:
    """Serves prepare()'s cached files through fetch_inputs' hooks, so verify
    resolves + loads inputs with exactly the code the nightly refresh uses."""

    def __init__(self, data_dir: Path, manifest: list[dict], transform=None):
        self.data_dir = data_dir
        self.by_id = {m["resource_id"]: m for m in manifest}
        self.transform = transform

    def preview(self, rid: str) -> Optional[dict]:
        m = self.by_id.get(rid)
        if not m:
            return None
        return {"fields": [{"id": f} for f in m["fields"]], "total": m["total"]}

    def fetch(self, rid, total, dest, **kw) -> Optional[FetchOutcome]:
        m = self.by_id.get(rid)
        if m and m.get("skipped"):
            raise FetchLimitExceeded(m["skipped"], f"prepare skipped {rid[:8]}: over {m['skipped']}")
        if not m or not m.get("file"):
            return None
        with open(self.data_dir / m["file"], encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        header, body = rows[0], rows[1:]
        if self.transform:
            body = self.transform(body)
        fields = kw.get("fields")
        if fields and all(c in header for c in fields):
            # The prod export carries only `fields`; measure the cap on that.
            # A missing column is left for fetch_inputs to report.
            idx = [header.index(c) for c in fields]
            header, body = fields, [[r[j] if j < len(r) else "" for j in idx] for r in body]
        with open(dest, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(body)
        size = dest.stat().st_size
        if "max_bytes" in kw and size > kw["max_bytes"]:
            dest.unlink()
            raise FetchLimitExceeded("bytes", f"{rid[:8]}: {size:,} bytes > cap {kw['max_bytes']:,}")
        return FetchOutcome(rows=len(body), bytes=size, mode="full")


def _truncate(rows: list) -> list:
    return rows[: max(1, int(len(rows) * TRUNCATE_FRACTION))]


def _shuffle(rows: list) -> list:
    out = list(rows)
    random.Random(SHUFFLE_SEED).shuffle(out)
    return out


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_IL_PHONE_RE = re.compile(r"(?<!\d)0(?:[2-9]|5\d|7\d)-?\d{7}(?!\d)")


def _pii_findings(recipe: Recipe) -> list[str]:
    out = []
    for name in (COMPUTE_FILENAME, TEMPLATE_FILENAME, MANIFEST_FILENAME, COVERAGE_FILENAME):
        if not (recipe.root / name).is_file():
            continue
        text = (recipe.root / name).read_text(encoding="utf-8")
        for rx, what in ((_EMAIL_RE, "email"), (_IL_PHONE_RE, "phone number")):
            for m in rx.finditer(text):
                out.append(f"PII: {name} contains a literal {what} {m.group(0)!r}")
    return out


# compute() must be a pure function of the frames: the same CKAN version has
# to render the same page tonight and in six months.
# Modules count only as imports or attribute use, so an insight id or a
# string that happens to read "requests" / "random" is not impure.
_IMPURE_MODULES = r"(?:random|uuid|requests|urllib|httpx|socket|subprocess|secrets)"
_IMPURE_RE = re.compile(
    r"\b(?:datetime\.(?:now|today|utcnow)|date\.today|time\.time|open|"
    r"pd\.Timestamp\.(?:now|today))\s*\("
    rf"|^\s*(?:import|from)\s+{_IMPURE_MODULES}\b"
    rf"|(?<![\w.\"']){_IMPURE_MODULES}\.\w"
    r"|\bnp\.random\b|\bos\.(?:environ|getenv)\b"
    # The wall clock spelled as a string: pd.Timestamp("now"), to_datetime("today"), …
    r"""|\b(?:Timestamp|to_datetime|datetime64)\s*\(\s*['"](?:now|today)['"]"""
    # File I/O beyond open(): compute() gets its data only as frames.
    r"|\.(?:read_text|read_bytes|write_text|write_bytes)\s*\("
    r"|\bpd\.read_\w+\s*\("
)


def _purity_findings(recipe: Recipe) -> list[str]:
    out = []
    for n, line in enumerate(recipe.compute_path.read_text(encoding="utf-8").splitlines(), 1):
        code = line.split("#", 1)[0]
        m = _IMPURE_RE.search(code)
        if m:
            out.append(f"IMPURE: compute.py:{n} uses {m.group(0).strip()!r} — compute() "
                       "may not read the clock, randomness, files, env or network")
    return out


# House style: no em dash (U+2014) in anything a visitor reads. Checked on the
# recipe source, not the rendered page, so an em dash inside CKAN data values
# is not flagged. Comments and docstrings are exempt; every other string
# literal in compute.py counts, since most of them end up on the page.
# Verify-only: legacy recipes still refresh nightly and comply when next touched.

# The character itself, or an HTML entity that renders as one.
_EM_DASH_RE = re.compile(r"\u2014|&mdash;|&#0*8212;|&#[xX]0*2014;")
_TPL_COMMENT_RE = re.compile(r"\{#.*?#\}|<!--.*?-->", re.S)
# A JS string literal (kept, so "a // b" or "https://…" stays checked) or a comment (blanked).
_JS_STRING_OR_COMMENT_RE = re.compile(
    r"""("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)|/\*.*?\*/|//[^\n]*""", re.S)
_SCRIPT_RE = re.compile(r"(<script\b[^>]*>)(.*?)(</script>)", re.S | re.I)


def _keep_newlines(m: re.Match) -> str:
    # Blank a comment but keep its line breaks, so finding line numbers stay true.
    return "\n" * m.group(0).count("\n")


def _strip_js_comments(js: str) -> str:
    return _JS_STRING_OR_COMMENT_RE.sub(lambda c: c.group(1) or _keep_newlines(c), js)


def _em_dash_findings(recipe: Recipe) -> list[str]:
    out = []
    py = recipe.compute_path.read_text(encoding="utf-8")
    tree = ast.parse(py)
    docstrings = {id(n.value) for n in ast.walk(tree)
                  if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    # Matched on the literal's source text, not its value: spelling it "\u2014"
    # is the opt-out for code that must match an em dash inside the data.
    lines = sorted({n.lineno for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and id(n) not in docstrings
                    and _EM_DASH_RE.search(ast.get_source_segment(py, n) or n.value)})
    out += [f"EM-DASH: compute.py:{n} has an em dash (U+2014) in a string literal" for n in lines]

    src = _TPL_COMMENT_RE.sub(_keep_newlines,
                              recipe.template_path.read_text(encoding="utf-8"))
    src = _SCRIPT_RE.sub(lambda m: m.group(1) + _strip_js_comments(m.group(2)) + m.group(3), src)
    out += [f"EM-DASH: template.html.j2:{n} has an em dash (U+2014)"
            for n, line in enumerate(src.splitlines(), 1) if _EM_DASH_RE.search(line)]
    if out:
        out.append("EM-DASH: user-facing text uses no em dash; rewrite with a colon, "
                   "comma, parentheses or a new sentence (a year range keeps its en dash –)")
    return out


# Chart fallback: a chart small enough to tabulate (~20 rows) carries a
# <details><table> of its own numbers in its section. A larger series is
# marked data-fallback="explorer" on the chart element — the shell's data
# explorer and download section under every page are its tabular view, so
# no per-chart link to data.gov.il. Either way it is a deliberate choice.
_CHART_DIV_RE = re.compile(
    r'<div\b(?=[^>]*\bid="([^"]+)")(?=[^>]*\brole="img")[^>]*>', re.IGNORECASE
)
_EXPLORER_FALLBACK = 'data-fallback="explorer"'


def _fallback_findings(html: str) -> list[str]:
    # GovMap containers carry no role="img", so they never match here (the
    # shell's explorer is their tabular view) — no id-based exemption.
    out = []
    for m in _CHART_DIV_RE.finditer(html):
        chart_id = m.group(1)
        if _EXPLORER_FALLBACK in m.group(0):
            continue
        start = html.rfind("<section", 0, m.start())
        # The nearest <section> must still be open at the chart; otherwise
        # the chart sits outside any section and has no section to carry a
        # fallback (don't borrow a closed neighbour's table).
        if start >= 0 and html.find("</section>", start, m.start()) != -1:
            start = -1
        end = html.find("</section>", m.end())
        chunk = html[start:end] if start >= 0 and end >= 0 else ""
        if "<table" not in chunk:
            out.append(
                f"NO-FALLBACK: chart #{chart_id} has no <details><table> in its "
                "section — add one (≤20 rows), or mark a larger series "
                f'{_EXPLORER_FALLBACK} on the chart element'
            )
    return out


# A per-chart "download at data.gov.il" link only repeats the shell's own
# downloads + explorer under the page.
_SOURCE_LINK_RE = re.compile(r'href="https://(?:www\.)?data\.gov\.il/', re.IGNORECASE)


def _source_link_findings(html: str) -> list[str]:
    # Checked on the RENDERED page, so a link built from a model value or a
    # Jinja expression is caught as well as a literal one.
    n = len(_SOURCE_LINK_RE.findall(html))
    return [f"SOURCE-LINK: page links to data.gov.il {n}x — the shell already "
            "renders downloads and the data explorer under every page; remove them"] if n else []


def _explorer_marked(html: str) -> list[str]:
    return [m.group(1) for m in _CHART_DIV_RE.finditer(html) if _EXPLORER_FALLBACK in m.group(0)]


# Coverage: every column of every input is accounted for — which view uses
# it, or why it gets none. Lives beside the recipe (never read by the
# refresh), so it changes nothing in production.
COVERAGE_FILENAME = "coverage.json"
_COVERAGE_TAGS = ("kpi:", "insight:", "table:", "text:", "map:", "filter:", "key:")


def _coverage_findings(
    recipe: Recipe, inputs: dict, manifest: list[dict], html: str, model: dict
) -> tuple[list[str], list[str]]:
    path = recipe.root / COVERAGE_FILENAME
    if not path.is_file():
        return [f"COVERAGE: recipes/{recipe.dataset_id}/{COVERAGE_FILENAME} is missing — "
                'map every "<input>.<column>" to the chart id(s) / kpi: / insight: / '
                'table: that use it, or to "skip: <reason>"'], []
    try:
        cov = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(cov, dict) and all(isinstance(v, str) for v in cov.values())
    except Exception:
        return [f"COVERAGE: {COVERAGE_FILENAME} must be a JSON object of strings"], []
    fields = {m["resource_id"]: m["fields"] for m in manifest}
    needed = {
        f"{name}.{col}"
        for name, parts in inputs.items()
        for part in parts
        for col in fields.get(part.resource_id, [])
        if col != "_id"  # datastore row id; dropped from exports (stale preps may list it)
    }
    # Whole resources no input reads (a translated twin, a lookup table)
    # need a reason too: "resource:<id>": "skip: …".
    read = {part.resource_id for parts in inputs.values() for part in parts}
    needed |= {f"resource:{m['resource_id']}" for m in manifest if m["resource_id"] not in read}
    problems = []
    missing = sorted(needed - cov.keys())
    if missing:
        problems.append(f"COVERAGE: {len(missing)} column(s)/resource(s) unaccounted for: "
                        + ", ".join(missing[:15]) + (" …" if len(missing) > 15 else ""))
    # The synthetic per-file column a concat input carries may be documented.
    synthetic = {f"{i.name}.{RESOURCE_NAME_COLUMN}" for i in recipe.manifest.inputs if i.concat}
    stale = sorted(cov.keys() - needed - synthetic)
    if stale:
        problems.append("COVERAGE: entries for columns/resources the recipe doesn't read "
                        "(typo or stale): " + ", ".join(stale[:15]))
    # A column the recipe never fetches can't be "used" on the page.
    unfetched = set()
    for i in recipe.manifest.inputs:
        if i.columns:
            for part in inputs.get(i.name, []):
                unfetched |= {f"{i.name}.{c}" for c in fields.get(part.resource_id, [])
                              if c not in i.columns}
    for key in sorted(unfetched & cov.keys()):
        if not cov[key].strip().startswith("skip:"):
            problems.append(f"COVERAGE: {key} is marked used but not in the input's "
                            "`columns`, so it is never fetched")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    kpis = set((model.get("kpis") or {}).keys())
    used = skipped = 0
    for key, value in cov.items():
        value = value.strip()
        if value.startswith("skip:"):
            skipped += 1
            if len(value[5:].strip()) < 8:
                problems.append(f"COVERAGE: {key}: give a real reason after 'skip:'")
            continue
        used += 1
        # "<ref>, <ref> — free note": refs before the first ' — ' / ' - ' / ';'.
        head = re.split(r"\s+[—–-]\s+|;", value, maxsplit=1)[0]
        tokens = [t.strip() for t in head.split(",") if t.strip()]
        if not tokens:
            problems.append(f"COVERAGE: {key}: no element id or kpi:/insight:/table: reference")
        for t in tokens:
            if t.startswith("kpi:") and t[4:].strip() not in kpis:
                problems.append(f"COVERAGE: {key} → {t!r}: the model has no such KPI")
            elif not t.startswith(_COVERAGE_TAGS) and t not in ids:
                problems.append(f"COVERAGE: {key} → {t!r} is not an element id on the page "
                                "(put free notes after ' — ')")
    notes = [f"coverage: {len(needed)} column(s) — {used} used, {skipped} skipped"]
    return problems, notes


def _resources_from_manifest(manifest: list[dict]) -> list[dict]:
    return [
        {"id": m["resource_id"], "name": m["name"], "format": m["format"],
         "last_modified": m.get("last_modified"), "datastore_active": True}
        for m in manifest
    ]


def verify(dataset_id: str, recipes_root: Path = RECIPES_ROOT, *, allow_order_dependent: bool = False) -> int:
    p = _paths(dataset_id)
    if not p["manifest"].is_file():
        raise SystemExit(f"run `author prepare {dataset_id}` first")
    manifest = json.loads(p["manifest"].read_text(encoding="utf-8"))
    resources = _resources_from_manifest(manifest)
    recipe = Recipe.load(recipes_root / dataset_id)
    problems: list[str] = []
    notes: list[str] = []
    provider = None
    try:
        provider = _provider_for_recipe(dataset_id, recipes_root)
        if provider is not None:
            prov, source = provider
            prov.facts(dataset_id, source, prov.parse_config(dataset_id, source))
            notes.append(f"source.json OK — provider {prov.key}")
    except (SystemExit, Exception) as e:  # a bad source.json is a finding, not a crash
        problems.append(f"SOURCE-CONFIG: recipes/{dataset_id}/source.json: {e}")
        provider = None

    problems += lint_template(
        recipe.template_path.read_text(encoding="utf-8"),
        recipe.manifest.lint_allow_numbers,
    )
    problems += _pii_findings(recipe)
    problems += _purity_findings(recipe)
    problems += _em_dash_findings(recipe)

    work = Path(tempfile.mkdtemp(prefix=f"author-{dataset_id[:8]}-"))
    try:
        def run(transform=None, tag="full"):
            ckan = _LocalCkan(p["data"], manifest, transform)
            d = work / tag
            inputs = fetch_inputs(recipe, resources, d, preview_fn=ckan.preview, fetch_fn=ckan.fetch)
            raw = run_compute(recipe, inputs, work)
            page = render_page(recipe, raw, work, inputs)
            return raw, page, inputs

        try:
            raw, page, inputs = run()
        except RecipeError as e:
            print(f"FAIL [{e.reason}] {e}")
            return 1
        rows = {k: sum(i.rows for i in v) for k, v in inputs.items()}
        charts = len(_CHART_DIV_RE.findall(page.content_html))
        notes.append(f"full run OK — rows {rows}, {charts} chart(s), "
                     f"{len(raw.get('insights') or [])} insights, "
                     f"{len(page.content_html):,} bytes")
        problems += _fallback_findings(page.content_html)
        problems += _source_link_findings(page.content_html)
        problems += kpi_format_findings(page.content_html)
        explorer = _explorer_marked(page.content_html)
        if explorer and provider is not None and not provider[0].presentation().explorer:
            problems.append(
                "NO-EXPLORER: this source has no live data explorer under the page — "
                "give chart(s) " + ", ".join(explorer) + " a <details><table> "
                "(downsample) instead of data-fallback=\"explorer\""
            )
        elif explorer:
            # Visible opt-outs: each should be a genuinely large series.
            notes.append("explorer fallback (no table): " + ", ".join(explorer))
        cov_problems, cov_notes = _coverage_findings(
            recipe, inputs, manifest, page.content_html, raw
        )
        problems += cov_problems
        notes += cov_notes

        raw2, page2, _ = run(tag="again")
        if dump_model(raw) != dump_model(raw2) or page.content_html != page2.content_html:
            problems.append("DETERMINISM: two runs on identical data produced different output")

        try:
            rawt, _, _ = run(_truncate, "truncated")
            if dump_model(rawt) == dump_model(raw):
                problems.append(
                    f"ROBUSTNESS: model unchanged after dropping {1 - TRUNCATE_FRACTION:.0%} "
                    "of rows — some numbers are not computed from the data"
                )
            notes.append(f"truncated run OK — {len(rawt.get('insights') or [])} insights: "
                         + " | ".join(i['text_he'] for i in rawt.get('insights') or []))
        except RecipeError as e:
            problems.append(f"ROBUSTNESS: recipe fails on {TRUNCATE_FRACTION:.0%} of the rows "
                            f"[{e.reason}]: {e}")

        try:
            raws, _, _ = run(_shuffle, "shuffled")
            if dump_model(raws) != dump_model(raw):
                msg = ("ORDER-DEPENDENT: shuffling the rows changed the model — sort "
                       "explicitly (stable sort, full tie-break keys) instead of "
                       "relying on CKAN row order")
                (notes if allow_order_dependent else problems).append(msg)
        except RecipeError as e:
            problems.append(f"ROBUSTNESS: recipe fails on shuffled rows [{e.reason}]: {e}")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    p["out"].mkdir(parents=True, exist_ok=True)
    (p["out"] / "content.html").write_text(page.content_html, encoding="utf-8")
    (p["out"] / "agent_data.json").write_text(
        json.dumps(page.agent_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (p["out"] / "model.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for n in notes:
        print(f"  · {n}")
    for prob in problems:
        print(f"  ✗ {prob}")
    print(f"page → {p['out'] / 'content.html'}")
    print(f"preview: python -m services.page_builder.cli.preview render {dataset_id}")
    if problems:
        print(f"FAIL — {len(problems)} problem(s)")
        return 1
    print("PASS")
    return 0


# ── queue ────────────────────────────────────────────────────────────────


def queue(*, legacy: bool, recipes_root: Path = RECIPES_ROOT) -> int:
    from services.shared.firestore import FirestoreStateStore

    store = FirestoreStateStore()
    have = {d.name for d in recipes_root.iterdir()} if recipes_root.is_dir() else set()
    rows = []
    for doc_id, state in store.iter_authoring_queue():
        if doc_id not in have:
            rows.append((doc_id, state.get("authoring_reason"), state.get("authoring_issue"),
                         state.get("title", "")))
    if legacy:
        queued = {r[0] for r in rows}
        for src in store.iter_succeeded_sources():
            if src.id not in have and src.id not in queued:
                rows.append((src.id, "legacy", None, src.title))
    for doc_id, reason, issue, title in rows:
        print(f"{doc_id}  {reason or '-':15} {('#' + str(issue)) if issue else '-':6} {title[:70]}")
    print(f"{len(rows)} dataset(s) without a recipe", file=sys.stderr)
    return 0


def _cli(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("prepare")
    sp.add_argument("dataset_id")
    sv = sub.add_parser("verify")
    sv.add_argument("dataset_id")
    sv.add_argument("--recipes", type=Path, default=RECIPES_ROOT)
    sv.add_argument("--allow-order-dependent", action="store_true",
                    help="downgrade the shuffle check to a note (e.g. 'latest row' semantics)")
    sq = sub.add_parser("queue")
    sq.add_argument("--legacy", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "prepare":
        print(prepare(args.dataset_id))
        return 0
    if args.cmd == "verify":
        return verify(args.dataset_id, args.recipes, allow_order_dependent=args.allow_order_dependent)
    return queue(legacy=args.legacy)


if __name__ == "__main__":
    import logging
    import os

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING"))
    sys.exit(_cli())
