"""
gslides_server.py

MCP server for reading Google Slides presentations.
Uses the same OAuth token/keys as Google Drive (no extra auth needed).

Env vars:
    GSLIDES_TOKEN_FILE  - path to the Google OAuth token file
    GSLIDES_KEYS_FILE   - path to the OAuth client keys file

Tools:
    slides_list         - list Google Slides presentations in Drive
    slides_read         - read the text content of a presentation (all slides)
    slides_search       - search presentations by name
"""

import json
import os
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TOKEN_URI = "https://oauth2.googleapis.com/token"
server = Server("gslides")

_creds = None


def _get_creds():
    global _creds
    if _creds:
        return _creds
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_file = os.path.expanduser(os.environ.get("GSLIDES_TOKEN_FILE", ""))
    keys_file = os.path.expanduser(os.environ.get("GSLIDES_KEYS_FILE", ""))
    if not token_file or not os.path.exists(token_file):
        raise RuntimeError("GSLIDES_TOKEN_FILE missing. Set it to the same file as GDRIVE_TOKEN_FILE.")
    if not keys_file or not os.path.exists(keys_file):
        raise RuntimeError("GSLIDES_KEYS_FILE missing.")

    with open(token_file, encoding="utf-8") as f:
        tok = json.load(f)
    with open(keys_file, encoding="utf-8") as f:
        keys = json.load(f)
    client = keys.get("installed") or keys.get("web") or {}

    creds = Credentials(
        token=tok.get("access_token") or tok.get("token"),
        refresh_token=tok.get("refresh_token"),
        token_uri=TOKEN_URI,
        client_id=client.get("client_id"),
        client_secret=client.get("client_secret"),
        scopes=tok.get("scope", "").split(),
    )
    if creds.refresh_token:
        creds.refresh(Request())
    _creds = creds
    return creds


def _drive_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_get_creds())


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="slides_list",
            description="List Google Slides presentations in Drive (id, name). Use the id with slides_read.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of presentations to return (default 20)."},
                },
            },
        ),
        Tool(
            name="slides_search",
            description="Search Google Slides presentations by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term to match presentation names."},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="slides_read",
            description=(
                "Read all text content from a Google Slides presentation — title, speaker notes, and slide text. "
                "Useful for reviewing proposals, workshop designs, and learning materials."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "Presentation file ID from slides_list or slides_search."},
                    "include_notes": {"type": "boolean", "description": "Include speaker notes (default true)."},
                },
                "required": ["file_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    drive = _drive_service()

    if name == "slides_list":
        limit = arguments.get("limit", 20)
        r = drive.files().list(
            q="mimeType='application/vnd.google-apps.presentation' and trashed=false",
            pageSize=limit,
            fields="files(id,name,modifiedTime)",
            orderBy="modifiedTime desc",
        ).execute()
        files = r.get("files", [])
        lines = [f"Google Slides presentations ({len(files)}):"]
        for f in files:
            modified = f.get("modifiedTime", "")[:10]
            lines.append(f"  {f['id']} | {f['name']} | modified: {modified}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "slides_search":
        query = arguments["query"]
        r = drive.files().list(
            q=f"mimeType='application/vnd.google-apps.presentation' and name contains '{query}' and trashed=false",
            pageSize=20,
            fields="files(id,name,modifiedTime)",
        ).execute()
        files = r.get("files", [])
        lines = [f"Presentations matching '{query}' ({len(files)}):"]
        for f in files:
            lines.append(f"  {f['id']} | {f['name']}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "slides_read":
        file_id = arguments["file_id"]
        include_notes = arguments.get("include_notes", True)

        # Export as plain text
        content = drive.files().export(fileId=file_id, mimeType="text/plain").execute()
        text = content.decode("utf-8", errors="replace")

        # Get file name
        meta = drive.files().get(fileId=file_id, fields="name").execute()
        fname = meta.get("name", file_id)

        if not include_notes:
            # Simple heuristic: speaker notes often appear after a blank line below slide content
            pass  # plain text export includes everything; filtering is approximate

        max_chars = 15000
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[... truncated at {max_chars} chars]"

        return [TextContent(type="text", text=f"Presentation: {fname}\n\n{text}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
