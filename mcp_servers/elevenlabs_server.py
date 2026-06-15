"""
elevenlabs_server.py

MCP server for ElevenLabs text-to-speech.

Env vars:
    ELEVENLABS_API_KEY  - ElevenLabs API key

Tools:
    elevenlabs_list_voices  - list available voices
    elevenlabs_tts          - convert text to speech, returns a local file path
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = "https://api.elevenlabs.io/v1"
server = Server("elevenlabs")


def _headers():
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY not set.")
    return {"xi-api-key": key}


def _get(url, **kwargs):
    return requests.get(url, headers=_headers(), **kwargs)

def _post(url, **kwargs):
    return requests.post(url, headers=_headers(), **kwargs)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="elevenlabs_list_voices",
            description="List available ElevenLabs voices (id, name, category). Use a voice_id with elevenlabs_tts.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="elevenlabs_tts",
            description=(
                "Convert text to speech using ElevenLabs. Returns the path to a saved MP3 file. "
                "Use elevenlabs_list_voices to get a voice_id. Default voice is Rachel if not specified."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to convert to speech."},
                    "voice_id": {"type": "string", "description": "ElevenLabs voice ID. Defaults to Rachel (21m00Tcm4TlvDq8ikWAM)."},
                    "model_id": {"type": "string", "description": "Model ID. Default: eleven_multilingual_v2 (supports EN/ES/PT and more)."},
                    "output_path": {"type": "string", "description": "Optional: where to save the MP3. Defaults to a temp file."},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="elevenlabs_usage",
            description="Check ElevenLabs account character usage and remaining quota.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "elevenlabs_list_voices":
        r = await asyncio.to_thread(_get, f"{BASE_URL}/voices", timeout=15)
        r.raise_for_status()
        voices = r.json().get("voices", [])
        lines = ["Available voices:"]
        for v in voices:
            lines.append(f"  {v['voice_id']} | {v['name']} | {v.get('category', '')}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "elevenlabs_tts":
        text = arguments["text"]
        voice_id = arguments.get("voice_id", "21m00Tcm4TlvDq8ikWAM")  # Rachel
        model_id = arguments.get("model_id", "eleven_multilingual_v2")
        output_path = arguments.get("output_path")

        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        r = await asyncio.to_thread(
            _post,
            f"{BASE_URL}/text-to-speech/{voice_id}",
            headers={**_headers(), "Content-Type": "application/json", "Accept": "audio/mpeg"},
            json=payload,
            timeout=60,
        )
        r.raise_for_status()

        if output_path:
            path = output_path
        else:
            fd, path = tempfile.mkstemp(suffix=".mp3", prefix="ody_tts_")
            os.close(fd)

        with open(path, "wb") as f:
            f.write(r.content)

        size_kb = len(r.content) // 1024
        return [TextContent(type="text", text=f"Audio saved to: {path} ({size_kb} KB)\nCharacters used: {len(text)}")]

    if name == "elevenlabs_usage":
        r = await asyncio.to_thread(_get, f"{BASE_URL}/user/subscription", timeout=15)
        r.raise_for_status()
        sub = r.json()
        used = sub.get("character_count", 0)
        limit = sub.get("character_limit", 0)
        remaining = limit - used
        tier = sub.get("tier", "unknown")
        return [TextContent(type="text", text=f"Plan: {tier}\nCharacters used: {used:,} / {limit:,}\nRemaining: {remaining:,}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
