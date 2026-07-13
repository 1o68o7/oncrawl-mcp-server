"""
OnCrawl API Client
Handles authentication and API requests to OnCrawl REST API v2
"""

import os
import httpx
from typing import Any, Optional
from urllib.parse import urljoin

class OnCrawlClient:
    BASE_URL = "https://app.oncrawl.com/api/v2/"
    LOG_SEARCH_MAX_LIMIT = 1000
    
    def __init__(self, api_token: Optional[str] = None):
        self.api_token = api_token or os.environ.get("ONCRAWL_API_TOKEN")
        if not self.api_token:
            raise ValueError("ONCRAWL_API_TOKEN environment variable required")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
    
    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        url = urljoin(self.BASE_URL, endpoint)
        
        with httpx.Client(timeout=120.0) as client:
            response = client.request(
                method=method,
                url=url,
                headers=self.headers,
                **kwargs
            )
            
            if response.status_code >= 400:
                error_detail = response.text
                try:
                    error_detail = response.json()
                except:
                    pass
                raise Exception(f"OnCrawl API error {response.status_code}: {error_detail}")
            
            return response.json()
    
    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        return self._request("GET", endpoint, params=params)
    
    def _post(self, endpoint: str, json_data: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        return self._request("POST", endpoint, json=json_data, params=params)
    
    # === Project Management ===
    
    def list_projects(self, workspace_id: str, limit: int = 100, offset: int = 0) -> dict:
        """List all projects in a workspace"""
        return self._get(
            f"workspaces/{workspace_id}/projects",
            params={"limit": limit, "offset": offset}
        )
    
    def get_project(self, project_id: str) -> dict:
        """Get details for a specific project including crawl IDs"""
        return self._get(f"projects/{project_id}")
    
    # === Data Schema ===
    
    def get_fields(self, crawl_id: str, data_type: str = "pages") -> dict:
        """
        Get available fields for a data type.
        This is critical for exploration - tells Claude what's queryable.
        
        data_type: pages, links, clusters, structured_data
        """
        return self._get(f"data/crawl/{crawl_id}/{data_type}/fields")
    
    # === Search Queries ===
    
    def search_pages(
        self,
        crawl_id: str,
        fields: list[str],
        oql: Optional[dict] = None,
        limit: int = 100,
        offset: int = 0,
        sort: Optional[list[dict]] = None
    ) -> dict:
        """
        Search pages with OQL filtering.
        Max 10k results via pagination - use export for larger sets.
        
        Example OQL:
        {
            "and": [
                {"field": ["urlpath", "startswith", "/blog/"]},
                {"field": ["status_code", "equals", 200]}
            ]
        }
        """
        payload = {
            "fields": fields,
            "limit": limit,
            "offset": offset
        }
        if oql:
            payload["oql"] = oql
        if sort:
            payload["sort"] = sort
        
        return self._post(f"data/crawl/{crawl_id}/pages", json_data=payload)
    
    def search_links(
        self,
        crawl_id: str,
        fields: list[str],
        oql: Optional[dict] = None,
        limit: int = 100,
        offset: int = 0
    ) -> dict:
        """
        Search internal links.
        Useful for finding link graph anomalies.
        """
        payload = {
            "fields": fields,
            "limit": limit,
            "offset": offset
        }
        if oql:
            payload["oql"] = oql

        return self._post(f"data/crawl/{crawl_id}/links", json_data=payload)

    def search_all_links(
        self,
        crawl_id: str,
        fields: list[str],
        oql: Optional[dict] = None,
        max_results: Optional[int] = None,
        batch_size: int = 1000
    ) -> dict:
        """
        Auto-paginating link search that bypasses the 1k limit.
        Fetches all matching links by paginating through results.

        Args:
            crawl_id: The crawl ID
            fields: Fields to return
            oql: Optional filter
            max_results: Maximum results to return (None = all)
            batch_size: Results per API call (max 1000 for links endpoint)

        Returns:
            dict with 'links' array and 'meta' with total_hits
        """
        all_links = []
        offset = 0
        total_hits = None

        while True:
            result = self.search_links(
                crawl_id=crawl_id,
                fields=fields,
                oql=oql,
                limit=min(batch_size, 1000),
                offset=offset
            )

            batch_links = result.get("links", [])
            if total_hits is None:
                total_hits = result.get("meta", {}).get("total_hits", 0)

            all_links.extend(batch_links)

            # Check if we're done
            if len(batch_links) < batch_size:
                break
            if max_results and len(all_links) >= max_results:
                all_links = all_links[:max_results]
                break

            offset += batch_size

        return {
            "links": all_links,
            "meta": {
                "total_hits": total_hits,
                "returned": len(all_links)
            }
        }

    def search_all_pages(
        self,
        crawl_id: str,
        fields: list[str],
        oql: Optional[dict] = None,
        sort: Optional[list[dict]] = None,
        max_results: Optional[int] = None,
        batch_size: int = 10000
    ) -> dict:
        """
        Auto-paginating page search that bypasses the 10k limit.
        Fetches all matching pages by paginating through results.

        Args:
            crawl_id: The crawl ID
            fields: Fields to return
            oql: Optional filter
            sort: Optional sort order
            max_results: Maximum results to return (None = all)
            batch_size: Results per API call (max 10000)

        Returns:
            dict with 'urls' array and 'meta' with total_hits
        """
        all_pages = []
        offset = 0
        total_hits = None

        while True:
            result = self.search_pages(
                crawl_id=crawl_id,
                fields=fields,
                oql=oql,
                sort=sort,
                limit=min(batch_size, 10000),
                offset=offset
            )

            batch_pages = result.get("urls", [])
            if total_hits is None:
                total_hits = result.get("meta", {}).get("total_hits", 0)

            all_pages.extend(batch_pages)

            # Check if we're done
            if len(batch_pages) < batch_size:
                break
            if max_results and len(all_pages) >= max_results:
                all_pages = all_pages[:max_results]
                break

            offset += batch_size

        return {
            "urls": all_pages,
            "meta": {
                "total_hits": total_hits,
                "returned": len(all_pages)
            }
        }
    
    # === Aggregations ===
    
    def aggregate(
        self,
        crawl_id: str,
        aggs: list[dict],
        data_type: str = "pages"
    ) -> dict:
        """
        Run aggregate queries for grouping/counting.
        
        Example aggs:
        [
            {
                "fields": [{"name": "depth"}],
                "value": "count"
            }
        ]
        
        Or with ranges:
        [
            {
                "fields": [{
                    "name": "follow_inlinks",
                    "ranges": [
                        {"name": "0", "to": 1},
                        {"name": "1-10", "from": 1, "to": 11},
                        {"name": "10+", "from": 11}
                    ]
                }]
            }
        ]
        """
        return self._post(
            f"data/crawl/{crawl_id}/{data_type}/aggs",
            json_data={"aggs": aggs}
        )
    
    # === Export ===
    
    def export_pages(
        self,
        crawl_id: str,
        fields: list[str],
        oql: Optional[dict] = None,
        file_type: str = "json"
    ) -> str:
        """
        Export pages as CSV or JSONL (no 10k limit).
        Returns raw response text.
        
        Note: For large exports, this can take a while.
        """
        url = urljoin(self.BASE_URL, f"data/crawl/{crawl_id}/pages")
        
        payload = {"fields": fields}
        if oql:
            payload["oql"] = oql
        
        with httpx.Client(timeout=300.0) as client:
            response = client.post(
                url,
                headers=self.headers,
                json=payload,
                params={"export": "true", "file_type": file_type}
            )
            
            if response.status_code >= 400:
                raise Exception(f"Export error {response.status_code}: {response.text}")
            
            return response.text

    def export_links(
        self,
        crawl_id: str,
        fields: list[str],
        oql: Optional[dict] = None,
        file_type: str = "csv"
    ) -> str:
        """
        Export internal links as CSV or JSON using pagination.
        Fetches in batches of 1000 with progress logging every 50k.
        """
        import io
        import csv
        import json
        import logging

        logger = logging.getLogger("oncrawl-mcp")

        all_links = []
        offset = 0
        batch_size = 1000
        total_hits = None
        last_logged = 0

        while True:
            result = self.search_links(
                crawl_id=crawl_id,
                fields=fields,
                oql=oql,
                limit=batch_size,
                offset=offset
            )

            batch_links = result.get("links", [])
            if total_hits is None:
                total_hits = result.get("meta", {}).get("total_hits", 0)
                logger.info(f"Export links: {total_hits:,} total links to fetch")

            all_links.extend(batch_links)

            # Log progress every 50k links
            if len(all_links) - last_logged >= 50000:
                logger.info(f"Export links progress: {len(all_links):,} / {total_hits:,}")
                last_logged = len(all_links)

            if len(batch_links) < batch_size:
                break

            offset += batch_size

        logger.info(f"Export links complete: {len(all_links):,} links")

        if file_type == "json":
            return json.dumps(all_links, indent=2)

        if not all_links:
            return ""

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_links)
        return output.getvalue()

    # === Clusters (Duplicate Detection) ===
    
    def search_clusters(
        self,
        crawl_id: str,
        fields: list[str],
        oql: Optional[dict] = None,
        limit: int = 100
    ) -> dict:
        """Search duplicate content clusters"""
        payload = {
            "fields": fields,
            "limit": limit
        }
        if oql:
            payload["oql"] = oql
        
        return self._post(f"data/crawl/{crawl_id}/clusters", json_data=payload)
    
    # === Structured Data ===
    
    def search_structured_data(
        self,
        crawl_id: str,
        fields: list[str],
        oql: Optional[dict] = None,
        limit: int = 100
    ) -> dict:
        """Search structured data (JSON-LD, microdata, RDFa)"""
        payload = {
            "fields": fields,
            "limit": limit
        }
        if oql:
            payload["oql"] = oql

        return self._post(f"data/crawl/{crawl_id}/structured_data", json_data=payload)

    # === Crawl Over Crawl ===

    def get_crawl_over_crawl_fields(self, coc_id: str, data_type: str = "pages") -> dict:
        """Get available fields for crawl over crawl comparison"""
        return self._get(f"data/crawl_over_crawl/{coc_id}/{data_type}/fields")

    def search_crawl_over_crawl(
        self,
        coc_id: str,
        fields: list[str],
        oql: Optional[dict] = None,
        limit: int = 100,
        offset: int = 0,
        sort: Optional[list[dict]] = None
    ) -> dict:
        """
        Search crawl over crawl comparison data.
        Shows what changed between crawls - new pages, removed pages, status changes, etc.
        """
        payload = {
            "fields": fields,
            "limit": limit,
            "offset": offset
        }
        if oql:
            payload["oql"] = oql
        if sort:
            payload["sort"] = sort

        return self._post(f"data/crawl_over_crawl/{coc_id}/pages", json_data=payload)

    def aggregate_crawl_over_crawl(
        self,
        coc_id: str,
        aggs: list[dict],
        data_type: str = "pages"
    ) -> dict:
        """Aggregate crawl over crawl data to see change patterns"""
        return self._post(
            f"data/crawl_over_crawl/{coc_id}/{data_type}/aggs",
            json_data={"aggs": aggs}
        )

    # === Log Monitoring ===

    def _get_log_monitoring_flags(self, project_id: str) -> dict:
        raw = self.get_project(project_id)
        p = raw.get("project", raw)
        return {
            "log_monitoring_ready": p.get("log_monitoring_ready", False),
            "log_monitoring_data_ready": p.get("log_monitoring_data_ready", False),
            "log_monitoring_processing_enabled": p.get("log_monitoring_processing_enabled", False),
        }

    def ensure_log_monitoring_ready(self, project_id: str) -> None:
        """Raise a clear error if log monitoring is not available for this project."""
        flags = self._get_log_monitoring_flags(project_id)
        issues = []
        if not flags["log_monitoring_ready"]:
            issues.append("log_monitoring_ready=false (configuration non soumise)")
        if not flags["log_monitoring_data_ready"]:
            issues.append("log_monitoring_data_ready=false (index non interrogeable)")
        if issues:
            msg = "Log Monitoring non disponible pour ce projet: " + "; ".join(issues)
            if not flags["log_monitoring_processing_enabled"]:
                msg += " (log_monitoring_processing_enabled=false — traitement automatique inactif)"
            raise ValueError(msg)

    def _clamp_log_limit(self, limit: int) -> int:
        """Log monitoring search endpoints cap at 1000 results per request."""
        if limit > self.LOG_SEARCH_MAX_LIMIT:
            raise ValueError(
                f"limit must be <= {self.LOG_SEARCH_MAX_LIMIT} for log monitoring search endpoints"
            )
        return limit

    def get_log_monitoring_metadata(self, project_id: str, data_type: str) -> dict:
        """Get log monitoring metadata (bot kinds, date ranges, search engines)."""
        self.ensure_log_monitoring_ready(project_id)
        return self._get(f"data/project/{project_id}/log_monitoring/{data_type}/metadata")

    def get_log_monitoring_fields(
        self,
        project_id: str,
        data_type: str,
        granularity: Optional[str] = None
    ) -> dict:
        """Get available fields for log monitoring events or pages."""
        self.ensure_log_monitoring_ready(project_id)
        if data_type == "pages":
            if not granularity:
                raise ValueError("granularity requis pour data_type=pages (days|weeks|months)")
            endpoint = f"data/project/{project_id}/log_monitoring/pages/{granularity}/fields"
        elif data_type == "events":
            endpoint = f"data/project/{project_id}/log_monitoring/events/fields"
        else:
            raise ValueError(f"data_type invalide: {data_type} (events|pages)")
        return self._get(endpoint)

    def search_log_events(
        self,
        project_id: str,
        fields: list[str],
        oql: Optional[dict] = None,
        limit: int = 100,
        offset: int = 0,
        sort: Optional[list[dict]] = None
    ) -> dict:
        """Search raw log events (one row per log hit)."""
        self.ensure_log_monitoring_ready(project_id)
        limit = self._clamp_log_limit(limit)
        payload = {
            "fields": fields,
            "limit": limit,
            "offset": offset
        }
        if oql:
            payload["oql"] = oql
        if sort:
            payload["sort"] = sort
        return self._post(
            f"data/project/{project_id}/log_monitoring/events",
            json_data=payload
        )

    def search_log_pages(
        self,
        project_id: str,
        granularity: str,
        fields: list[str],
        oql: Optional[dict] = None,
        limit: int = 100,
        offset: int = 0,
        sort: Optional[list[dict]] = None
    ) -> dict:
        """Search log pages aggregated by granularity (days|weeks|months)."""
        self.ensure_log_monitoring_ready(project_id)
        limit = self._clamp_log_limit(limit)
        payload = {
            "fields": fields,
            "limit": limit,
            "offset": offset
        }
        if oql:
            payload["oql"] = oql
        if sort:
            payload["sort"] = sort
        return self._post(
            f"data/project/{project_id}/log_monitoring/pages/{granularity}",
            json_data=payload
        )

    def search_all_log_pages(
        self,
        project_id: str,
        granularity: str,
        fields: list[str],
        oql: Optional[dict] = None,
        sort: Optional[list[dict]] = None,
        max_results: Optional[int] = None,
        batch_size: int = 1000
    ) -> dict:
        """Auto-paginating log page search (1000 results per API call)."""
        batch_size = min(batch_size, self.LOG_SEARCH_MAX_LIMIT)
        all_pages = []
        offset = 0
        total_hits = None

        while True:
            result = self.search_log_pages(
                project_id=project_id,
                granularity=granularity,
                fields=fields,
                oql=oql,
                sort=sort,
                limit=batch_size,
                offset=offset
            )

            batch_pages = result.get("urls", [])
            if total_hits is None:
                total_hits = result.get("meta", {}).get("total_hits", 0)

            all_pages.extend(batch_pages)

            if len(batch_pages) < batch_size:
                break
            if max_results and len(all_pages) >= max_results:
                all_pages = all_pages[:max_results]
                break

            offset += batch_size

        return {
            "urls": all_pages,
            "meta": {
                "total_hits": total_hits,
                "returned": len(all_pages)
            }
        }

    def aggregate_log_monitoring(
        self,
        project_id: str,
        data_type: str,
        aggs: list[dict],
        granularity: Optional[str] = None
    ) -> dict:
        """Run aggregate queries on log monitoring data."""
        self.ensure_log_monitoring_ready(project_id)
        if data_type == "pages":
            if not granularity:
                raise ValueError("granularity requis pour data_type=pages (days|weeks|months)")
            endpoint = f"data/project/{project_id}/log_monitoring/pages/{granularity}/aggs"
        elif data_type == "events":
            endpoint = f"data/project/{project_id}/log_monitoring/events/aggs"
        else:
            raise ValueError(f"data_type invalide: {data_type} (events|pages)")
        return self._post(endpoint, json_data={"aggs": aggs})

    def export_log_pages(
        self,
        project_id: str,
        granularity: str,
        fields: list[str],
        oql: Optional[dict] = None,
        file_type: str = "json"
    ) -> str:
        """Export log pages as CSV or JSONL (no search limit)."""
        self.ensure_log_monitoring_ready(project_id)
        url = urljoin(
            self.BASE_URL,
            f"data/project/{project_id}/log_monitoring/pages/{granularity}"
        )

        payload = {"fields": fields, "file_type": file_type}
        if oql:
            payload["oql"] = oql

        with httpx.Client(timeout=300.0) as client:
            response = client.post(
                url,
                headers=self.headers,
                json=payload,
                params={"export": "true"}
            )

            if response.status_code >= 400:
                raise Exception(f"Export error {response.status_code}: {response.text}")

            return response.text
