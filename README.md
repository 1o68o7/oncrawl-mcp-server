# OnCrawl MCP Server

[![PyPI version](https://badge.fury.io/py/oncrawl-mcp-server.svg)](https://badge.fury.io/py/oncrawl-mcp-server)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

MCP server that exposes OnCrawl's API for use with Claude Code and Claude Desktop. Enables Claude to perform deep technical SEO analysis by querying crawl data, Google Search Console metrics, and crawl-over-crawl comparisons.

## Features

- **28 MCP Tools** for comprehensive SEO and log analysis
- **Raw data access**: Query pages, links, clusters, structured data with flexible OQL
- **Schema discovery**: Claude learns available fields before querying
- **Aggregations**: Group/count by any dimension for pattern detection
- **Full exports**: No 10k limit for complete datasets
- **Crawl-over-crawl analysis**: Track changes between crawls (new pages, status changes, etc.)
- **Google Search Console integration**: 600+ GSC fields including clicks, impressions, CTR, position by device, brand/non-brand, and more
- **Log Monitoring**: Googlebot visits, SEO organic traffic, crawl frequency per page

## What Makes This Powerful

OnCrawl combines crawl data with GSC/GA4 traffic data, enabling analyses like:

- **Orphan pages with traffic**: Pages getting clicks from Google but not linked internally
- **Underlinked high-performers**: Popular pages with weak internal linking
- **Low CTR opportunities**: Pages with high impressions but poor click-through rates
- **404s still in Google**: Broken pages still appearing in search results
- **Deep pages with traffic**: Buried content that Google values
- **Mobile vs desktop performance**: Traffic breakdowns by device

## Prerequisites

- Python 3.11+
- OnCrawl account with API access
- OnCrawl API token (from your OnCrawl settings)

## Installation

### Option 1: Install from PyPI (Recommended)

```bash
pip install oncrawl-mcp-server
```

Then configure in Claude Desktop/Code (see [Configuration](#configuration)).

### Option 2: Install from Source

```bash
# Clone the repository
git clone https://github.com/Amaculus/oncrawl-mcp-server.git
cd oncrawl-mcp-server

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Mac/Linux
.venv\Scripts\activate     # Windows

# Install dependencies
pip install -e .
```

## Getting Your API Token

1. Log into OnCrawl
2. Go to **Settings → API**
3. Create a new token with `projects:read` scope
4. Copy the token

## Getting Your Workspace ID

Your workspace ID is required to list projects. To find it:

1. Log into OnCrawl
2. Look at the URL in your browser - it will be in this format:
   ```
   https://app.oncrawl.com/workspace/5c015889451c956baf7ab7a9/projects
                                   ^^^^^^^^^^^^^^^^^^^^^^^^^
                                   This is your workspace ID
   ```
3. Copy the 24-character ID from the URL

You can optionally add it to your config for convenience, or pass it directly when calling tools.

## Configuration

### For Claude Desktop

**Windows:** Edit `%APPDATA%\Claude\claude_desktop_config.json`
**Mac:** Edit `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "oncrawl": {
      "command": "python",
      "args": ["-m", "oncrawl_mcp_server.server"],
      "env": {
        "ONCRAWL_API_TOKEN": "your-api-token-here",
        "ONCRAWL_WORKSPACE_ID": "your-workspace-id-here"
      }
    }
  }
}
```

**Note**: `ONCRAWL_WORKSPACE_ID` is optional but recommended for convenience. If not set, you'll need to provide it when calling `oncrawl_list_projects`.

### For Claude Code (CLI)

```bash
# Add to your MCP config
claude mcp add oncrawl

# Or manually edit your config with:
{
  "mcpServers": {
    "oncrawl": {
      "command": "python",
      "args": ["-m", "oncrawl_mcp_server.server"],
      "env": {
        "ONCRAWL_API_TOKEN": "your-api-token-here",
        "ONCRAWL_WORKSPACE_ID": "your-workspace-id-here"
      }
    }
  }
}
```

**Note**: `ONCRAWL_WORKSPACE_ID` is optional but recommended for convenience.

**Important**: Restart Claude Desktop/Code after changing the config.

## Available Tools

| Tool | Purpose |
|------|---------|
| `oncrawl_list_projects` | List all projects in a workspace |
| `oncrawl_get_project` | Get project details including crawl IDs and COC IDs |
| `oncrawl_get_schema` | **Call first** - discover available fields for a crawl |
| `oncrawl_search_pages` | Query pages with OQL filtering, sorting, pagination (max 10k) |
| `oncrawl_search_links` | Query internal link graph (max 10k) |
| `oncrawl_search_all_pages` | **Auto-paginating** page search - bypasses 10k limit |
| `oncrawl_search_all_links` | **Auto-paginating** link search - bypasses 10k limit |
| `oncrawl_aggregate` | Group and count by any dimension with range support |
| `oncrawl_export_pages` | Full export without 10k limit |
| `oncrawl_search_clusters` | Find duplicate content clusters |
| `oncrawl_search_structured_data` | Audit schema markup |
| `oncrawl_get_coc_schema` | Discover fields for crawl-over-crawl comparison |
| `oncrawl_search_coc` | Find what changed between two crawls |
| `oncrawl_aggregate_coc` | Aggregate change patterns at scale |
| `oncrawl_get_log_monitoring_metadata` | Get log monitoring metadata (bot kinds, date ranges) |
| `oncrawl_get_log_monitoring_schema` | **Call first** - discover log monitoring fields |
| `oncrawl_search_log_events` | Search raw log hits (Googlebot, bots) |
| `oncrawl_search_log_pages` | Search log pages by time period (days/weeks/months) |
| `oncrawl_search_all_log_pages` | **Auto-paginating** log page search - bypasses 10k limit |
| `oncrawl_aggregate_log_monitoring` | Aggregate log data by bot, URL, time period |
| `oncrawl_export_log_pages` | Full log page export without 10k limit |

### Handling Large Result Sets

The OnCrawl API limits search results to 10,000 per request. For larger datasets:

- **`oncrawl_search_all_pages`** / **`oncrawl_search_all_links`**: Automatically paginate through all results
- Use `max_results` parameter to cap the total (e.g., `max_results: 50000`)
- For very large exports (100k+), consider using filters to reduce the dataset

## Usage Examples

### Getting Started

```
"List my OnCrawl projects"
# If ONCRAWL_WORKSPACE_ID is not set in config, specify it:
"List my OnCrawl projects in workspace 5c015889451c956baf7ab7a9"

"Get the schema for crawl xyz789 - what fields are available?"

"Show me the first 10 pages from this crawl"
```

### Technical SEO Analysis

```
"Find all pages at depth > 5 with fewer than 3 inlinks"

"Show me 404 pages that still have internal links pointing to them"

"What's the status code distribution for this crawl?"

"Find pages with missing meta descriptions"
```

### GSC Integration

```
"Find orphan pages (0 internal links) that are getting clicks from Google"

"Show me pages with high impressions but low CTR (<2%)"

"Which pages buried deep in the site are getting significant traffic?"

"Compare mobile vs desktop traffic for the top landing pages"
```

### Crawl-Over-Crawl Analysis

```
"Show me pages that changed status code between the last two crawls"

"Find pages that were added in the latest crawl"

"Which pages increased in depth between crawls?"

"Show me the status code distribution changes over time"
```

### Detective Work

```
"I want you to act as a senior SEO analyst. Investigate crawl xyz789 for issues:
- Site structure problems
- Orphan page clusters
- Broken internal links
- Pages that should be linked better
- Anything else that looks problematic"
```

```
"Analyze this site for low-hanging SEO opportunities using both crawl and GSC data"
```

## OQL Query Language

OnCrawl uses OQL (OnCrawl Query Language) for filtering. Here are the key operators:

### Basic Operators

```json
// Equals
{"field": ["status_code", "equals", 200]}

// Greater than / Less than
{"field": ["depth", "gt", "3"]}
{"field": ["follow_inlinks", "lt", "5"]}

// Contains
{"field": ["url", "contains", "/blog/"]}

// Starts with
{"field": ["urlpath", "startswith", "/products/"]}

// Has value / No value
{"field": ["canonical", "has_value", ""]}
{"field": ["canonical", "has_no_value", ""]}
```

### Combining Filters

```json
// AND
{
  "and": [
    {"field": ["status_code", "equals", 200]},
    {"field": ["depth", "gt", "3"]},
    {"field": ["follow_inlinks", "lt", "5"]}
  ]
}

// OR
{
  "or": [
    {"field": ["status_code", "equals", 301]},
    {"field": ["status_code", "equals", 404]}
  ]
}

// Nested combinations
{
  "and": [
    {"field": ["status_code", "equals", 200]},
    {
      "or": [
        {"field": ["depth", "gt", "5"]},
        {"field": ["follow_inlinks", "equals", 0]}
      ]
    }
  ]
}
```

### Regex Support

```json
{"field": ["urlpath", "startswith", "/blog/[0-9]{4}/", {"regex": true}]}
```

## Common Field Names

### Crawl Fields
- `url`, `urlpath`, `depth`, `status_code`
- `follow_inlinks`, `follow_outlinks`
- `title`, `description`, `h1`, `canonical`
- `content_length`, `load_time`
- `indexability`, `is_compliant`

### GSC Fields (600+ available)
- `gsc_clicks`, `gsc_impressions`, `gsc_ctr`, `gsc_position`
- `gsc_clicks_device_mobile`, `gsc_clicks_device_desktop`
- `gsc_clicks_brand`, `gsc_clicks_nonbrand`
- `gsc_impressions_device_mobile`, etc.

### Google Analytics Fields
- `google_analytics_users_seo`
- `google_analytics_sessions_seo`
- `google_analytics_engaged_sessions_seo`
- `google_analytics_engagement_rate_seo`

**Pro tip**: Always call `oncrawl_get_schema` first to see exactly which fields are available for your specific crawl.

## Log Monitoring

Log Monitoring exposes server log data (Googlebot crawls, SEO visits) at the **project** level (not crawl level).

### Prerequisites

Check project flags via `oncrawl_get_project`:
- `log_monitoring_ready` — log parsing configuration submitted
- `log_monitoring_data_ready` — index is searchable
- `log_monitoring_processing_enabled` — automatic log file processing active

If flags are `false`, log tools return a clear error instead of failing silently.

### Workflow

1. `oncrawl_get_project` — verify log monitoring flags
2. `oncrawl_get_log_monitoring_metadata` — check available date ranges and bot kinds
3. `oncrawl_get_log_monitoring_schema` — discover fields (granularity required for pages)
4. `oncrawl_search_log_events` or `oncrawl_search_log_pages` — query data

### Common Log Fields

- `url`, `urlpath` — page URL
- `bot_kind` — `seo`, `sea`, `vertical`
- `hits` — number of log hits (pages data type)
- `day`, `week`, `month` — time period (depends on granularity)
- `status_code` — HTTP status from log
- `search_engine` — e.g. `google`

### Examples

```
"Check if log monitoring is active for project abc123"
"Get log monitoring metadata for project abc123, data type pages"
"Show top 20 most crawled URLs by Googlebot last month"
"Export all log pages with more than 50 hits per day"
```

## GSC Integration

OnCrawl automatically integrates with Google Search Console when connected to your account. The GSC fields will appear in the schema if integration is active.

**How it works:**
- If GSC is connected: 600+ GSC fields are available in the schema
- If GSC is not connected: GSC fields won't appear in the schema
- Querying GSC fields without integration returns a 400 error
- Fields with no data return 0 or null (not an error)

**Detection:** Check the schema first with `oncrawl_get_schema` to see if GSC fields are present.

## Troubleshooting

### "ONCRAWL_API_TOKEN environment variable required"
- Make sure the token is set in the `env` block of your MCP config
- Restart Claude Desktop/Code after changing the config

### "Unknown field" errors
- Call `oncrawl_get_schema` first to see available fields
- Field names are case-sensitive
- GSC fields only appear if GSC integration is active

### API rate limits
- OnCrawl API has rate limits
- If you hit 429 errors, slow down requests
- Use exports for large datasets instead of pagination

### Tool not appearing in Claude
- Verify Python path in config is correct
- Check that oncrawl-mcp-server is installed
- Look at Claude's logs for MCP connection errors
- Restart Claude after config changes

### Permission errors
- Verify API token has `projects:read` scope
- Check workspace/project/crawl IDs are correct

## Development

### Running Tests

```bash
# Set your API token
export ONCRAWL_API_TOKEN="your-token"

# Run the server directly
python -m oncrawl_mcp_server.server

# Test with a specific project
python test_full_mcp.py
```

### Building from Source

```bash
# Install build tools
pip install build twine

# Build the package
python -m build

# Install locally
pip install -e .
```

## Version History

### 0.5.0
- Added Log Monitoring support (7 new tools)
- Project flags for log monitoring exposed in `oncrawl_get_project`

### 0.4.6
- Extended tool set (site health, GSC integration, auto-pagination, exports)
- Initial release with 9 core tools
- Basic OnCrawl API integration

## Contributing

Contributions welcome! Please feel free to submit a Pull Request.

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Links

- [GitHub Repository](https://github.com/Amaculus/oncrawl-mcp-server)
- [Report Issues](https://github.com/Amaculus/oncrawl-mcp-server/issues)
- [OnCrawl Documentation](https://developer.oncrawl.com/)
- [Model Context Protocol](https://modelcontextprotocol.io/)

## Author

Antonio - [GitHub](https://github.com/Amaculus)
