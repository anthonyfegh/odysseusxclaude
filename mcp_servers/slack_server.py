"""
slack_server.py

MCP server for Slack — read channels/history and send messages.

Auth is a Slack bot token (xoxb-...) passed via env:
    SLACK_BOT_TOKEN

Required Slack bot scopes:
    channels:read, channels:history, users:read, chat:write
    (add groups:read, groups:history for private channels)

The bot must be a MEMBER of a channel to read or post to it.
Invite it with /invite @AppName in each channel.

Tools:
    slack_list_channels   - list channels visible to the bot
    slack_channel_history - read recent messages from a channel
    slack_send_message    - post a message to a channel
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


def _get(method: str, params: dict) -> dict:
    headers = {"Authorization": f"Bearer {_token()}"}
    with httpx.Client(timeout=20.0) as cx:
        r = cx.get(f"{API}/{method}", headers=headers, params=params)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "unknown Slack error"))
    return data


def _post(method: str, payload: dict) -> dict:
    headers = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}
    with httpx.Client(timeout=20.0) as cx:
        r = cx.post(f"{API}/{method}", headers=headers, json=payload)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "unknown Slack error"))
    return data


def _list_channels(cursor: str) -> dict:
    try:
        return _get("conversations.list", {"types": "public_channel,private_channel", "limit": 200, "cursor": cursor})
    except RuntimeError as e:
        if "missing_scope" in str(e):
            return _get("conversations.list", {"types": "public_channel", "limit": 200, "cursor": cursor})
        raise


def _channel_id(name_or_id: str) -> str:
    s = name_or_id.strip().lstrip("#")
    if s.startswith("C") and len(s) > 7:
        return s
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
        data = _get("users.info", {"user": uid})
        u = data.get("user", {})
        name = u.get("real_name") or u.get("name") or uid
    except Exception:
        name = uid
    _user_cache[uid] = name
    return name


def _do_list_channels() -> str:
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
        return "No channels visible to the bot."
    return f"{len(rows)} channels:\n" + "\n".join(rows)


def _do_channel_history(ch: str, hours: float, limit: int) -> str:
    cid = _channel_id(ch)
    oldest = time.time() - hours * 3600
    data = _get("conversations.history", {"channel": cid, "oldest": f"{oldest:.6f}", "limit": max(1, min(limit, 200))})
    msgs = list(reversed(data.get("messages", [])))
    if not msgs:
        return f"No messages in #{ch} in the last {hours:g} hours."
    lines = [f"Last {len(msgs)} messages in #{ch} (most recent last):\n"]
    for m in msgs:
        if m.get("subtype") and not m.get("user"):
            continue
        who = _user_name(m.get("user", ""))
        txt = (m.get("text") or "").replace("\n", " ")
        ts = time.strftime("%b %d %H:%M", time.localtime(float(m.get("ts", "0"))))
        lines.append(f"[{ts}] {who}: {txt}")
    return "\n".join(lines)


def _do_send_message(ch: str, text: str) -> str:
    cid = _channel_id(ch)
    data = _post("chat.postMessage", {"channel": cid, "text": text})
    ts = data.get("ts", "")
    return f"Message sent to #{ch} (ts: {ts})"


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="slack_list_channels",
            description="List Slack channels the bot can see, and whether the bot is a member (only member channels can be read or posted to).",
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
        Tool(
            name="slack_send_message",
            description="Send a message to a Slack channel. The bot must be a member of the channel (use /invite @AppName in Slack first). Supports Slack markdown (*bold*, _italic_, bullet lists).",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": "Channel name (without #) or channel id."},
                    "text": {"type": "string", "description": "Message text. Supports Slack markdown."},
                },
                "required": ["channel", "text"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "slack_list_channels":
            result = await asyncio.to_thread(_do_list_channels)
            return [TextContent(type="text", text=result)]

        if name == "slack_channel_history":
            ch = (arguments.get("channel") or "").strip()
            if not ch:
                return [TextContent(type="text", text="Error: channel is required")]
            hours = float(arguments.get("hours") or 24)
            limit = int(arguments.get("limit") or 50)
            result = await asyncio.to_thread(_do_channel_history, ch, hours, limit)
            return [TextContent(type="text", text=result)]

        if name == "slack_send_message":
            ch = (arguments.get("channel") or "").strip()
            text = (arguments.get("text") or "").strip()
            if not ch or not text:
                return [TextContent(type="text", text="Error: channel and text are required")]
            result = await asyncio.to_thread(_do_send_message, ch, text)
            return [TextContent(type="text", text=result)]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        msg = str(e)
        if "not_in_channel" in msg:
            return [TextContent(type="text", text="The bot is not in that channel. In Slack, type /invite @YourAppName in the channel, then try again.")]
        if "missing_scope" in msg:
            return [TextContent(type="text", text=f"Slack token is missing a required scope: {msg}. For sending messages, the bot needs chat:write scope — reinstall the app with that scope added.")]
        return [TextContent(type="text", text=f"Slack error: {msg}")]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
