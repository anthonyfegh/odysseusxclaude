"""
slack_server.py

MCP server exposing read-only Slack access (list channels + read history).

Auth is a Slack bot token (xoxb-...) passed via env on the MCP registration:
    SLACK_BOT_TOKEN

Required Slack bot scopes: channels:read, channels:history, users:read
(add groups:read, groups:history for private channels).
The bot must be a MEMBER of a channel to read its history. Invite it with
/invite @AppName in each channel you want the agent to read.

Tools:
    slack_list_channels  - list channels and whether the bot is a member
    slack_channel_history - read recent messages from a channel
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import httpx

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API = "https://slack.com/api"
server = Server("slack")
_user_cache = {}


def _token():
    tok = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("SLACK_BOT_TOKEN not set. Add your Slack bot token to the connector.")
    return tok


def _call(method: str, params: dict) -> dict:
    headers = {"Authorization": f"Bearer {_token()}"}
    with httpx.Client(timeout=20.0) as cx:
        r = cx.get(f"{API}/{method}", headers=headers, params=params)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "unknown Slack error"))
    return data


def _list_channels(cursor: str) -> dict:
    """List conversations. Try public + private, fall back to public only when
    the token lacks groups:read (private channel scope)."""
    try:
        return _call("conversations.list", {"types": "public_channel,private_channel", "limit": 200, "cursor": cursor})
    except RuntimeError as e:
        if "missing_scope" in str(e):
            return _call("conversations.list", {"types": "public_channel", "limit": 200, "cursor": cursor})
        raise


def _channel_id(name_or_id: str) -> str:
    s = name_or_id.strip().lstrip("#")
    if s.startswith("C") and s.isupper() and len(s) > 7:
        return s  # already an id
    cur = ""
    for _ in range(10):
        data = _list_channels(cur)
        for ch in data.get("channels", []):
            if ch.get("name") == s:
                return ch["id"]
        cur = data.get("response_metadata", {}).get("next_cursor", "")
        if not cur:
            break
    raise RuntimeError(f"Channel '{name_or_id}' not found. Use slack_list_channels to see available channels.")


def _user_name(uid: str) -> str:
    if not uid:
        return "?"
    if uid in _user_cache:
        return _user_cache[uid]
    try:
        data = _call("users.info", {"user": uid})
        u = data.get("user", {})
        name = u.get("real_name") or u.get("name") or uid
    except Exception:
        name = uid
    _user_cache[uid] = name
    return name


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="slack_list_channels",
            description="List Slack channels the bot can see, and whether the bot is a member (only member channels can be read).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="slack_channel_history",
            description="Read recent messages from a Slack channel by name (e.g. 'general') or id. The bot must be a member of the channel.",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": "Channel name (without #) or channel id."},
                    "hours": {"type": "number", "description": "How many hours back to read (default 24)."},
                    "limit": {"type": "integer", "description": "Max messages (default 50)."},
                },
                "required": ["channel"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "slack_list_channels":
            cur, rows = "", []
            for _ in range(10):
                data = _list_channels(cur)
                for ch in data.get("channels", []):
                    mark = "member" if ch.get("is_member") else "not a member"
                    rows.append(f"- #{ch.get('name')}  ({mark})  id: {ch.get('id')}")
                cur = data.get("response_metadata", {}).get("next_cursor", "")
                if not cur:
                    break
            if not rows:
                return [TextContent(type="text", text="No channels visible to the bot.")]
            return [TextContent(type="text", text=f"{len(rows)} channels:\n" + "\n".join(rows))]

        if name == "slack_channel_history":
            ch = (arguments.get("channel") or "").strip()
            if not ch:
                return [TextContent(type="text", text="Error: channel is required")]
            hours = float(arguments.get("hours") or 24)
            limit = int(arguments.get("limit") or 50)
            cid = _channel_id(ch)
            oldest = time.time() - hours * 3600
            data = _call("conversations.history", {"channel": cid, "oldest": f"{oldest:.6f}", "limit": max(1, min(limit, 200))})
            msgs = list(reversed(data.get("messages", [])))
            if not msgs:
                return [TextContent(type="text", text=f"No messages in #{ch} in the last {hours:g} hours.")]
            lines = [f"Last {len(msgs)} messages in #{ch} (most recent last):\n"]
            for m in msgs:
                if m.get("subtype") and not m.get("user"):
                    continue
                who = _user_name(m.get("user", ""))
                txt = (m.get("text") or "").replace("\n", " ")
                ts = time.strftime("%b %d %H:%M", time.localtime(float(m.get("ts", "0"))))
                lines.append(f"[{ts}] {who}: {txt}")
            return [TextContent(type="text", text="\n".join(lines))]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        msg = str(e)
        if "not_in_channel" in msg:
            return [TextContent(type="text", text="The bot is not in that channel. In Slack, type /invite @YourAppName in the channel, then try again.")]
        if "missing_scope" in msg:
            return [TextContent(type="text", text=f"Slack token is missing a scope: {msg}. Add channels:read, channels:history, users:read and reinstall the app.")]
        return [TextContent(type="text", text=f"Slack error: {msg}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
