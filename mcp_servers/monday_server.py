"""
monday_server.py

MCP server exposing read-only Monday.com access (list boards + read items).

Auth is a Monday personal API token passed via env on the MCP registration:
    MONDAY_API_TOKEN

Get one in Monday: click your avatar -> Developers -> My Access Tokens (or
Administration -> Connections -> API). The token carries your own permissions.

Tools:
    monday_list_boards - list your boards (id + name)
    monday_board_items - read the rows (items) of a board with column values
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API = "https://api.monday.com/v2"
MAX_ITEMS = 100
server = Server("monday")


def _token():
    tok = os.environ.get("MONDAY_API_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("MONDAY_API_TOKEN not set. Add your Monday API token to the connector.")
    return tok


def _query(query: str, variables: dict = None) -> dict:
    headers = {"Authorization": _token(), "Content-Type": "application/json", "API-Version": "2024-01"}
    with httpx.Client(timeout=30.0) as cx:
        r = cx.post(API, headers=headers, json={"query": query, "variables": variables or {}})
    data = r.json()
    if data.get("errors"):
        msgs = "; ".join(e.get("message", "") for e in data["errors"])
        raise RuntimeError(msgs or "Monday API error")
    return data.get("data", {})


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="monday_list_boards",
            description="List your Monday.com boards (id and name). Use a board id with monday_board_items.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="monday_board_items",
            description="Read the rows (items) of a Monday board, including each row's column values (status, dates, people, etc.). Use this to find what is overdue, blocked, or in progress.",
            inputSchema={
                "type": "object",
                "properties": {
                    "board_id": {"type": "string", "description": "The board id from monday_list_boards."},
                    "limit": {"type": "integer", "description": "Max rows to return (default 50)."},
                },
                "required": ["board_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "monday_list_boards":
            data = _query("query { boards (limit: 100, state: active) { id name } }")
            boards = data.get("boards", [])
            if not boards:
                return [TextContent(type="text", text="No boards found.")]
            lines = [f"{len(boards)} boards:"]
            for b in boards:
                lines.append(f"- {b.get('name')}  (id: {b.get('id')})")
            return [TextContent(type="text", text="\n".join(lines))]

        if name == "monday_board_items":
            bid = str(arguments.get("board_id") or "").strip()
            if not bid:
                return [TextContent(type="text", text="Error: board_id is required")]
            try:
                limit = int(arguments.get("limit") or 50)
            except (TypeError, ValueError):
                limit = 50
            limit = max(1, min(limit, MAX_ITEMS))
            q = """query ($bid: [ID!], $lim: Int!) {
              boards (ids: $bid) {
                name
                columns { id title }
                items_page (limit: $lim) {
                  items { id name column_values { id text } }
                }
              }
            }"""
            data = _query(q, {"bid": [bid], "lim": limit})
            boards = data.get("boards", [])
            if not boards:
                return [TextContent(type="text", text=f"Board {bid} not found.")]
            b = boards[0]
            col_title = {c["id"]: c["title"] for c in b.get("columns", [])}
            items = b.get("items_page", {}).get("items", [])
            if not items:
                return [TextContent(type="text", text=f"Board '{b.get('name')}' has no rows.")]
            lines = [f"Board: {b.get('name')} ({len(items)} rows)\n"]
            for it in items:
                parts = [f"# {it.get('name')}"]
                for cv in it.get("column_values", []):
                    txt = (cv.get("text") or "").strip()
                    if txt:
                        parts.append(f"{col_title.get(cv.get('id'), cv.get('id'))}: {txt}")
                lines.append("  " + " | ".join(parts))
            return [TextContent(type="text", text="\n".join(lines))]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Monday error: {e}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
