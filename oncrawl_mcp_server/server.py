"""
OnCrawl MCP Server
Exposes OnCrawl API as tools for Claude to use in SEO analysis.
"""

import json
import logging
import os
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .oncrawl_client import OnCrawlClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oncrawl-mcp")

# Initialize server
server = Server("oncrawl-mcp")

# Client will be initialized on first use
_client: Optional[OnCrawlClient] = None

# Get default workspace ID from environment
DEFAULT_WORKSPACE_ID = os.environ.get("ONCRAWL_WORKSPACE_ID")

def get_client() -> OnCrawlClient:
    global _client
    if _client is None:
        _client = OnCrawlClient()
    return _client


def compact_response(data: dict) -> str:
    """Convert response to compact JSON, removing nulls and empty values."""
    def clean(obj):
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items()
                    if v is not None and v != "" and v != [] and v != {}}
        elif isinstance(obj, list):
            return [clean(item) for item in obj if item is not None]
        return obj

    cleaned = clean(data)
    return json.dumps(cleaned, separators=(',', ':'))


def get_search_rows(result: dict) -> list:
    """Extract row list from a search API response."""
    for key in ("urls", "links", "pages", "clusters"):
        if key in result:
            return result[key]
    return []


def get_search_total_hits(result: dict) -> int:
    return result.get("meta", {}).get("total_hits", len(get_search_rows(result)))


def parse_agg_page_count(agg_result: dict) -> int:
    """Sum page counts from OnCrawl aggregation rows/cols format."""
    if not agg_result.get("aggs"):
        return 0
    agg = agg_result["aggs"][0]
    if "rows" in agg:
        cols = agg.get("cols", [])
        count_idx = cols.index("page_count") if "page_count" in cols else 1
        return sum(
            row[count_idx] for row in agg.get("rows", [])
            if len(row) > count_idx and row[count_idx] is not None
        )
    if "buckets" in agg:
        return sum(bucket.get("count", 0) for bucket in agg["buckets"])
    return int(agg.get("value", 0) or 0)


def parse_agg_dimension_counts(agg_result: dict) -> dict:
    """Map dimension values to page counts from aggregation rows."""
    if not agg_result.get("aggs"):
        return {}
    agg = agg_result["aggs"][0]
    counts = {}
    if "rows" not in agg:
        return counts
    cols = agg.get("cols", [])
    count_idx = cols.index("page_count") if "page_count" in cols else 1
    for row in agg.get("rows", []):
        if len(row) > count_idx:
            counts[row[0]] = row[count_idx]
    return counts


def count_matching_results(client: OnCrawlClient, crawl_id: str, oql: Optional[dict], data_type: str = "pages") -> int:
    """Fast count via search meta.total_hits."""
    if data_type == "pages":
        result = client.search_pages(crawl_id, ["url"], oql=oql, limit=1)
    elif data_type == "links":
        result = client.search_links(crawl_id, ["origin"], oql=oql, limit=1)
    elif data_type == "clusters":
        result = client.search_clusters(crawl_id, ["url"], oql=oql, limit=1)
    else:
        result = client.search_pages(crawl_id, ["url"], oql=oql, limit=1)
    return get_search_total_hits(result)


