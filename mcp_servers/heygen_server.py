"""
heygen_server.py

MCP server for HeyGen AI avatar video generation.

Env vars:
    HEYGEN_API_KEY  - HeyGen API key

Tools:
    heygen_list_avatars   - list available avatars
    heygen_list_voices    - list available voices
    heygen_create_video   - submit an avatar video generation job
    heygen_video_status   - check the status of a video job
    heygen_list_videos    - list recent generated videos with download links
"""

import json
import os
import sys
from pathlib import Path

import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = "https://api.heygen.com/v2"
BASE_URL_V1 = "https://api.heygen.com/v1"
server = Server("heygen")


def _headers():
    key = os.environ.get("HEYGEN_API_KEY", "")
    if not key:
        raise RuntimeError("HEYGEN_API_KEY not set.")
    return {"X-Api-Key": key, "Content-Type": "application/json"}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="heygen_list_avatars",
            description="List available HeyGen avatars (id and name). Use avatar_id with heygen_create_video.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="heygen_list_voices",
            description="List available HeyGen voices filtered by language. Use voice_id with heygen_create_video.",
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "description": "Filter by language code, e.g. 'en', 'es', 'pt'. Leave empty for all."},
                },
            },
        ),
        Tool(
            name="heygen_create_video",
            description=(
                "Submit a HeyGen avatar video generation job. Provide a script, avatar_id and voice_id. "
                "Returns a video_id — use heygen_video_status to check when it's ready."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "The spoken script for the avatar."},
                    "avatar_id": {"type": "string", "description": "Avatar ID from heygen_list_avatars."},
                    "voice_id": {"type": "string", "description": "Voice ID from heygen_list_voices."},
                    "title": {"type": "string", "description": "Optional title for the video."},
                    "width": {"type": "integer", "description": "Width in pixels (default 1280)."},
                    "height": {"type": "integer", "description": "Height in pixels (default 720)."},
                },
                "required": ["script", "avatar_id", "voice_id"],
            },
        ),
        Tool(
            name="heygen_video_status",
            description="Check the status of a HeyGen video generation job. Returns status and download URL when complete.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "The video_id returned by heygen_create_video."},
                },
                "required": ["video_id"],
            },
        ),
        Tool(
            name="heygen_list_videos",
            description="List recently generated HeyGen videos with their status and download links.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of videos to return (default 10)."},
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "heygen_list_avatars":
        r = requests.get(f"{BASE_URL}/avatars", headers=_headers(), timeout=15)
        r.raise_for_status()
        avatars = r.json().get("data", {}).get("avatars", [])
        lines = [f"Available avatars ({len(avatars)}):"]
        for a in avatars[:30]:
            lines.append(f"  {a['avatar_id']} | {a.get('avatar_name', '')}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "heygen_list_voices":
        lang = arguments.get("language", "")
        r = requests.get(f"{BASE_URL}/voices", headers=_headers(), timeout=15)
        r.raise_for_status()
        voices = r.json().get("data", {}).get("voices", [])
        if lang:
            voices = [v for v in voices if v.get("language", "").lower().startswith(lang.lower())]
        lines = [f"Voices ({len(voices)}):"]
        for v in voices[:40]:
            lines.append(f"  {v['voice_id']} | {v.get('display_name', '')} | {v.get('language', '')} | {v.get('gender', '')}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "heygen_create_video":
        payload = {
            "video_inputs": [{
                "character": {
                    "type": "avatar",
                    "avatar_id": arguments["avatar_id"],
                    "avatar_style": "normal",
                },
                "voice": {
                    "type": "text",
                    "input_text": arguments["script"],
                    "voice_id": arguments["voice_id"],
                },
            }],
            "dimension": {
                "width": arguments.get("width", 1280),
                "height": arguments.get("height", 720),
            },
            "title": arguments.get("title", "Odysseus Generated Video"),
        }
        r = requests.post(f"{BASE_URL}/video/generate", headers=_headers(), json=payload, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", {})
        video_id = data.get("video_id", "")
        return [TextContent(type="text", text=f"Video job submitted.\nvideo_id: {video_id}\nUse heygen_video_status to check when it's ready (usually 2–5 minutes).")]

    if name == "heygen_video_status":
        video_id = arguments["video_id"]
        r = requests.get(f"{BASE_URL}/video/{video_id}", headers=_headers(), timeout=15)
        r.raise_for_status()
        data = r.json().get("data", {})
        status = data.get("status", "unknown")
        url = data.get("video_url", "")
        lines = [f"Video ID: {video_id}", f"Status: {status}"]
        if url:
            lines.append(f"Download URL: {url}")
        if data.get("error"):
            lines.append(f"Error: {data['error']}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "heygen_list_videos":
        limit = arguments.get("limit", 10)
        r = requests.get(f"{BASE_URL}/videos", headers=_headers(), params={"limit": limit}, timeout=15)
        r.raise_for_status()
        videos = r.json().get("data", {}).get("videos", [])
        lines = [f"Recent videos ({len(videos)}):"]
        for v in videos:
            url = v.get("video_url", "pending")
            lines.append(f"  [{v.get('status')}] {v.get('title', v.get('video_id', ''))} — {url[:60] if url != 'pending' else 'not ready'}")
        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
