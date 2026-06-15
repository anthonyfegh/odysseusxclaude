"""
monday_server.py

MCP server for Monday.com — read boards/items and create/update them.

Auth is a Monday personal API token passed via env:
    MONDAY_API_TOKEN

Get one in Monday: click your avatar -> Developers -> My Access Tokens.

Tools:
    monday_list_boards        - list your boards (id + name)
    monday_board_items        - read rows of a board with column values
    monday_create_item        - create a new item (row) on a board
    monday_update_item_status - change the status of an item
    monday_add_update         - post a comment/update on an item
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


def _do_list_boards() -> str:
    data = _query("query { boards (limit: 100, state: active) { id name } }")
    boards = data.get("boards", [])
    if not boards:
        return "No boards found."
    lines = [f"{len(boards)} boards:"]
    for b in boards:
        lines.append(f"- {b.get('name')}  (id: {b.get('id')})")
    return "\n".join(lines)


def _do_board_items(bid: str, limit: int) -> str:
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
        return f"Board {bid} not found."
    b = boards[0]
    col_title = {c["id"]: c["title"] for c in b.get("columns", [])}
    items = b.get("items_page", {}).get("items", [])
    if not items:
        return f"Board '{b.get('name')}' has no rows."
    lines = [f"Board: {b.get('name')} ({len(items)} rows)\n"]
    for it in items:
        parts = [f"# {it.get('name')}  (id: {it.get('id')})"]
        for cv in it.get("column_values", []):
            txt = (cv.get("text") or "").strip()
            if txt:
                parts.append(f"{col_title.get(cv.get('id'), cv.get('id'))}: {txt}")
        lines.append("  " + " | ".join(parts))
    return "\n".join(lines)


def _do_create_item(board_id: str, item_name: str, group_id: str) -> str:
    if group_id:
        q = """mutation ($board: ID!, $group: String!, $name: String!) {
          create_item (board_id: $board, group_id: $group, item_name: $name) { id name }
        }"""
        data = _query(q, {"board": board_id, "group": group_id, "name": item_name})
    else:
        q = """mutation ($board: ID!, $name: String!) {
          create_item (board_id: $board, item_name: $name) { id name }
        }"""
        data = _query(q, {"board": board_id, "name": item_name})
    item = data.get("create_item", {})
    return f"Item created: '{item.get('name')}' (id: {item.get('id')})"


def _do_update_status(item_id: str, board_id: str, column_id: str, status_label: str) -> str:
    value = json.dumps({"label": status_label})
    q = """mutation ($item: ID!, $board: ID!, $col: String!, $val: JSON!) {
      change_column_value (item_id: $item, board_id: $board, column_id: $col, value: $val) { id }
    }"""
    _query(q, {"item": item_id, "board": board_id, "col": column_id, "val": value})
    return f"Item {item_id} column '{column_id}' updated to '{status_label}'"


def _do_add_update(item_id: str, body: str) -> str:
    q = """mutation ($item: ID!, $body: String!) {
      create_update (item_id: $item, body: $body) { id }
    }"""
    data = _query(q, {"item": item_id, "body": body})
    uid = data.get("create_update", {}).get("id", "")
    return f"Update posted on item {item_id} (update id: {uid})"


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
            description="Read the rows (items) of a Monday board, including each row's id, column values (status, dates, people, etc.). Item ids are shown — use them with monday_update_item_status and monday_add_update.",
            inputSchema={
                "type": "object",
                "properties": {
                    "board_id": {"type": "string", "description": "The board id from monday_list_boards."},
                    "limit": {"type": "integer", "description": "Max rows to return (default 50)."},
                },
                "required": ["board_id"],
            },
        ),
        Tool(
            name="monday_create_item",
            description="Create a new item (row) on a Monday board. Optionally specify a group (section). Returns the new item id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "board_id": {"type": "string", "description": "The board id from monday_list_boards."},
                    "item_name": {"type": "string", "description": "Name for the new item/row."},
                    "group_id": {"type": "string", "description": "Optional group/section id to add the item to (leave blank for default group)."},
                },
                "required": ["board_id", "item_name"],
            },
        ),
        Tool(
            name="monday_update_item_status",
            description="Change a column value on a Monday item — typically used to update status (e.g. 'Done', 'In Progress', 'Stuck'). Use monday_board_items to find the item id and column id first.",
            inputSchema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "The item id from monday_board_items."},
                    "board_id": {"type": "string", "description": "The board id the item belongs to."},
                    "column_id": {"type": "string", "description": "The column id to update (e.g. 'status', 'status_1'). Use monday_board_items to see column ids."},
                    "status_label": {"type": "string", "description": "The new status label, e.g. 'Done', 'In Progress', 'Stuck', 'Working on it'."},
                },
                "required": ["item_id", "board_id", "column_id", "status_label"],
            },
        ),
        Tool(
            name="monday_add_update",
            description="Post a comment or update on a Monday item — visible in the item's Updates section. Great for logging agent actions or adding notes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "The item id from monday_board_items."},
                    "body": {"type": "string", "description": "The update text to post."},
                },
                "required": ["item_id", "body"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "monday_list_boards":
            result = await asyncio.to_thread(_do_list_boards)
            return [TextContent(type="text", text=result)]

        if name == "monday_board_items":
            bid = str(arguments.get("board_id") or "").strip()
            if not bid:
                return [TextContent(type="text", text="Error: board_id is required")]
            limit = max(1, min(int(arguments.get("limit") or 50), MAX_ITEMS))
            result = await asyncio.to_thread(_do_board_items, bid, limit)
            return [TextContent(type="text", text=result)]

        if name == "monday_create_item":
            board_id = str(arguments.get("board_id") or "").strip()
            item_name = (arguments.get("item_name") or "").strip()
            group_id = (arguments.get("group_id") or "").strip()
            if not board_id or not item_name:
                return [TextContent(type="text", text="Error: board_id and item_name are required")]
            result = await asyncio.to_thread(_do_create_item, board_id, item_name, group_id)
            return [TextContent(type="text", text=result)]

        if name == "monday_update_item_status":
            item_id = str(arguments.get("item_id") or "").strip()
            board_id = str(arguments.get("board_id") or "").strip()
            column_id = (arguments.get("column_id") or "").strip()
            status_label = (arguments.get("status_label") or "").strip()
            if not all([item_id, board_id, column_id, status_label]):
                return [TextContent(type="text", text="Error: item_id, board_id, column_id, and status_label are all required")]
            result = await asyncio.to_thread(_do_update_status, item_id, board_id, column_id, status_label)
            return [TextContent(type="text", text=result)]

        if name == "monday_add_update":
            item_id = str(arguments.get("item_id") or "").strip()
            body = (arguments.get("body") or "").strip()
            if not item_id or not body:
                return [TextContent(type="text", text="Error: item_id and body are required")]
            result = await asyncio.to_thread(_do_add_update, item_id, body)
            return [TextContent(type="text", text=result)]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Monday error: {e}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