# === Tool Definitions ===

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="oncrawl_list_projects",
            description="List all OnCrawl projects in a workspace. Returns project IDs, names, start URLs, and latest crawl info.",
            inputSchema={
                "type": "object",
                "properties": {
                    "workspace_id": {
                        "type": "string",
                        "description": "The workspace ID to list projects from. Optional if ONCRAWL_WORKSPACE_ID is set in environment."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max projects to return (default 100)",
                        "default": 100
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="oncrawl_get_project",
            description="Get detailed info about a project including all crawl IDs. Use this to find the latest crawl_id for analysis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project ID"
                    }
                },
                "required": ["project_id"]
            }
        ),
        Tool(
            name="oncrawl_get_schema",
            description="""Get available fields for querying. ALWAYS CALL THIS FIRST before searching or aggregating.
Returns field names, types, available filters, and whether they can be used for aggregation.
This tells you what data is available to explore.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID to get schema for"
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["pages", "links", "clusters", "structured_data"],
                        "description": "Type of data to get schema for (default: pages)",
                        "default": "pages"
                    }
                },
                "required": ["crawl_id"]
            }
        ),
        Tool(
            name="oncrawl_search_pages",
            description="""Search crawled pages with flexible OQL filtering. Use for exploring URL structure, finding anomalies, checking specific page attributes.

OQL Examples:
- All pages: null
- Pages in /blog/: {"field": ["urlpath", "startswith", "/blog/"]}
- 404 errors: {"field": ["status_code", "equals", 404]}
- Orphan pages: {"field": ["depth", "has_no_value", ""]}
- Combined: {"and": [{"field": ["urlpath", "contains", "/product/"]}, {"field": ["follow_inlinks", "lt", "5"]}]}

Filter types: equals, contains, startswith, endswith, gt, gte, lt, lte, between, has_value, has_no_value
Add not_ prefix to negate string filters (not_contains, not_equals, etc.)
Use {"regex": true} as 4th element for regex matching.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID to search"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return (e.g., ['url', 'status_code', 'depth', 'follow_inlinks', 'title'])"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter object (optional, null for all pages)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 100, max 1000)",
                        "default": 100
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset",
                        "default": 0
                    },
                    "sort": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "order": {"type": "string", "enum": ["asc", "desc"]}
                            }
                        },
                        "description": "Sort order (e.g., [{'field': 'follow_inlinks', 'order': 'desc'}])"
                    }
                },
                "required": ["crawl_id", "fields"]
            }
        ),
        Tool(
            name="oncrawl_search_links",
            description="""Search the internal link graph. Use for analyzing link distribution, finding broken links, understanding site architecture.

Useful fields: origin (source URL), target (destination URL), anchor, follow, status_code
Do NOT use url/target_url — those field names do not exist.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID to search"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return (e.g., ['origin', 'target', 'anchor', 'follow'])"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter object"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 100, max 1000)",
                        "default": 100
                    }
                },
                "required": ["crawl_id", "fields"]
            }
        ),
        Tool(
            name="oncrawl_search_all_pages",
            description="""Auto-paginating page search. Fetches all matching pages in batches of 1000 (API limit per request).
Use when you need more than 1000 results. For smaller queries, use oncrawl_search_pages instead.

WARNING: Large result sets can take a long time and use significant memory. Use max_results to limit if needed.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID to search"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter object"
                    },
                    "sort": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Sort order"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default: all matching results)"
                    }
                },
                "required": ["crawl_id", "fields"]
            }
        ),
        Tool(
            name="oncrawl_search_all_links",
            description="""Auto-paginating link search. Fetches all matching links in batches of 1000.
Use when you need more than 1000 results. For smaller queries, use oncrawl_search_links instead.

WARNING: Large result sets can take a long time and use significant memory. Use max_results to limit if needed.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID to search"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return (e.g., ['origin', 'target', 'anchor', 'follow'])"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter object"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default: all matching results)"
                    }
                },
                "required": ["crawl_id", "fields"]
            }
        ),
        Tool(
            name="oncrawl_aggregate",
            description="""Run aggregate queries to group and count pages by dimensions. Essential for understanding site structure at scale.

Examples:
- Count by depth: [{"fields": [{"name": "depth"}]}]
- Count by status code: [{"fields": [{"name": "status_code"}]}]
- Avg inrank by depth: [{"fields": [{"name": "depth"}], "value": "inrank:avg"}]
- Count by inlink ranges: [{"fields": [{"name": "follow_inlinks", "ranges": [{"name": "0", "to": 1}, {"name": "1-10", "from": 1, "to": 11}, {"name": "10+", "from": 11}]}]}]
- With filter: [{"oql": {"field": ["urlpath", "startswith", "/blog/"]}, "fields": [{"name": "depth"}]}]

Aggregation methods: count (default), min, max, avg, sum, value_count, cardinality""",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID"
                    },
                    "aggs": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Array of aggregation objects"
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["pages", "links", "clusters"],
                        "description": "Data type to aggregate (default: pages)",
                        "default": "pages"
                    }
                },
                "required": ["crawl_id", "aggs"]
            }
        ),
        Tool(
            name="oncrawl_export_pages",
            description="""Export pages to JSON or CSV without the 10k limit. Use for larger datasets when you need complete data.
Warning: Can be slow for large sites. Consider filtering with OQL first.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to export"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter (recommended to limit export size)"
                    },
                    "file_type": {
                        "type": "string",
                        "enum": ["json", "csv"],
                        "description": "Output format (default: json)",
                        "default": "json"
                    }
                },
                "required": ["crawl_id", "fields"]
            }
        ),
        Tool(
            name="oncrawl_export_links",
            description="""Export internal links without the 10k limit. For complete link graph analysis (inlinks, outlinks).
Use for: finding all inlinks to a page/subdomain, link equity analysis, anchor text audits.
Warning: Can be slow for large sites. Use OQL filters to limit export size.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to export (e.g., origin, target, target_host, anchor, follow, status_code)"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter (e.g., filter by target_host for inlinks)"
                    },
                    "file_type": {
                        "type": "string",
                        "enum": ["json", "csv"],
                        "description": "Output format (default: csv)",
                        "default": "csv"
                    }
                },
                "required": ["crawl_id", "fields"]
            }
        ),
        Tool(
            name="oncrawl_search_clusters",
            description="Search duplicate content clusters. Use to find near-duplicate pages that might cause cannibalization.",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results",
                        "default": 100
                    }
                },
                "required": ["crawl_id", "fields"]
            }
        ),
        Tool(
            name="oncrawl_search_structured_data",
            description="Search structured data (JSON-LD, microdata, RDFa). URL field is structured_data_origin_url (not url). Use to audit schema markup implementation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results",
                        "default": 100
                    }
                },
                "required": ["crawl_id", "fields"]
            }
        ),
        Tool(
            name="oncrawl_get_coc_schema",
            description="""Get available fields for crawl-over-crawl comparison.
Call this before querying COC data to understand what change metrics are available.
COC IDs are found in the project details (crawl_over_crawl_ids array).""",
            inputSchema={
                "type": "object",
                "properties": {
                    "coc_id": {
                        "type": "string",
                        "description": "The crawl-over-crawl comparison ID"
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["pages"],
                        "description": "Data type (default: pages)",
                        "default": "pages"
                    }
                },
                "required": ["coc_id"]
            }
        ),
        Tool(
            name="oncrawl_search_coc",
            description="""Search crawl-over-crawl data to find what changed between crawls.
Essential for detecting:
- New pages appearing (where did they come from?)
- Pages that disappeared (were they removed or broken?)
- Status code changes (200→404, 200→301, etc.)
- Depth changes (pages moving deeper/shallower in structure)
- Inlink changes (pages gaining/losing internal links)

Use OQL to filter for specific change patterns.
COC field naming: crawl1_* (older crawl), crawl2_* (newer crawl), delta_*, eq_* — NOT previous_/current_.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "coc_id": {
                        "type": "string",
                        "description": "The crawl-over-crawl comparison ID"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return - use crawl1_*, crawl2_*, delta_*, eq_* prefixes"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter for specific changes"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 100)",
                        "default": 100
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset",
                        "default": 0
                    },
                    "sort": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "order": {"type": "string", "enum": ["asc", "desc"]}
                            }
                        },
                        "description": "Sort order"
                    }
                },
                "required": ["coc_id", "fields"]
            }
        ),
        Tool(
            name="oncrawl_aggregate_coc",
            description="""Aggregate crawl-over-crawl data to see change patterns at scale.
Examples:
- Count pages by change type (new, removed, changed, unchanged)
- Group status code changes
- See which URL patterns had the most changes""",
            inputSchema={
                "type": "object",
                "properties": {
                    "coc_id": {
                        "type": "string",
                        "description": "The crawl-over-crawl comparison ID"
                    },
                    "aggs": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Array of aggregation objects"
                    }
                },
                "required": ["coc_id", "aggs"]
            }
        ),
        Tool(
            name="oncrawl_get_log_monitoring_metadata",
            description="""Get log monitoring metadata for a project: bot kinds, available date ranges per granularity, search engines, week definition.
Call this first to check what log data is available before querying.
Requires log_monitoring_ready and log_monitoring_data_ready on the project (check via oncrawl_get_project).""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project ID"
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["events", "pages"],
                        "description": "Log data type: events (raw hits) or pages (aggregated by URL)"
                    }
                },
                "required": ["project_id", "data_type"]
            }
        ),
        Tool(
            name="oncrawl_get_log_monitoring_schema",
            description="""Get available fields for log monitoring. ALWAYS CALL THIS FIRST before searching or aggregating log data.
Returns field names, types, filters, and aggregation capabilities.
For pages data_type, granularity is required (days|weeks|months).

IMPORTANT — field naming differs by data_type:
- pages: unprefixed names (url, crawl_hits_google, seo_visits_google)
- events: all fields prefixed event_ (event_url, event_bot_kind, event_status_code)
Using a pages field name on events (or vice versa) returns 400 Unknown field.

For pages, day/week/month are filterable in OQL but cannot be included in fields (API returns 400).""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project ID"
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["events", "pages"],
                        "description": "Log data type"
                    },
                    "granularity": {
                        "type": "string",
                        "enum": ["days", "weeks", "months"],
                        "description": "Required for pages: aggregation period (days=YYYY-MM-DD, weeks=YYYY-Www, months=YYYY-MM)"
                    }
                },
                "required": ["project_id", "data_type"]
            }
        ),
        Tool(
            name="oncrawl_search_log_events",
            description="""Search raw log events (one row per server log hit). Use for Googlebot visits, bot analysis, detailed log inspection.

All event fields are prefixed event_ (NOT the same names as pages). Examples:
- Googlebot hits: {"field": ["event_bot_kind", "equals", "seo"]}
- Specific URL: {"field": ["event_url", "contains", "/blog/"]}
- Date range: {"field": ["event_date", "between", "2024-01-01", "2024-01-31"]}

Max 1000 results per request (log API limit, lower than crawl endpoints).
Use oncrawl_get_log_monitoring_schema with data_type=events first.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project ID"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return (e.g., ['event_url', 'event_bot_kind', 'event_date', 'event_status_code'])"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter object"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 100, max 1000)",
                        "default": 100
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset",
                        "default": 0
                    },
                    "sort": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Sort order"
                    }
                },
                "required": ["project_id", "fields"]
            }
        ),
        Tool(
            name="oncrawl_search_log_pages",
            description="""Search log pages aggregated by time period. Use for crawl frequency per URL, SEO visits over time, bot activity trends.

granularity is required: days, weeks, or months.
Field names are unprefixed (url, crawl_hits_google) — different from events (event_url, event_bot_kind).

OQL Examples:
- High crawl frequency: {"field": ["crawl_hits_google", "gt", 100]}
- Filter by day (day is filterable but NOT returnable in fields): {"field": ["day", "equals", "2026-07-01"]}

Max 1000 results per request. Use oncrawl_get_log_monitoring_schema with data_type=pages first.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project ID"
                    },
                    "granularity": {
                        "type": "string",
                        "enum": ["days", "weeks", "months"],
                        "description": "Time aggregation period"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return (e.g., ['url', 'crawl_hits_google', 'seo_visits_google']) — do NOT include day/week/month"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter object"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 100, max 1000)",
                        "default": 100
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset",
                        "default": 0
                    },
                    "sort": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Sort order"
                    }
                },
                "required": ["project_id", "granularity", "fields"]
            }
        ),
        Tool(
            name="oncrawl_search_all_log_pages",
            description="""Auto-paginating log page search. Fetches all matching rows in batches of 1000 (log API page size).
Use when you need more than 1000 log page rows. For smaller queries, use oncrawl_search_log_pages instead.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project ID"
                    },
                    "granularity": {
                        "type": "string",
                        "enum": ["days", "weeks", "months"],
                        "description": "Time aggregation period"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to return"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter object"
                    },
                    "sort": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Sort order"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default: all matching results)"
                    }
                },
                "required": ["project_id", "granularity", "fields"]
            }
        ),
        Tool(
            name="oncrawl_aggregate_log_monitoring",
            description="""Aggregate log monitoring data to group and count at scale.

Use field names from the matching data_type schema (pages: url, crawl_hits_google; events: event_bot_kind, event_url).

Examples (pages):
- Top crawled URLs: [{"fields": [{"name": "url"}], "value": "crawl_hits_google:sum"}]
- With filter: [{"oql": {"field": ["crawl_hits_google", "gt", 0]}, "fields": [{"name": "url"}]}]

For pages data_type, granularity is required.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project ID"
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["events", "pages"],
                        "description": "Log data type"
                    },
                    "granularity": {
                        "type": "string",
                        "enum": ["days", "weeks", "months"],
                        "description": "Required for pages data_type"
                    },
                    "aggs": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Array of aggregation objects"
                    }
                },
                "required": ["project_id", "data_type", "aggs"]
            }
        ),
        Tool(
            name="oncrawl_export_log_pages",
            description="""Export log pages without the 1000-result search limit. Use for complete crawl frequency datasets.
granularity is required (days|weeks|months). Filter with OQL to limit export size.
file_type=json returns JSONL (one JSON object per line); file_type=csv returns semicolon-separated CSV.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project ID"
                    },
                    "granularity": {
                        "type": "string",
                        "enum": ["days", "weeks", "months"],
                        "description": "Time aggregation period"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Fields to export"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter (recommended to limit export size)"
                    },
                    "file_type": {
                        "type": "string",
                        "enum": ["json", "csv"],
                        "description": "Output format (default: json)",
                        "default": "json"
                    }
                },
                "required": ["project_id", "granularity", "fields"]
            }
        ),
        Tool(
            name="oncrawl_site_health",
            description="""Quick site health summary. Returns key metrics at a glance:
- Total pages crawled
- Status code breakdown (2xx, 3xx, 4xx, 5xx)
- Orphan page count (no inlinks)
- Average crawl depth
- Indexability stats

Use this first to get an overview before diving into specific issues.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID to analyze"
                    }
                },
                "required": ["crawl_id"]
            }
        ),
        Tool(
            name="oncrawl_inspect_url",
            description="""Get everything about a specific URL. Returns:
- Status code, depth, crawl date
- Title, meta description, h1
- Canonical URL, robots directives
- Inlinks and outlinks count
- GSC data if available (clicks, impressions)
- Core Web Vitals if available

Use this to investigate specific pages.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID"
                    },
                    "url": {
                        "type": "string",
                        "description": "The exact URL to inspect"
                    }
                },
                "required": ["crawl_id", "url"]
            }
        ),
        Tool(
            name="oncrawl_find_url",
            description="""Search for URLs by pattern. Returns matching URLs with basic info.
Use when you don't know the exact URL but know part of it.

Examples:
- Find all product pages: pattern="/product/"
- Find specific slug: pattern="my-article-slug"
- Find by extension: pattern=".pdf" """,
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID"
                    },
                    "pattern": {
                        "type": "string",
                        "description": "URL pattern to search for (will match anywhere in URL)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20
                    }
                },
                "required": ["crawl_id", "pattern"]
            }
        ),
        Tool(
            name="oncrawl_compare_crawls",
            description="""Quick diff between two crawls. Returns summary of changes:
- Pages added/removed
- Status code changes
- New 404s
- Depth changes

Requires a crawl-over-crawl (COC) ID from the project.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "coc_id": {
                        "type": "string",
                        "description": "The crawl-over-crawl comparison ID"
                    }
                },
                "required": ["coc_id"]
            }
        ),
        Tool(
            name="oncrawl_top_issues",
            description="""Pre-built query for common SEO problems. Returns counts and samples of:
- 404 errors with inlinks (broken internal links)
- Orphan pages (no internal links pointing to them)
- Redirect chains (3+ hops)
- Duplicate titles
- Missing meta descriptions
- Soft 404s

Use this for a quick audit of common issues.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID to analyze"
                    }
                },
                "required": ["crawl_id"]
            }
        ),
        Tool(
            name="oncrawl_count",
            description="""Quick count without fetching data. Much faster than search when you just need numbers.

Examples:
- Total pages: oql=null
- 404 pages: oql={"field": ["status_code", "equals", 404]}
- Orphan pages: oql={"field": ["follow_inlinks", "equals", 0]}
- Deep pages: oql={"field": ["depth", "gte", 5]}""",
            inputSchema={
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl ID"
                    },
                    "oql": {
                        "type": "object",
                        "description": "OQL filter (optional, null for total count)"
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["pages", "links", "clusters"],
                        "description": "Data type to count (default: pages)",
                        "default": "pages"
                    }
                },
                "required": ["crawl_id"]
            }
        )
    ]


# === Tool Handlers ===

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        client = get_client()
        result = None
        
        if name == "oncrawl_list_projects":
            workspace_id = arguments.get("workspace_id") or DEFAULT_WORKSPACE_ID
            if not workspace_id:
                raise ValueError("workspace_id required - provide as parameter or set ONCRAWL_WORKSPACE_ID env var")
            result = client.list_projects(
                workspace_id=workspace_id,
                limit=arguments.get("limit", 100)
            )
            # Simplify project list response
            if "projects" in result:
                result["projects"] = [
                    {
                        "id": p["id"],
                        "name": p["name"],
                        "domain": p.get("domain"),
                        "start_url": p.get("start_url"),
                        "last_crawl_id": p.get("last_crawl_id"),
                        "crawl_ids": p.get("crawl_ids", [])[-5:],  # Last 5 crawls only
                        "coc_ids": p.get("crawl_over_crawl_ids", [])
                    }
                    for p in result["projects"]
                ]
                result.pop("meta", None)  # Remove metadata
        
        elif name == "oncrawl_get_project":
            raw = client.get_project(arguments["project_id"])
            p = raw.get("project", raw)
            result = {
                "id": p["id"],
                "name": p["name"],
                "domain": p.get("domain"),
                "start_url": p.get("start_url"),
                "last_crawl_id": p.get("last_crawl_id"),
                "crawl_ids": p.get("crawl_ids", [])[-10:],  # Last 10 crawls
                "coc_ids": p.get("crawl_over_crawl_ids", []),
                "log_monitoring_ready": p.get("log_monitoring_ready", False),
                "log_monitoring_data_ready": p.get("log_monitoring_data_ready", False),
                "log_monitoring_processing_enabled": p.get("log_monitoring_processing_enabled", False),
            }
        
        elif name == "oncrawl_get_schema":
            result = client.get_fields(
                crawl_id=arguments["crawl_id"],
                data_type=arguments.get("data_type", "pages")
            )
            # Simplify output for readability
            if "fields" in result:
                result["fields"] = [
                    {
                        "name": f["name"],
                        "type": f["type"],
                        "filters": f.get("actions", []),
                        "can_aggregate": f.get("agg_dimension", False),
                        "agg_methods": f.get("agg_metric_methods", [])
                    }
                    for f in result["fields"]
                ]
        
        elif name == "oncrawl_search_pages":
            result = client.search_pages(
                crawl_id=arguments["crawl_id"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                limit=arguments.get("limit", 100),
                offset=arguments.get("offset", 0),
                sort=arguments.get("sort")
            )
        
        elif name == "oncrawl_search_links":
            result = client.search_links(
                crawl_id=arguments["crawl_id"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                limit=arguments.get("limit", 100)
            )

        elif name == "oncrawl_search_all_pages":
            result = client.search_all_pages(
                crawl_id=arguments["crawl_id"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                sort=arguments.get("sort"),
                max_results=arguments.get("max_results")
            )

        elif name == "oncrawl_search_all_links":
            result = client.search_all_links(
                crawl_id=arguments["crawl_id"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                max_results=arguments.get("max_results")
            )

        elif name == "oncrawl_aggregate":
            result = client.aggregate(
                crawl_id=arguments["crawl_id"],
                aggs=arguments["aggs"],
                data_type=arguments.get("data_type", "pages")
            )
        
        elif name == "oncrawl_export_pages":
            raw = client.export_pages(
                crawl_id=arguments["crawl_id"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                file_type=arguments.get("file_type", "json")
            )
            # Return as-is for JSON/CSV
            return [TextContent(type="text", text=raw)]

        elif name == "oncrawl_export_links":
            raw = client.export_links(
                crawl_id=arguments["crawl_id"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                file_type=arguments.get("file_type", "csv")
            )
            # Return as-is for JSON/CSV
            return [TextContent(type="text", text=raw)]

        elif name == "oncrawl_search_clusters":
            result = client.search_clusters(
                crawl_id=arguments["crawl_id"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                limit=arguments.get("limit", 100)
            )
        
        elif name == "oncrawl_search_structured_data":
            result = client.search_structured_data(
                crawl_id=arguments["crawl_id"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                limit=arguments.get("limit", 100)
            )

        elif name == "oncrawl_get_coc_schema":
            result = client.get_crawl_over_crawl_fields(
                coc_id=arguments["coc_id"],
                data_type=arguments.get("data_type", "pages")
            )
            if "fields" in result:
                result["fields"] = [
                    {
                        "name": f["name"],
                        "type": f["type"],
                        "filters": f.get("actions", []),
                        "can_aggregate": f.get("agg_dimension", False),
                        "agg_methods": f.get("agg_metric_methods", [])
                    }
                    for f in result["fields"]
                ]

        elif name == "oncrawl_search_coc":
            result = client.search_crawl_over_crawl(
                coc_id=arguments["coc_id"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                limit=arguments.get("limit", 100),
                offset=arguments.get("offset", 0),
                sort=arguments.get("sort")
            )

        elif name == "oncrawl_aggregate_coc":
            result = client.aggregate_crawl_over_crawl(
                coc_id=arguments["coc_id"],
                aggs=arguments["aggs"]
            )

        elif name == "oncrawl_get_log_monitoring_metadata":
            result = client.get_log_monitoring_metadata(
                project_id=arguments["project_id"],
                data_type=arguments["data_type"]
            )

        elif name == "oncrawl_get_log_monitoring_schema":
            result = client.get_log_monitoring_fields(
                project_id=arguments["project_id"],
                data_type=arguments["data_type"],
                granularity=arguments.get("granularity")
            )
            if "fields" in result:
                result["fields"] = [
                    {
                        "name": f["name"],
                        "type": f["type"],
                        "filters": f.get("actions", []),
                        "can_aggregate": f.get("agg_dimension", False),
                        "agg_methods": f.get("agg_metric_methods", [])
                    }
                    for f in result["fields"]
                ]

        elif name == "oncrawl_search_log_events":
            result = client.search_log_events(
                project_id=arguments["project_id"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                limit=arguments.get("limit", 100),
                offset=arguments.get("offset", 0),
                sort=arguments.get("sort")
            )

        elif name == "oncrawl_search_log_pages":
            result = client.search_log_pages(
                project_id=arguments["project_id"],
                granularity=arguments["granularity"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                limit=arguments.get("limit", 100),
                offset=arguments.get("offset", 0),
                sort=arguments.get("sort")
            )

        elif name == "oncrawl_search_all_log_pages":
            result = client.search_all_log_pages(
                project_id=arguments["project_id"],
                granularity=arguments["granularity"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                sort=arguments.get("sort"),
                max_results=arguments.get("max_results")
            )

        elif name == "oncrawl_aggregate_log_monitoring":
            result = client.aggregate_log_monitoring(
                project_id=arguments["project_id"],
                data_type=arguments["data_type"],
                aggs=arguments["aggs"],
                granularity=arguments.get("granularity")
            )

        elif name == "oncrawl_export_log_pages":
            raw = client.export_log_pages(
                project_id=arguments["project_id"],
                granularity=arguments["granularity"],
                fields=arguments["fields"],
                oql=arguments.get("oql"),
                file_type=arguments.get("file_type", "json")
            )
            return [TextContent(type="text", text=raw)]

        elif name == "oncrawl_site_health":
            crawl_id = arguments["crawl_id"]
            status_agg = client.aggregate(crawl_id, [{"fields": [{"name": "status_code"}]}])
            depth_agg = client.aggregate(crawl_id, [{"fields": [{"name": "depth"}]}])
            orphan_agg = client.aggregate(
                crawl_id,
                [{"oql": {"field": ["follow_inlinks", "equals", 0]}, "fields": [{"name": "status_code"}]}]
            )
            indexable_agg = client.aggregate(crawl_id, [{"fields": [{"name": "indexable"}]}])

            status_counts = parse_agg_dimension_counts(status_agg)
            status_breakdown = {}
            for code, count in status_counts.items():
                if code is not None:
                    category = f"{str(code)[0]}xx"
                    status_breakdown[category] = status_breakdown.get(category, 0) + count

            total_pages = count_matching_results(client, crawl_id, None)

            orphan_count = parse_agg_page_count(orphan_agg)

            depth_counts = parse_agg_dimension_counts(depth_agg)
            avg_depth = None
            if depth_counts:
                depth_total = sum(depth_counts.values())
                if depth_total:
                    avg_depth = sum(depth * count for depth, count in depth_counts.items()) / depth_total

            indexable_counts = parse_agg_dimension_counts(indexable_agg)
            indexable_count = indexable_counts.get("true", 0)
            non_indexable_count = indexable_counts.get("false", 0)

            result = {
                "total_pages": total_pages,
                "status_breakdown": status_breakdown,
                "orphan_pages": orphan_count,
                "avg_depth": round(avg_depth, 2) if avg_depth is not None else None,
                "indexable": indexable_count,
                "non_indexable": non_indexable_count
            }

        elif name == "oncrawl_inspect_url":
            crawl_id = arguments["crawl_id"]
            url = arguments["url"]
            desired_fields = [
                "url", "status_code", "depth", "fetch_date",
                "title", "meta_description", "h1",
                "rel_canonical", "canonicals", "meta_robots",
                "follow_inlinks", "follow_outlinks", "nofollow_inlinks", "nofollow_outlinks",
                "word_count", "load_time",
                "indexable", "indexable_reason",
                "gsc_clicks", "gsc_impressions", "gsc_ctr", "gsc_position",
            ]
            schema = client.get_fields(crawl_id, "pages")
            available = {f["name"] for f in schema.get("fields", [])}
            fields = [f for f in desired_fields if f in available]
            search_result = client.search_pages(
                crawl_id=crawl_id,
                fields=fields,
                oql={"field": ["url", "equals", url]},
                limit=1
            )
            pages = get_search_rows(search_result)
            if pages:
                result = {"page": pages[0]}
            else:
                result = {"error": f"URL not found: {url}"}

        elif name == "oncrawl_find_url":
            crawl_id = arguments["crawl_id"]
            pattern = arguments["pattern"]
            limit = arguments.get("limit", 20)
            search_result = client.search_pages(
                crawl_id=crawl_id,
                fields=["url", "status_code", "depth", "title"],
                oql={"field": ["url", "contains", pattern]},
                limit=limit
            )
            pages = get_search_rows(search_result)
            result = {
                "pattern": pattern,
                "count": get_search_total_hits(search_result),
                "pages": pages
            }

        elif name == "oncrawl_compare_crawls":
            coc_id = arguments["coc_id"]
            status_change_agg = client.aggregate_crawl_over_crawl(
                coc_id=coc_id,
                aggs=[{"fields": [{"name": "eq_status_code"}]}]
            )
            new_404_result = client.search_crawl_over_crawl(
                coc_id=coc_id,
                fields=["url", "crawl1_status_code", "crawl2_status_code"],
                oql={"and": [
                    {"field": ["crawl2_status_code", "equals", 404]},
                    {"field": ["crawl1_status_code", "not_equals", 404]}
                ]},
                limit=10
            )

            status_changes = parse_agg_dimension_counts(status_change_agg)
            result = {
                "status_unchanged": status_changes.get("true", status_changes.get(True, 0)),
                "status_changed": status_changes.get("false", status_changes.get(False, 0)),
                "new_404s": get_search_rows(new_404_result)[:10]
            }

        elif name == "oncrawl_top_issues":
            crawl_id = arguments["crawl_id"]
            issues = {}

            broken_links = client.search_pages(
                crawl_id=crawl_id,
                fields=["url", "follow_inlinks"],
                oql={"and": [
                    {"field": ["status_code", "equals", 404]},
                    {"field": ["follow_inlinks", "gt", 0]}
                ]},
                limit=5,
                sort=[{"field": "follow_inlinks", "order": "desc"}]
            )
            issues["404_with_inlinks"] = {
                "count": count_matching_results(
                    client, crawl_id,
                    {"and": [
                        {"field": ["status_code", "equals", 404]},
                        {"field": ["follow_inlinks", "gt", 0]}
                    ]}
                ),
                "samples": get_search_rows(broken_links)
            }

            orphans = client.search_pages(
                crawl_id=crawl_id,
                fields=["url", "title"],
                oql={"and": [
                    {"field": ["follow_inlinks", "equals", 0]},
                    {"field": ["indexable", "equals", "true"]}
                ]},
                limit=5
            )
            issues["orphan_pages"] = {
                "count": count_matching_results(
                    client, crawl_id,
                    {"and": [
                        {"field": ["follow_inlinks", "equals", 0]},
                        {"field": ["indexable", "equals", "true"]}
                    ]}
                ),
                "samples": get_search_rows(orphans)
            }

            missing_meta = client.aggregate(
                crawl_id=crawl_id,
                aggs=[{"oql": {"and": [
                    {"field": ["meta_description", "has_no_value", ""]},
                    {"field": ["indexable", "equals", "true"]}
                ]}, "fields": [{"name": "status_code"}]}]
            )
            issues["missing_meta_description"] = {"count": parse_agg_page_count(missing_meta)}

            dup_titles = client.aggregate(
                crawl_id=crawl_id,
                aggs=[{"oql": {"field": ["indexable", "equals", "true"]}, "fields": [{"name": "title"}]}]
            )
            dup_count = 0
            if dup_titles.get("aggs"):
                agg = dup_titles["aggs"][0]
                for row in agg.get("rows", []):
                    if len(row) > 1 and row[1] > 1:
                        dup_count += row[1]
            issues["duplicate_titles"] = {"count": dup_count}

            soft_404s = client.aggregate(
                crawl_id=crawl_id,
                aggs=[{"oql": {"field": ["status_code", "equals", 202]}, "fields": [{"name": "status_code"}]}]
            )
            issues["soft_404s"] = {"count": parse_agg_page_count(soft_404s)}

            result = issues

        elif name == "oncrawl_count":
            crawl_id = arguments["crawl_id"]
            oql = arguments.get("oql")
            data_type = arguments.get("data_type", "pages")
            result = {"count": count_matching_results(client, crawl_id, oql, data_type)}

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(type="text", text=compact_response(result))]

    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# === Main Entry Point ===

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
