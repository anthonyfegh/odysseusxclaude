"""
odysseus_server.py

MCP server that exposes Odysseus's own APP tools (email, calendar, notes, memory,
documents, sessions, research, UI control, …) to a per-agent Claude Code session.

It is a thin PROXY: tool *definitions* are built from Odysseus's existing
FUNCTION_TOOL_SCHEMAS, but every tool *call* is forwarded over localhost to the
main Odysseus app's internal endpoint (/api/internal/agent_tool), so the tool
runs IN the live app process with full runtime state (the injected memory
manager, ui_control's event bus, in-flight sessions, the research engine, …).
Running tools inside this subprocess can't reach that state.

Context is provided by the backend as env vars on the `claude` subprocess
(inherited by this stdio grandchild):
  ODY_INTERNAL_URL    e.g. http://127.0.0.1:7860/api/internal/agent_tool
  ODY_INTERNAL_TOKEN  matches core.middleware.INTERNAL_TOOL_TOKEN
  ODY_OWNER           the logged-in user (impersonated server-side)
  ODY_AGENT_ID, ODY_WORKSPACE_ROOT, ODY_CHAT_SESSION_ID
Tools Claude already has natively (bash/python/file/web) are NOT exposed here.
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

# Resolve the tool_schemas <-> agent_tools circular import, then reuse the
# OpenAI-style function schemas as MCP tool definitions (no execution logic).
import src.agent_tools  # noqa: F401
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

server = Server("odysseus")

ODY_INTERNAL_URL = os.environ.get("ODY_INTERNAL_URL") or "http://127.0.0.1:7860/api/internal/agent_tool"
ODY_INTERNAL_TOKEN = os.environ.get("ODY_INTERNAL_TOKEN") or ""
ODY_OWNER = os.environ.get("ODY_OWNER") or ""
ODY_WORKSPACE_ROOT = os.environ.get("ODY_WORKSPACE_ROOT") or None
ODY_CHAT_SESSION_ID = os.environ.get("ODY_CHAT_SESSION_ID") or None

# App-tool subset (Claude has bash/python/read_file/write_file/web_search/
# web_fetch/edit_image natively, so those are omitted; low-level model-serving
# and admin infra are also omitted from the baseline).
_ALLOW = {
    "list_email_accounts", "list_emails", "read_email", "send_email", "reply_to_email",
    "bulk_email", "archive_email", "delete_email", "mark_email_read",
    "resolve_contact", "manage_contact",
    "manage_calendar", "manage_memory",
    "create_document", "edit_document", "update_document", "suggest_document", "manage_documents",
    "manage_session", "list_sessions", "create_session", "search_chats", "send_to_session",
    "trigger_research", "manage_research", "manage_tasks", "manage_skills", "ui_control",
    "api_call", "app_api",
}


def _build_tools():
    tools, seen = [], set()
    for s in FUNCTION_TOOL_SCHEMAS:
        if s.get("type") != "function":
            continue
        fn = s.get("function") or {}
        name = fn.get("name")
        if name in _ALLOW and name not in seen:
            seen.add(name)
            tools.append(Tool(
                name=name,
                description=(fn.get("description") or name),
                inputSchema=(fn.get("parameters") or {"type": "object", "properties": {}}),
            ))
    if "manage_notes" not in seen:
        tools.append(Tool(
            name="manage_notes",
            description=("Manage the user's notes & to-dos (Google-Keep style): create, "
                         "list, update, complete, archive, delete. Pass an 'action' plus fields."),
            inputSchema={"type": "object", "properties": {"action": {"type": "string"}},
                         "required": ["action"], "additionalProperties": True},
        ))
    return tools


_TOOLS = _build_tools()


@server.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


def _flatten(result) -> str:
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return str(result)
    for k in ("output", "results", "content", "response", "message"):
        v = result.get(k)
        if isinstance(v, str) and v.strip():
            return v
        if v is not None and not isinstance(v, str):
            try:
                return json.dumps(v, default=str)[:8000]
            except Exception:
                return str(v)[:8000]
    if result.get("error"):
        return f"Error: {result['error']}"
    try:
        return json.dumps(result, default=str)[:8000]
    except Exception:
        return str(result)[:8000]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    headers = {
        "X-Odysseus-Internal-Token": ODY_INTERNAL_TOKEN,
        "X-Odysseus-Owner": ODY_OWNER,
        "Content-Type": "application/json",
    }
    payload = {"tool": name, "args": arguments or {},
               "session_id": ODY_CHAT_SESSION_ID, "workspace_root": ODY_WORKSPACE_ROOT}
    try:
        async with httpx.AsyncClient(timeout=180.0) as cx:
            r = await cx.post(ODY_INTERNAL_URL, headers=headers, json=payload)
        if r.status_code != 200:
            return [TextContent(type="text", text=f"Error calling {name}: HTTP {r.status_code} {r.text[:200]}")]
        data = r.json()
    except Exception as e:
        return [TextContent(type="text", text=f"Error calling {name}: {e}")]
    if not data.get("ok"):
        return [TextContent(type="text", text=f"Error: {data.get('error', 'tool failed')}")]
    return [TextContent(type="text", text=_flatten(data.get("result")))]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
