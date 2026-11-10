"""
Scanner service — scans CKAN and persists per-source state to Firestore.

The `Scanner` class is import-safe in minimal containers (just logging, no
rich/typer deps). The CLI at the bottom of this module is only used for local
debugging and relies on `typer` + `rich`; those are optional for the
Cloud Run builder.
"""

import asyncio
import logging
from datetime import UTC, datetime

from services.shared.resources import pick_primary_resource_id

from .client import CKANClient
from .config import ScannerSettings, settings
from .detector import ChangeDetector
from .filters import DatasetFilter, create_filter
from .models import DatasetStatus, ScanResult, ScanSummary
from .state import StateDB

log = logging.getLogger("scanner")

# Per-dataset failures in a row before the scan gives up: past this the store
# or CKAN is down, and walking the rest of the listing only repeats the error.
SCAN_MAX_CONSECUTIVE_ERRORS = 20
# Error strings kept on the summary (and joined into scan_runs.error); the
# rest only count.
MAX_ERRORS_KEPT = 50


def _record_error(summary: ScanSummary, message: str) -> None:
    summary.error_count += 1
    if len(summary.errors) < MAX_ERRORS_KEPT:
        summary.errors.append(message[:500])


class Scanner:
    """Scans CKAN and persists per-source state to Firestore."""

    def __init__(
        self,
        config: ScannerSettings | None = None,
        db: StateDB | None = None,
    ):
        self.config = config or settings
        self.db = db or StateDB()

    async def scan(
        self,
        *,
        limit: int = 5,
        filter_config: DatasetFilter | None = None,
        force: bool = False,
        mode: str = "manual",
    ) -> ScanSummary:
        """Scan up to `limit` datasets. A failure on one dataset is recorded in
        `summary.errors` and the scan moves on; SCAN_MAX_CONSECUTIVE_ERRORS in
        a row (Firestore or CKAN down) stops it. A failure outside the
        per-dataset work (the package count, the listing itself) is recorded
        and re-raised. The `scan_runs` doc is closed either way."""
        summary = ScanSummary(started_at=datetime.now(UTC))
        scan_id = self.db.start_scan(mode=mode)
        detector = ChangeDetector(self.db)

        log.info("scan start — limit=%d force=%s mode=%s", limit, force, mode)

        try:
            async with CKANClient(self.config) as client:
                total_available = await client.get_package_count()
                log.info("CKAN reports %d total datasets available", total_available)

                datasets_processed = 0
                consecutive_errors = 0
                async for dataset in client.iter_all_packages(limit=limit * 3):
                    if dataset.id in self.config.EXCLUDED_DATASET_IDS:
                        continue
                    if filter_config and not filter_config.matches(dataset):
                        continue
                    datasets_processed += 1
                    try:
                        await self._scan_one(client, detector, dataset, summary, force)
                        consecutive_errors = 0
                    except Exception as e:  # one dataset; the scan goes on
                        consecutive_errors += 1
                        log.exception("scan: %s failed", dataset.id[:8])
                        _record_error(summary, f"{dataset.id[:8]}: {type(e).__name__}: {e}")
                        if consecutive_errors >= SCAN_MAX_CONSECUTIVE_ERRORS:
                            raise RuntimeError(
                                f"scan stopped after {consecutive_errors} failures in a row"
                            ) from e
                    # Reached after a success and after a recorded failure.
                    if datasets_processed >= limit:
                        break
        except BaseException as e:
            _record_error(summary, f"scan aborted: {type(e).__name__}: {e}")
            raise
        finally:
            summary.completed_at = datetime.now(UTC)
            self.db.complete_scan(
                scan_id,
                sources_seen=summary.datasets_scanned,
                new=summary.datasets_new,
                updated=summary.datasets_updated,
                unchanged=summary.datasets_unchanged,
                errors=summary.errors,
                started_at=summary.started_at,
            )
        log.info(
            "scan done — scanned=%d new=%d updated=%d unchanged=%d errors=%d",
            summary.datasets_scanned,
            summary.datasets_new,
            summary.datasets_updated,
            summary.datasets_unchanged,
            summary.error_count,
        )
        return summary

    async def _scan_one(self, client, detector, dataset, summary: ScanSummary,
                        force: bool) -> None:
        status = detector.detect_status(dataset, force=force)
        log.info(
            "%s %s (%s) resources=%d",
            status.value.upper(),
            dataset.id[:8],
            (dataset.title or "")[:60],
            len(dataset.resources),
        )
        if status in (DatasetStatus.NEW, DatasetStatus.UPDATED):
            primary_id = pick_primary_resource_id(dataset.resources)
            if primary_id:
                dataset.record_count = await client.datastore_total(primary_id)
            self.db.save_dataset(dataset, status)
        # Counted once the dataset's work is done, so a failed save isn't
        # reported as scanned.
        summary.datasets_scanned += 1
        if status == DatasetStatus.NEW:
            summary.datasets_new += 1
        elif status == DatasetStatus.UPDATED:
            summary.datasets_updated += 1
        else:
            summary.datasets_unchanged += 1
        summary.results.append(ScanResult(dataset=dataset, status=status))


