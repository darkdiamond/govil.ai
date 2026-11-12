"""
CKAN API client for data.gov.il.

Provides async methods to interact with the Israeli government
open data portal API.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, Self

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from services.shared.ckan import EXACT_TOTAL_THRESHOLD, is_authorization_error

from .config import ScannerSettings, settings
from .models import Dataset

log = logging.getLogger("scanner.client")


class CKANError(Exception):
    """Exception raised for CKAN API errors."""


def _retryable(exc: BaseException) -> bool:
    """Transport errors (timeouts included), 5xx, 408 and 429. Any other 4xx
    (a WAF 403, a missing dataset's 404) answers the same on a second try."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code >= 500 or code in (408, 429)
    return False


# Retry policy shared by the client's CKAN requests. `reraise`: after the last
# attempt the real error reaches the caller (and scan_runs.error), not
# tenacity's opaque RetryError.
_ckan_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(_retryable),
    reraise=True,
)


class CKANClient:
    """Async client for the CKAN API."""
    
    def __init__(self, config: ScannerSettings | None = None):
        """Initialize the CKAN client."""
        self.config = config or settings
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0
    
    async def __aenter__(self) -> Self:
        """Enter async context."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.ckan_timeout),
            follow_redirects=True,
            headers={
                # data.gov.il's WAF 403s requests without a browser User-Agent.
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
            },
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def _rate_limit(self) -> None:
        """Space requests at least `ckan_request_delay` apart. Serialized by a
        lock: the reconcile sweep probes concurrently, and without it every
        waiter would read the same `_last_request_time` and fire together."""
        # Created on first use, not in __init__: tests build the client with
        # __new__, and the lock must belong to the running loop.
        lock = getattr(self, "_rate_lock", None)
        if lock is None:
            lock = self._rate_lock = asyncio.Lock()
        async with lock:
            loop = asyncio.get_running_loop()
            elapsed = loop.time() - self._last_request_time
            delay = self.config.ckan_request_delay
            if elapsed < delay:
                await asyncio.sleep(delay - elapsed)
            self._last_request_time = loop.time()
    
    @_ckan_retry
    async def _request(self, url: str, params: dict | None = None) -> dict:
        """Make a rate-limited request to the CKAN API."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")
        
        await self._rate_limit()
        
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        
        data = response.json()
        
        if not data.get("success", False):
            error = data.get("error", {})
            raise CKANError(f"CKAN API error: {error}")
        
        return data.get("result", {})
    
    async def search_packages(
        self,
        query: str | None = None,
        rows: int = 100,
        start: int = 0,
        sort: str = "metadata_modified desc",
        fq: str | None = None,
    ) -> dict[str, Any]:
        """
        Search for datasets.
        
        Args:
            query: Search query string
            rows: Number of results to return
            start: Offset for pagination
            sort: Sort order
            fq: Filter query (Solr syntax)
        
        Returns:
            Dictionary with 'count' and 'results' keys.
        """
        params = {
            "rows": rows,
            "start": start,
            "sort": sort,
        }
        
        if query:
            params["q"] = query
        
        if fq:
            params["fq"] = fq
        
        result = await self._request(self.config.package_search_url, params)
        
        return {
            "count": result.get("count", 0),
            "results": result.get("results", []),
        }
    
    async def get_package(self, package_id: str) -> Dataset:
        """
        Get full details for a specific dataset.
        
        Args:
            package_id: The dataset ID or name.
        
        Returns:
            Dataset model with all details.
        """
        result = await self._request(
            self.config.package_show_url,
            params={"id": package_id}
        )
        
        return Dataset.from_ckan_response(result)
    
    @_ckan_retry
    async def _datastore_search(self, params: dict) -> httpx.Response:
        """One rate-limited datastore_search call. Transport errors, 5xx, 408
        and 429 raise (and are retried); any other reply is returned."""
        await self._rate_limit()
        response = await self._client.get(self.config.datastore_search_url, params=params)
        if response.status_code >= 500 or response.status_code in (408, 429):
            raise httpx.HTTPStatusError(
                f"datastore_search HTTP {response.status_code}",
                request=response.request, response=response,
            )
        return response

    async def datastore_total(self, resource_id: str) -> int | None:
        """Return the total row count of a datastore-backed resource.

        Calls `/datastore_search?resource_id=<rid>&limit=0&include_total=true`
        with an estimation threshold past any table, so `result.total` is an
        exact count, and returns it. Returns `None` when CKAN answers that
        there is no count: resources that aren't in the datastore (PDF, ZIP,
        ...), i.e. a 4xx carrying CKAN's `success: false` envelope (for a 403,
        its Authorization Error), or `success: false`. Raises `CKANError` when
        it couldn't ask (transport errors, 5xx, 408, 429 after the shared
        retries, an unparseable body, or a 4xx without CKAN's error body), so
        the caller can keep the count it already has.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        try:
            response = await self._datastore_search({
                "resource_id": resource_id,
                "limit": 0,
                "include_total": "true",
                # Exact count, not a stale planner estimate.
                "total_estimation_threshold": EXACT_TOTAL_THRESHOLD,
            })
        except httpx.HTTPError as exc:
            raise CKANError(
                f"datastore_search unavailable for {resource_id}: {exc!r}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise CKANError(
                f"datastore_search HTTP {response.status_code} without JSON for {resource_id}"
            ) from exc
        if response.status_code >= 400:
            # Only CKAN's own error envelope is a definite answer. A 4xx page
            # from the WAF or a proxy says nothing about the count; a 403 counts
            # only with CKAN's Authorization Error (as in `_probe`).
            definite = isinstance(data, dict) and data.get("success") is False
            if response.status_code == 403:
                definite = definite and is_authorization_error(data)
            if not definite:
                raise CKANError(
                    f"datastore_search HTTP {response.status_code} without CKAN's "
                    f"error body for {resource_id}")
            return None
        if not data.get("success"):
            return None
        total = (data.get("result") or {}).get("total")
        try:
            return int(total) if total is not None else None
        except (TypeError, ValueError):
            return None

    async def _probe(self, url: str, params: dict) -> str:
        """Shared probe for the reconcile sweep:
        - "gone": HTTP 403 whose body is CKAN's Authorization Error envelope
          (`shared.ckan.is_authorization_error`), i.e. CKAN itself says the
          data is no longer public;
        - "blocked": any other 403 (the WAF's HTML page, an empty or foreign
          body). Never treated as removal: a WAF change refusing our
          User-Agent would otherwise flip every published page;
        - "alive": 2xx with `success: true`;
        - "unknown": anything else (404, 5xx, success:false, parse or
          transport error); the caller leaves the flag unchanged.
        The same 403 rule as `ckan_export._http_403_is_restriction`."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")
        await self._rate_limit()
        try:
            response = await self._client.get(url, params=params)
        except (httpx.HTTPError, httpx.TimeoutException):
            return "unknown"
        if response.status_code == 403:
            try:
                body = response.json()
            except ValueError:
                return "blocked"
            return "gone" if is_authorization_error(body) else "blocked"
        if response.status_code >= 400:
            return "unknown"
        try:
            data = response.json()
        except ValueError:
            return "unknown"
        return "alive" if data.get("success") else "unknown"

    async def probe_resource(self, resource_id: str) -> str:
        """Is a datastore resource still readable? Uses a limit=0 probe."""
        return await self._probe(
            self.config.datastore_search_url,
            {"resource_id": resource_id, "limit": 0},
        )

    async def probe_package(self, package_id: str) -> str:
        """Is a package still readable? Fallback when there's no primary
        datastore resource id."""
        return await self._probe(
            self.config.package_show_url, {"id": package_id}
        )

    async def get_package_count(self) -> int:
        """
        Get the total number of datasets available.
        
        Returns:
            Total count of datasets.
        """
        result = await self.search_packages(rows=0)
        return result.get("count", 0)
    
    async def iter_all_packages(
        self,
        batch_size: int = 100,
        limit: int | None = None,
        on_progress: Callable[..., Any] | None = None,
        on_error: Callable[[str, Exception], None] | None = None,
        total_count: int | None = None,
        stop_before: datetime | None = None,
    ):
        """
        Iterate through all datasets with pagination.
        
        Args:
            batch_size: Number of datasets per API call.
            limit: Maximum number of datasets to return.
            on_progress: Optional callback(current, total) for progress.
            on_error: Optional callback(package_id, exception) for a package
                that doesn't parse as a Dataset. It is skipped either way: one
                malformed CKAN record must not end the listing (and so every
                scan) at its position.
            total_count: CKAN's package count, when the caller already asked
                for it (saves one request); asked here otherwise.
            stop_before: stop paging after a page whose every dataset was
                modified before this instant (the listing is sorted
                metadata_modified desc, so later pages are older still). That
                page's datasets are still yielded. A dataset without a parsed
                metadata_modified, or one that doesn't parse, keeps paging on.
        
        Yields:
            Dataset models one at a time.
        """
        start = 0
        fetched = 0
        if total_count is None:
            total_count = await self.get_package_count()
        
        if limit:
            total_count = min(total_count, limit)
        
        while fetched < total_count:
            remaining = total_count - fetched
            rows = min(batch_size, remaining)
            
            result = await self.search_packages(rows=rows, start=start)
            # Whether every dataset on this page is older than `stop_before`.
            page_older = stop_before is not None and bool(result.get("results"))
            
            for package_data in result.get("results", []):
                fetched += 1
                try:
                    dataset = Dataset.from_ckan_response(package_data)
                except Exception as e:  # noqa: BLE001 - one bad record, not the listing
                    page_older = False
                    pid = str((package_data or {}).get("id") or "?")
                    log.warning("skipping CKAN package %s: %s", pid[:8], e)
                    if on_error:
                        on_error(pid, e)
                else:
                    if page_older and (dataset.metadata_modified is None
                                       or dataset.metadata_modified >= stop_before):
                        page_older = False
                    yield dataset
                
                if on_progress:
                    on_progress(fetched, total_count)
                
                if limit and fetched >= limit:
                    return
            
            start += batch_size

            if page_older:
                log.info("listing: a whole page is older than %s; stopping after %d",
                         stop_before.isoformat(), fetched)
                return
            
            # Safety check to prevent infinite loops
            if not result.get("results"):
                break

