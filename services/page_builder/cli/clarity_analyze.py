"""CLI: pull a Microsoft Clarity snapshot for govil.ai.

Fetches the six dimension slices we care about (overview, per-URL, device,
geo/source, URL×device, channel/campaign) into `tmp/clarity/<YYYY-MM-DD>/`,
then writes a README that hands off to Claude for analysis.

    python -m services.page_builder.cli.clarity_analyze --dry-run
    python -m services.page_builder.cli.clarity_analyze --days 3

Reads GOVIL_CLARITY_API from `.env` at the repo root.

The Clarity Data Export API caps usage at 10 requests/project/day and returns
only the last 1-3 days — this script burns 6 requests per run and leaves 4
in reserve.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = REPO_ROOT / "tmp" / "clarity"
API_URL = "https://www.clarity.ms/export-data/api/v1/project-live-insights"
TIMEOUT_S = 30.0
INTER_REQUEST_DELAY_S = 1.0

log = logging.getLogger("clarity")


# Each tuple: (filename_stem, label, dimensions...)
# Dimension order matches Microsoft's dimension1/dimension2/dimension3 slots.
# Every doc example includes at least dimension1 — calls without any dimension
# return 500, so we always pass one.
REQUESTS: list[tuple[str, str, tuple[str, ...]]] = [
    ("01_url", "per-URL", ("URL",)),
    ("02_device_browser_os", "device × browser × OS", ("Device", "Browser", "OS")),
    ("03_geo_source_medium", "country × source × medium", ("Country/Region", "Source", "Medium")),
    ("04_url_device", "URL × device", ("URL", "Device")),
    ("05_channel_campaign", "channel × campaign", ("Channel", "Campaign")),
    ("06_os", "OS breakdown (doc canonical example)", ("OS",)),
]


class ClarityAuthError(RuntimeError):
    pass


class ClarityRateLimitError(RuntimeError):
    """Hit the 10-req/day project quota. Do NOT retry — burns tomorrow's budget."""


class ClarityNoDataError(RuntimeError):
    """Clarity returns 500 with empty body for fresh projects with no aggregated data yet."""


class ClarityServerError(RuntimeError):
    pass


# Retry only when the request never reached Clarity (connect failures). NEVER retry
# on HTTP status errors (401/403/429/500): each retry burns daily quota for nothing.
# A read timeout or dropped response may already have been counted, so no retry.
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
    reraise=True,
)
async def _fetch(
    client: httpx.AsyncClient,
    token: str,
    num_of_days: int,
    dimensions: tuple[str, ...],
) -> Any:
    params: dict[str, Any] = {"numOfDays": num_of_days}
    for i, dim in enumerate(dimensions, start=1):
        params[f"dimension{i}"] = dim
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = await client.get(API_URL, params=params, headers=headers)
    if resp.status_code in (401, 403):
        raise ClarityAuthError(
            f"Clarity API rejected the token ({resp.status_code}): {resp.text[:200]}"
        )
    if resp.status_code == 429:
        raise ClarityRateLimitError(
            "Clarity API daily quota exhausted (10 req/project/day). "
            "Try again after UTC midnight."
        )
    if resp.status_code == 500 and not resp.content:
        # Microsoft's documented quirk: empty 500 body = "project has no aggregated
        # data in the requested window yet". Fresh projects need ~24h.
        raise ClarityNoDataError(
            f"Clarity returned 500/empty for numOfDays={num_of_days} dims={dimensions}. "
            "Likely: project is new and hasn't accumulated daily aggregates yet, "
            "or no traffic in the requested window."
        )
    if resp.status_code >= 500:
        raise ClarityServerError(
            f"Clarity {resp.status_code}: {resp.text[:200]}"
        )
    resp.raise_for_status()
    return resp.json()