# ----- CLI (optional — only loaded if typer/rich are installed) --------------

try:  # pragma: no cover - CLI deps are optional in the Cloud Run container
    import typer
    from rich.console import Console
    from rich.table import Table
except ImportError:  # pragma: no cover
    typer = None  # type: ignore[assignment]


if typer is not None:
    app = typer.Typer(
        name="scanner",
        help="Scan datasets from data.gov.il CKAN API into Firestore",
        add_completion=False,
    )
    console = Console()

    def print_summary(summary: ScanSummary) -> None:
        table = Table(title="Scan Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right")
        table.add_row("Datasets Scanned", str(summary.datasets_scanned))
        table.add_row("New Datasets", f"[green]{summary.datasets_new}[/green]")
        table.add_row("Updated Datasets", f"[yellow]{summary.datasets_updated}[/yellow]")
        table.add_row("Unchanged Datasets", f"[dim]{summary.datasets_unchanged}[/dim]")
        if summary.errors:
            table.add_row("Errors", f"[red]{len(summary.errors)}[/red]")
        duration = (
            (summary.completed_at - summary.started_at).total_seconds()
            if summary.completed_at
            else 0
        )
        table.add_row("Duration", f"{duration:.1f}s")
        console.print("\n")
        console.print(table)

    @app.command()
    def scan(
        limit: int = typer.Option(5, "--limit", "-l"),
        format: str | None = typer.Option(None, "--format", "-f"),
        name_contains: str | None = typer.Option(None, "--name-contains", "-n"),
        name_regex: str | None = typer.Option(None, "--name-regex"),
        org: str | None = typer.Option(None, "--org", "-o"),
        tags: str | None = typer.Option(None, "--tags", "-t"),
        force: bool = typer.Option(False, "--force"),
    ) -> None:
        """Scan datasets from data.gov.il CKAN API and upsert into Firestore."""
        config = ScannerSettings()
        filter_config = None
        if any([format, name_contains, name_regex, org, tags]):
            filter_config = create_filter(
                name_contains=name_contains,
                name_regex=name_regex,
                formats=format,
                organization=org,
                tags=tags,
            )
        scanner = Scanner(config=config)
        summary = asyncio.run(
            scanner.scan(
                limit=limit,
                filter_config=filter_config,
                force=force,
                mode="manual",
            )
        )
        print_summary(summary)

    @app.command()
    def stats() -> None:
        """Show Firestore source-collection statistics."""
        db = StateDB()
        s = db.get_stats()
        table = Table(title="Source Collection Stats")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right")
        table.add_row("Total Datasets", str(s.get("total", 0)))
        table.add_row("Never Analyzed", str(s.get("never", 0)))
        table.add_row("Succeeded", f"[green]{s.get('succeeded', 0)}[/green]")
        table.add_row("Failed", f"[red]{s.get('failed', 0)}[/red]")
        table.add_row("Pending", f"[yellow]{s.get('pending', 0)}[/yellow]")
        console.print(table)

    @app.command()
    def history(limit: int = typer.Option(10, "--limit", "-l")) -> None:
        """Show recent scan runs."""
        db = StateDB()
        records = db.get_scan_history(limit=limit)
        if not records:
            console.print("[dim]No scan history found[/dim]")
            return
        table = Table(title="Scan History")
        table.add_column("ID", style="dim")
        table.add_column("Started")
        table.add_column("Mode")
        table.add_column("Seen", justify="right")
        table.add_column("New", justify="right", style="green")
        table.add_column("Updated", justify="right", style="yellow")
        table.add_column("Unchanged", justify="right", style="dim")
        table.add_column("Processed", justify="right", style="cyan")
        for r in records:
            started = r.get("started_at")
            started_s = (
                started.isoformat()[:19]
                if hasattr(started, "isoformat")
                else str(started or "-")[:19]
            )
            processed = r.get("processed_source_ids") or []
            table.add_row(
                r["id"][:8],
                started_s,
                r.get("mode", "-"),
                str(r.get("sources_seen", 0)),
                str(r.get("new", 0)),
                str(r.get("updated", 0)),
                str(r.get("unchanged", 0)),
                str(len(processed)),
            )
        console.print(table)

    def main() -> None:
        app()

else:

    def main() -> None:  # type: ignore[no-redef]
        raise SystemExit(
            "scanner CLI requires `typer` and `rich`; install with "
            "`pip install -r requirements.txt`"
        )


if __name__ == "__main__":
    main()
