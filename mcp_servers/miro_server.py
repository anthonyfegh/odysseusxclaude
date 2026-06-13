"""
miro_server.py

MCP server for reading Miro boards.

Env vars:
    MIRO_ACCESS_TOKEN  - Miro OAuth access token or app token

Tools:
    miro_list_boards   - list boards in the workspace
    miro_read_board    - read sticky notes, cards and text items from a board
    miro_search_boards - search boards by name
"""

import os
import sys
from pathlib import Path

import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = "https://api.miro.com/v2"
server = Server("miro")


def _headers():
    token = os.environ.get("MIRO_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("MIRO_ACCESS_TOKEN not set. Create an app token at miro.com/app/settings/user-profile/apps.")
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="miro_list_boards",
            description="List Miro boards the token can access (id, name, last modified). Use board_id with miro_read_board.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of boards to return (default 20)."},
                },
            },
        ),
        Tool(
            name="miro_search_boards",
            description="Search Miro boards by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term to match board names."},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="miro_read_board",
            description=(
                "Read the text content of a Miro board: sticky notes, cards, text items and shapes. "
                "Returns all readable text so an agent can summarise the board or extract actions and ideas."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "board_id": {"type": "string", "description": "Board ID from miro_list_boards."},
                    "item_types": {
                        "type": "string",
                        "description": "Comma-separated item types to read. Options: sticky_note, card, text, shape. Default: sticky_note,card,text.",
                    },
                },
                "required": ["board_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    h = _headers()

    if name == "miro_list_boards":
        limit = arguments.get("limit", 20)
        r = requests.get(f"{BASE_URL}/boards", headers=h, params={"limit": limit, "sort": "last_modified"}, timeout=15)
        r.raise_for_status()
        boards = r.json().get("data", [])
        lines = [f"Miro boards ({len(boards)}):"]
        for b in boards:
            modified = b.get("modifiedAt", "")[:10]
            lines.append(f"  {b['id']} | {b.get('name', 'Untitled')} | last modified: {modified}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "miro_search_boards":
        query = arguments["query"]
        r = requests.get(f"{BASE_URL}/boards", headers=h, params={"query": query, "limit": 20}, timeout=15)
        r.raise_for_status()
        boards = r.json().get("data", [])
        lines = [f"Boards matching '{query}' ({len(boards)}):"]
        for b in boards:
            lines.append(f"  {b['id']} | {b.get('name', 'Untitled')}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "miro_read_board":
        board_id = arguments["board_id"]
        types_str = arguments.get("item_types", "sticky_note,card,text")
        types = [t.strip() for t in types_str.split(",")]

        all_items = []
        for itype in types:
            params = {"type": itype, "limit": 50}
            r = requests.get(f"{BASE_URL}/boards/{board_id}/items", headers=h, params=params, timeout=20)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            items = r.json().get("data", [])
            for item in items:
                text = ""
                data = item.get("data", {})
                if "content" in data:
                    # Strip basic HTML tags
                    import re
                    text = re.sub(r"<[^>]+>", " ", data["content"]).strip()
                elif "title" in data:
                    text = data.get("title", "") + (" — " + data.get("description", "") if data.get("description") else "")
                if text:
                    all_items.append((itype, text))

        if not all_items:
            return [TextContent(type="text", text=f"No readable text items found on board {board_id}.")]

        lines = [f"Board {board_id} — {len(all_items)} text items:"]
        for itype, text in all_items:
            lines.append(f"\n  [{itype}] {text[:300]}")
        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
