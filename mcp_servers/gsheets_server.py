"""
gsheets_server.py

MCP server exposing read-only Google Sheets access (list tabs + read values).

Shares the same Google OAuth token as the Drive connector (the token must
include the spreadsheets.readonly scope). Reads paths from env vars set on
the MCP server registration:
    GSHEETS_TOKEN_FILE - the Google token file (same one Drive uses)
    GSHEETS_KEYS_FILE  - the OAuth client keys file

Tools:
    sheets_list_tabs - list the tab names in a spreadsheet
    sheets_read      - read the cell values from a tab or A1 range
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TOKEN_URI = "https://oauth2.googleapis.com/token"
MAX_ROWS = 200
MAX_CHARS = 20_000

server = Server("gsheets")

_service = None
_initialized = False


def _load_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_file = os.path.expanduser(os.environ.get("GSHEETS_TOKEN_FILE", ""))
    keys_file = os.path.expanduser(os.environ.get("GSHEETS_KEYS_FILE", ""))
    if not token_file or not os.path.exists(token_file):
        raise RuntimeError("GSHEETS_TOKEN_FILE missing or not found. Authorize the connector first.")
    if not keys_file or not os.path.exists(keys_file):
        raise RuntimeError("GSHEETS_KEYS_FILE missing or not found.")

    with open(token_file, encoding="utf-8") as f:
        tok = json.load(f)
    with open(keys_file, encoding="utf-8") as f:
        keys = json.load(f)
    client = keys.get("installed") or keys.get("web") or {}

    scope = tok.get("scope", "")
    scopes = scope.split() if isinstance(scope, str) else scope

    creds = Credentials(
        token=tok.get("access_token") or tok.get("token"),
        refresh_token=tok.get("refresh_token"),
        token_uri=TOKEN_URI,
        client_id=client.get("client_id"),
        client_secret=client.get("client_secret"),
        scopes=scopes,
    )
    if creds.refresh_token:
        creds.refresh(Request())
        tok["access_token"] = creds.token
        with open(token_file, "w", encoding="utf-8") as f:
            json.dump(tok, f, indent=2)
    elif not creds.valid:
        raise RuntimeError("Token invalid and no refresh_token. Re-authorize the connector.")
    return creds


def _ensure_init():
    global _service, _initialized
    if _initialized:
        return
    _initialized = True
    from googleapiclient.discovery import build
    _service = build("sheets", "v4", credentials=_load_credentials(), cache_discovery=False)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="sheets_list_tabs",
            description="List the tab (sheet) names in a Google Spreadsheet. Use the spreadsheet id from a Drive search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheet_id": {"type": "string", "description": "The spreadsheet id (the long id from a Drive file, not the name)."},
                },
                "required": ["spreadsheet_id"],
            },
        ),
        Tool(
            name="sheets_read",
            description="Read cell values from a Google Spreadsheet. Give a tab name, or an A1 range like 'Sheet1!A1:F50'. Omit range to read the first tab.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheet_id": {"type": "string", "description": "The spreadsheet id."},
                    "range": {"type": "string", "description": "A tab name (e.g. 'Tracker') or an A1 range (e.g. 'Tracker!A1:F100'). Optional."},
                },
                "required": ["spreadsheet_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        _ensure_init()
    except Exception as e:
        return [TextContent(type="text", text=f"Sheets not connected: {e}")]

    sid = (arguments.get("spreadsheet_id") or "").strip()
    if not sid:
        return [TextContent(type="text", text="Error: spreadsheet_id is required")]

    if name == "sheets_list_tabs":
        try:
            meta = _service.spreadsheets().get(spreadsheetId=sid, fields="properties.title,sheets.properties").execute()
        except Exception as e:
            return [TextContent(type="text", text=f"Sheets read failed: {e}")]
        title = meta.get("properties", {}).get("title", "")
        tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
        return [TextContent(type="text", text=f"Spreadsheet: {title}\nTabs: " + ", ".join(tabs))]

    if name == "sheets_read":
        rng = (arguments.get("range") or "").strip()
        try:
            if not rng:
                meta = _service.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties.title").execute()
                first = meta.get("sheets", [{}])[0].get("properties", {}).get("title", "Sheet1")
                rng = first
            resp = _service.spreadsheets().values().get(spreadsheetId=sid, range=rng).execute()
        except Exception as e:
            return [TextContent(type="text", text=f"Sheets read failed: {e}")]
        values = resp.get("values", [])
        if not values:
            return [TextContent(type="text", text=f"No data found in range '{rng}'.")]
        lines = []
        for row in values[:MAX_ROWS]:
            lines.append(" | ".join(str(c) for c in row))
        out = f"Range {resp.get('range', rng)} ({len(values)} rows):\n" + "\n".join(lines)
        if len(values) > MAX_ROWS:
            out += f"\n... ({len(values) - MAX_ROWS} more rows)"
        if len(out) > MAX_CHARS:
            out = out[:MAX_CHARS] + "\n... (truncated)"
        return [TextContent(type="text", text=out)]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
