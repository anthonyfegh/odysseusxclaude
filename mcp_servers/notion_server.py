"""
notion_server.py

MCP server for reading Notion pages and databases.

Env vars:
    NOTION_API_KEY  - Notion internal integration token (starts with secret_)

Tools:
    notion_search          - search across all shared pages and databases
    notion_read_page       - read the full text content of a page
    notion_list_databases  - list all accessible databases
    notion_query_database  - query a database with optional filter
"""

import asyncio
import os
import sys
from pathlib import Path

import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
server = Server("notion")


def _headers():
    token = os.environ.get("NOTION_API_KEY", "")
    if not token:
        raise RuntimeError(
            "NOTION_API_KEY not set. Create an integration at notion.so/my-integrations "
            "and share your pages with it."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _get(path, **kwargs):
    return requests.get(f"{BASE_URL}{path}", headers=_headers(), **kwargs)


def _post(path, **kwargs):
    return requests.post(f"{BASE_URL}{path}", headers=_headers(), **kwargs)


def _extract_rich_text(rich_text_list):
    """Extract plain text from a Notion rich text array."""
    return "".join(rt.get("plain_text", "") for rt in (rich_text_list or []))


def _extract_block_text(block):
    """Extract readable text from a single Notion block."""
    btype = block.get("type", "")
    data = block.get(btype, {})

    if btype in ("paragraph", "heading_1", "heading_2", "heading_3",
                 "bulleted_list_item", "numbered_list_item", "toggle",
                 "quote", "callout"):
        text = _extract_rich_text(data.get("rich_text", []))
        prefix = {
            "heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
            "bulleted_list_item": "- ", "numbered_list_item": "1. ",
            "quote": "> ", "callout": ">> ",
        }.get(btype, "")
        return f"{prefix}{text}" if text else None

    if btype == "to_do":
        text = _extract_rich_text(data.get("rich_text", []))
        checked = "[x]" if data.get("checked") else "[ ]"
        return f"{checked} {text}" if text else None

    if btype == "code":
        text = _extract_rich_text(data.get("rich_text", []))
        lang = data.get("language", "")
        return f"```{lang}\n{text}\n```" if text else None

    if btype == "divider":
        return "---"

    if btype == "image":
        url = data.get("external", {}).get("url") or data.get("file", {}).get("url", "")
        caption = _extract_rich_text(data.get("caption", []))
        return f"[Image{': ' + caption if caption else ''}]({url})" if url else "[Image]"

    if btype == "bookmark":
        url = data.get("url", "")
        caption = _extract_rich_text(data.get("caption", []))
        return f"[{caption or url}]({url})" if url else None

    return None


def _fetch_block_children(block_id, depth=0, max_depth=3):
    """Recursively fetch block children and return as text lines."""
    if depth > max_depth:
        return []

    r = requests.get(
        f"{BASE_URL}/blocks/{block_id}/children",
        headers=_headers(),
        params={"page_size": 100},
        timeout=20,
    )
    if r.status_code != 200:
        return []

    lines = []
    indent = "  " * depth
    for block in r.json().get("results", []):
        text = _extract_block_text(block)
        if text:
            lines.append(f"{indent}{text}")
        if block.get("has_children") and depth < max_depth:
            lines.extend(_fetch_block_children(block["id"], depth + 1, max_depth))

    return lines


def _page_title(page):
    """Extract title from a page or database object."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return _extract_rich_text(prop.get("title", []))
    # Fallback for database objects
    title_list = page.get("title", [])
    if title_list:
        return _extract_rich_text(title_list)
    return "Untitled"


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="notion_search",
            description=(
                "Search across all Notion pages and databases shared with this integration. "
                "Returns titles, types, and IDs. Use the ID with notion_read_page to get full content."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term. Leave empty to list all accessible pages.",
                    },
                    "filter_type": {
                        "type": "string",
                        "description": "Filter by type: 'page' or 'database'. Leave empty for both.",
                    },
                },
            },
        ),
        Tool(
            name="notion_read_page",
            description=(
                "Read the full text content of a Notion page by its ID. "
                "Returns all text blocks in reading order. Use notion_search to find page IDs first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "Notion page ID from notion_search results.",
                    },
                },
                "required": ["page_id"],
            },
        ),
        Tool(
            name="notion_list_databases",
            description="List all Notion databases shared with this integration (name, ID, properties).",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="notion_query_database",
            description=(
                "Query a Notion database and return its entries as readable text. "
                "Returns up to 50 rows with all property values."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "database_id": {
                        "type": "string",
                        "description": "Database ID from notion_list_databases.",
                    },
                    "filter_property": {
                        "type": "string",
                        "description": "Optional property name to filter by (e.g. 'Status').",
                    },
                    "filter_value": {
                        "type": "string",
                        "description": "Optional value to filter for (e.g. 'In progress').",
                    },
                },
                "required": ["database_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:

    if name == "notion_search":
        query = arguments.get("query", "")
        filter_type = arguments.get("filter_type", "")

        payload = {"page_size": 30}
        if query:
            payload["query"] = query
        if filter_type in ("page", "database"):
            payload["filter"] = {"value": filter_type, "property": "object"}

        r = await asyncio.to_thread(
            lambda: _post("/search", json=payload, timeout=20)
        )
        r.raise_for_status()
        results = r.json().get("results", [])

        if not results:
            msg = f"No results found for '{query}'." if query else "No pages or databases shared with this integration."
            return [TextContent(type="text", text=msg)]

        lines = [f"Notion search results ({len(results)}):"]
        for obj in results:
            otype = obj.get("object", "")
            oid = obj.get("id", "")
            title = _page_title(obj)
            edited = obj.get("last_edited_time", "")[:10]
            lines.append(f"  [{otype}] {title} | id: {oid} | edited: {edited}")

        return [TextContent(type="text", text="\n".join(lines))]

    if name == "notion_read_page":
        page_id = arguments["page_id"]

        # Get page metadata first
        r = await asyncio.to_thread(
            lambda: _get(f"/pages/{page_id}", timeout=15)
        )
        if r.status_code == 404:
            return [TextContent(type="text", text=f"Page {page_id} not found. Make sure it is shared with the integration.")]
        r.raise_for_status()
        page = r.json()
        title = _page_title(page)
        edited = page.get("last_edited_time", "")[:10]

        # Fetch all block content
        lines = await asyncio.to_thread(_fetch_block_children, page_id)

        header = f"# {title}\nLast edited: {edited}\n\n"
        content = "\n".join(lines) if lines else "(This page has no text content.)"
        return [TextContent(type="text", text=header + content)]

    if name == "notion_list_databases":
        r = await asyncio.to_thread(
            lambda: _post("/search", json={"filter": {"value": "database", "property": "object"}, "page_size": 30}, timeout=20)
        )
        r.raise_for_status()
        dbs = r.json().get("results", [])

        if not dbs:
            return [TextContent(type="text", text="No databases found. Share databases with the integration at notion.so/my-integrations.")]

        lines = [f"Notion databases ({len(dbs)}):"]
        for db in dbs:
            dbid = db.get("id", "")
            title = _page_title(db)
            props = list(db.get("properties", {}).keys())
            lines.append(f"\n  {title}")
            lines.append(f"    id: {dbid}")
            lines.append(f"    properties: {', '.join(props[:8])}")

        return [TextContent(type="text", text="\n".join(lines))]

    if name == "notion_query_database":
        database_id = arguments["database_id"]
        filter_property = arguments.get("filter_property", "")
        filter_value = arguments.get("filter_value", "")

        payload = {"page_size": 50}
        # Basic select/status filter
        if filter_property and filter_value:
            payload["filter"] = {
                "or": [
                    {"property": filter_property, "select": {"equals": filter_value}},
                    {"property": filter_property, "status": {"equals": filter_value}},
                ]
            }

        r = await asyncio.to_thread(
            lambda: _post(f"/databases/{database_id}/query", json=payload, timeout=20)
        )
        if r.status_code == 404:
            return [TextContent(type="text", text=f"Database {database_id} not found. Share it with the integration first.")]
        r.raise_for_status()
        rows = r.json().get("results", [])

        if not rows:
            return [TextContent(type="text", text="No entries found in this database.")]

        lines = [f"Database query results ({len(rows)} rows):"]
        for row in rows:
            title = _page_title(row)
            row_id = row.get("id", "")
            lines.append(f"\n  {title} (id: {row_id})")
            for prop_name, prop_data in row.get("properties", {}).items():
                if prop_data.get("type") == "title":
                    continue
                value = _format_property(prop_data)
                if value:
                    lines.append(f"    {prop_name}: {value}")

        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


def _format_property(prop):
    """Format a Notion property value as a readable string."""
    ptype = prop.get("type", "")
    data = prop.get(ptype, None)

    if data is None:
        return None
    if ptype == "rich_text":
        return _extract_rich_text(data) or None
    if ptype == "number":
        return str(data) if data is not None else None
    if ptype == "select":
        return data.get("name") if data else None
    if ptype == "multi_select":
        return ", ".join(o.get("name", "") for o in (data or []))
    if ptype == "status":
        return data.get("name") if data else None
    if ptype == "date":
        if not data:
            return None
        start = data.get("start", "")
        end = data.get("end", "")
        return f"{start} - {end}" if end else start
    if ptype == "checkbox":
        return "Yes" if data else "No"
    if ptype == "url":
        return data
    if ptype == "email":
        return data
    if ptype == "phone_number":
        return data
    if ptype in ("created_time", "last_edited_time"):
        return str(data)[:10] if data else None
    if ptype == "people":
        return ", ".join(p.get("name", "") for p in (data or []))
    if ptype == "formula":
        ftype = data.get("type", "")
        return str(data.get(ftype, ""))
    return None


async def run():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
