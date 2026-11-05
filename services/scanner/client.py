"""
CKAN API client for data.gov.il.

Provides async methods to interact with the Israeli government
open data portal API.
"""

import asyncio
from collections.abc import Callable
from typing import Any, Self

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import ScannerSettings, settings
from .models import Dataset


class CKANError(Exception):
    """Exception raised for CKAN API errors."""


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
        """Apply rate limiting between requests."""
        current_time = asyncio.get_event_loop().time()
        elapsed = current_time - self._last_request_time
        delay = self.config.ckan_request_delay
        
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        
        self._last_request_time = asyncio.get_event_loop().time()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
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
    
    async def list_package_ids(self) -> list[str]:
        """
        List all dataset (package) IDs.
        
        Returns:
            List of dataset ID strings.
        """
        result = await self._request(self.config.package_list_url)
        return result if isinstance(result, list) else []
    
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
    
    async def get_packages_batch(
        self, 
        package_ids: list[str],
        on_progress: Callable[..., Any] | None = None,
    ) -> list[Dataset]:
        """
        Get details for multiple datasets.
        
        Args:
            package_ids: List of dataset IDs to fetch.
            on_progress: Optional callback(current, total) for progress.
        
        Returns:
            List of Dataset models.
        """
        datasets = []
        total = len(package_ids)
        
        for i, package_id in enumerate(package_ids):
            try:
                dataset = await self.get_package(package_id)
                datasets.append(dataset)
            except Exception as e:  # noqa: BLE001
                # Log error but continue with other datasets
                print(f"Error fetching {package_id}: {e}")
            
            if on_progress:
                on_progress(i + 1, total)
        
        return datasets
    
    async def datastore_total(self, resource_id: str) -> int | None:
        """Return the total row count of a datastore-backed resource.

        Calls `/datastore_search?resource_id=<rid>&limit=0&include_total=true`
        with an estimation threshold past any table, so `result.total` is an
        exact count, and returns it. Returns `None` for resources that aren't
        in the datastore (PDF, ZIP, …), 4xx responses, or transport errors —
        the caller treats `None` as "unknown" and moves on.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        await self._rate_limit()
        try:
            response = await self._client.get(
                self.config.datastore_search_url,
                params={
                    "resource_id": resource_id,
                    "limit": 0,
                    "include_total": "true",
                    # Exact count, not Postgres's planner estimate, which
                    # CKAN returns for large tables and which goes stale
                    # when a re-upload shrinks one (see agent_contract's
                    # _EXACT_TOTAL_THRESHOLD).
                    "total_estimation_threshold": 1_000_000_000,
                },
            )
        except (httpx.HTTPError, httpx.TimeoutException):
            return None

        if response.status_code >= 400:
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        if not data.get("success"):
            return None
        total = (data.get("result") or {}).get("total")
        try:
            return int(total) if total is not None else None
        except (TypeError, ValueError):
            return None

    async def _probe(self, url: str, params: dict) -> str:
        """Shared tri-state probe. 403 → "gone", 2xx+success → "alive",
        anything else (404, 5xx, success:false, parse/transport error) →
        "unknown" (caller leaves the flag unchanged)."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")
        await self._rate_limit()
        try:
            response = await self._client.get(url, params=params)
        except (httpx.HTTPError, httpx.TimeoutException):
            return "unknown"
        if response.status_code == 403:
            return "gone"
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
    ):
        """
        Iterate through all datasets with pagination.
        
        Args:
            batch_size: Number of datasets per API call.
            limit: Maximum number of datasets to return.
            on_progress: Optional callback(current, total) for progress.
        
        Yields:
            Dataset models one at a time.
        """
        start = 0
        fetched = 0
        total_count = await self.get_package_count()
        
        if limit:
            total_count = min(total_count, limit)
        
        while fetched < total_count:
            remaining = total_count - fetched
            rows = min(batch_size, remaining)
            
            result = await self.search_packages(rows=rows, start=start)
            
            for package_data in result.get("results", []):
                dataset = Dataset.from_ckan_response(package_data)
                yield dataset
                fetched += 1
                
                if on_progress:
                    on_progress(fetched, total_count)
                
                if limit and fetched >= limit:
                    return
            
            start += batch_size
            
            # Safety check to prevent infinite loops
            if not result.get("results"):
                break