def _format_plan(num_of_days: int) -> str:
    lines = [f"Clarity request plan (numOfDays={num_of_days}, {len(REQUESTS)} calls):"]
    for i, (stem, label, dims) in enumerate(REQUESTS, start=1):
        dim_str = " × ".join(dims) if dims else "(no dimensions)"
        lines.append(f"  {i}. {stem}.json  —  {label}  [{dim_str}]")
    return "\n".join(lines)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _write_readme(out_dir: Path, num_of_days: int, fetched_at: str) -> None:
    rel = _display_path(out_dir)
    lines = [
        f"# Clarity snapshot — {fetched_at}",
        "",
        f"`numOfDays={num_of_days}`, fetched via `services.page_builder.cli.clarity_analyze`.",
        "",
        "## Files",
        "",
    ]
    for stem, label, dims in REQUESTS:
        dim_str = " × ".join(dims) if dims else "(no dimensions)"
        lines.append(f"- `{stem}.json` — {label} [{dim_str}]")
    lines += [
        "",
        "## Next step",
        "",
        "Paste this back into Claude:",
        "",
        "```",
        f"Read {rel}/*.json and produce a prioritized list of UX/SEO/content",
        "improvements for govil.ai, grouped by impact tier (high / medium / low).",
        "For each suggestion include: (1) the Clarity signal that triggered it,",
        "(2) the proposed change, (3) the files most likely affected.",
        "```",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


async def _run(token: str, num_of_days: int, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).isoformat()
    meta: dict[str, Any] = {
        "fetched_at": fetched_at,
        "num_of_days": num_of_days,
        "request_count": 0,
        "errors": [],
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S)) as client:
        for i, (stem, label, dims) in enumerate(REQUESTS):
            if i > 0:
                await asyncio.sleep(INTER_REQUEST_DELAY_S)
            log.info("fetching %s (%s)", stem, label)
            try:
                payload = await _fetch(client, token, num_of_days, dims)
            except (ClarityRateLimitError, ClarityAuthError, ClarityNoDataError) as exc:
                log.error("%s — aborting remaining calls (%s)", stem, exc)
                meta["errors"].append({"file": stem, "error": str(exc)})
                break
            except (ClarityServerError, httpx.HTTPError) as exc:
                log.error("%s failed: %s", stem, exc)
                meta["errors"].append({"file": stem, "error": str(exc)})
                continue
            (out_dir / f"{stem}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            meta["request_count"] += 1
    (out_dir / "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_readme(out_dir, num_of_days, fetched_at)
    log.info(
        "wrote %d files to %s (errors: %d)",
        meta["request_count"],
        _display_path(out_dir),
        len(meta["errors"]),
    )
    return 0 if not meta["errors"] else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="clarity_analyze",
        description="Fetch a Microsoft Clarity snapshot for govil.ai.",
    )
    p.add_argument(
        "--days",
        type=int,
        choices=(1, 2, 3),
        default=3,
        help="numOfDays for the Clarity API (1-3 only; default 3).",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: tmp/clarity/<UTC-date>/).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the request plan and exit without calling the API.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)

    if args.dry_run:
        print(_format_plan(args.days))
        return 0

    load_dotenv(REPO_ROOT / ".env")
    token = os.environ.get("GOVIL_CLARITY_API")
    if not token:
        print(
            "error: GOVIL_CLARITY_API is not set. Add it to .env or export it.",
            file=sys.stderr,
        )
        return 2

    out_dir = (args.out or (DEFAULT_OUT_DIR / datetime.now(UTC).strftime("%Y-%m-%d"))).resolve()
    # Fail on an unusable --out before spending any of the daily request quota.
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"error: cannot create --out {out_dir}: {exc}", file=sys.stderr)
        return 2
    if not os.access(out_dir, os.W_OK):
        print(f"error: --out {out_dir} is not writable", file=sys.stderr)
        return 2
    return asyncio.run(_run(token, args.days, out_dir))


if __name__ == "__main__":
    sys.exit(main())
