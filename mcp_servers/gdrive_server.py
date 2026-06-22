"""
gdrive_server.py

MCP server exposing read-only Google Drive access (search + read).

Built to work with Odysseus's own MCP OAuth flow (routes/mcp_routes.py),
which writes the raw Google token endpoint response to a token file. This
server reads that token file plus the OAuth client keys file and builds a
google.oauth2 credential from them, refreshing as needed.

Paths are passed in via env vars set on the MCP server registration:
    GDRIVE_TOKEN_FILE  - the token file Odysseus writes after Authorize
    GDRIVE_KEYS_FILE   - the OAuth client keys file (installed/desktop creds)

Tools:
    drive_search  - find files by name or full-text query
    drive_read    - read a file's text (Google Docs/Sheets are exported)
"""

import asyncio
import io
import json
import os
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TOKEN_URI = "https://oauth2.googleapis.com/token"
MAX_READ_CHARS = 20_000

server = Server("gdrive")

_service = None
_initialized = False


def _load_credentials():
    """Build a Google credential from the Odysseus-written token file and the
    OAuth client keys file. Refreshes the access token if it is expired and
    writes the refreshed token back to the token file."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_file = os.path.expanduser(os.environ.get("GDRIVE_TOKEN_FILE", ""))
    keys_file = os.path.expanduser(os.environ.get("GDRIVE_KEYS_FILE", ""))
    if not token_file or not os.path.exists(token_file):
        raise RuntimeError("GDRIVE_TOKEN_FILE missing or not found. Authorize the connector in Settings first.")
    if not keys_file or not os.path.exists(keys_file):
        raise RuntimeError("GDRIVE_KEYS_FILE missing or not found.")

    with open(token_file, encoding="utf-8") as f:
        tok = json.load(f)
    with open(keys_file, encoding="utf-8") as f:
        keys = json.load(f)
    client = keys.get("installed") or keys.get("web") or {}
    client_id = client.get("client_id")
    client_secret = client.get("client_secret")

    scope = tok.get("scope", "")
    scopes = scope.split() if isinstance(scope, str) else scope

    creds = Credentials(
        token=tok.get("access_token") or tok.get("token"),
        refresh_token=tok.get("refresh_token"),
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
    )

    if creds.refresh_token:
        # Always refresh on startup so a stale stored access token can never
        # cause a 401. The server is spawned fresh per connection, so this is
        # cheap. Persist the new access token in the same raw shape.
        creds.refresh(Request())
        tok["access_token"] = creds.token
        with open(token_file, "w", encoding="utf-8") as f:
            json.dump(tok, f, indent=2)
    elif not creds.valid:
        raise RuntimeError("Token invalid and no refresh_token available. Re-authorize the connector.")
    return creds


def _ensure_init():
    global _service, _initialized
    if _initialized:
        return
    _initialized = True
    from googleapiclient.discovery import build
    creds = _load_credentials()
    _service = build("drive", "v3", credentials=creds, cache_discovery=False)


# Export MIME types for Google-native files.
_EXPORT = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="drive_search",
            description="Search Google Drive for files by name or content. Returns name, id, type, and last modified date for each match.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text. Matches file names and full text content."},
                    "max_results": {"type": "integer", "description": "Max files to return (default 10)."},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="drive_read",
            description="Read the text of a Drive file by its id. Google Docs are exported as text, Google Sheets as CSV. Use drive_search first to get the id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "The Drive file id (from drive_search)."},
                },
                "required": ["file_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        _ensure_init()
    except Exception as e:
        return [TextContent(type="text", text=f"Drive not connected: {e}")]

    if name == "drive_search":
        query = (arguments.get("query") or "").strip().replace("'", "\\'")
        if not query:
            return [TextContent(type="text", text="Error: query is required")]
        try:
            limit = int(arguments.get("max_results") or 10)
        except (TypeError, ValueError):
            limit = 10
        try:
            resp = _service.files().list(
                q=f"fullText contains '{query}' or name contains '{query}'",
                pageSize=max(1, min(limit, 50)),
                orderBy="modifiedTime desc",
                fields="files(id,name,mimeType,modifiedTime,webViewLink)",
                spaces="drive",
            ).execute()
        except Exception as e:
            return [TextContent(type="text", text=f"Drive search failed: {e}")]
        files = resp.get("files", [])
        if not files:
            return [TextContent(type="text", text=f"No Drive files found for '{arguments.get('query')}'.")]
        lines = [f"Found {len(files)} file(s):\n"]
        for fobj in files:
            mt = fobj.get("mimeType", "").replace("application/vnd.google-apps.", "google ")
            lines.append(f"- {fobj.get('name')}  [{mt}]  id: {fobj.get('id')}  modified: {fobj.get('modifiedTime','')[:10]}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "drive_read":
        file_id = (arguments.get("file_id") or "").strip()
        if not file_id:
            return [TextContent(type="text", text="Error: file_id is required")]
        try:
            from googleapiclient.http import MediaIoBaseDownload
            meta = _service.files().get(fileId=file_id, fields="name,mimeType").execute()
            mime = meta.get("mimeType", "")
            if mime in _EXPORT:
                data = _service.files().export(fileId=file_id, mimeType=_EXPORT[mime]).execute()
                text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
            elif mime.startswith("application/vnd.google-apps"):
                return [TextContent(type="text", text=f"'{meta.get('name')}' is a {mime} file that cannot be read as text.")]
            else:
                buf = io.BytesIO()
                downloader = MediaIoBaseDownload(buf, _service.files().get_media(fileId=file_id))
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                raw = buf.getvalue()
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    return [TextContent(type="text", text=f"'{meta.get('name')}' is a binary file ({mime}) and cannot be read as text.")]
        except Exception as e:
            return [TextContent(type="text", text=f"Drive read failed: {e}")]
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + f"\n... (truncated, {len(text)} chars total)"
        return [TextContent(type="text", text=f"# {meta.get('name')}\n\n{text}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
