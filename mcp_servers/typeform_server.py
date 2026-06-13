"""
typeform_server.py

MCP server for reading Typeform form responses.

Env vars:
    TYPEFORM_API_KEY  - Typeform personal access token

Tools:
    typeform_list_forms      - list all forms in the account
    typeform_get_responses   - get responses from a specific form
    typeform_response_summary - summarise responses from a form (counts, trends)
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

BASE_URL = "https://api.typeform.com"
server = Server("typeform")


def _headers():
    key = os.environ.get("TYPEFORM_API_KEY", "")
    if not key:
        raise RuntimeError("TYPEFORM_API_KEY not set. Create a personal access token at typeform.com/developers.")
    return {"Authorization": f"Bearer {key}"}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="typeform_list_forms",
            description="List all Typeform forms in the account (id, title, response count). Use form_id with other tools.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="typeform_get_responses",
            description="Get the most recent responses from a Typeform form, including all answers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "form_id": {"type": "string", "description": "Form ID from typeform_list_forms."},
                    "limit": {"type": "integer", "description": "Number of responses to return (default 25, max 1000)."},
                    "since": {"type": "string", "description": "Optional ISO date to get responses submitted after this date, e.g. '2026-06-01T00:00:00'."},
                },
                "required": ["form_id"],
            },
        ),
        Tool(
            name="typeform_response_summary",
            description=(
                "Summarise responses from a Typeform. Returns: total count, submission timeline, "
                "and a question-by-question breakdown of answers. Good for participant feedback, surveys."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "form_id": {"type": "string", "description": "Form ID from typeform_list_forms."},
                    "limit": {"type": "integer", "description": "Number of recent responses to summarise (default 100)."},
                },
                "required": ["form_id"],
            },
        ),
    ]


def _get_form_fields(form_id: str, headers: dict) -> dict:
    """Return a dict of field_id -> title for a form."""
    r = requests.get(f"{BASE_URL}/forms/{form_id}", headers=headers, timeout=15)
    r.raise_for_status()
    fields = r.json().get("fields", [])
    return {f["id"]: f.get("title", f["id"]) for f in fields}


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    h = _headers()

    if name == "typeform_list_forms":
        r = requests.get(f"{BASE_URL}/forms", headers=h, params={"page_size": 50}, timeout=15)
        r.raise_for_status()
        forms = r.json().get("items", [])
        lines = [f"Forms ({len(forms)}):"]
        for f in forms:
            lines.append(f"  {f['id']} | {f.get('title', 'Untitled')} | {f.get('_links', {}).get('display', '')}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "typeform_get_responses":
        form_id = arguments["form_id"]
        limit = min(arguments.get("limit", 25), 1000)
        params = {"page_size": limit, "sort": "submitted_at,desc"}
        if arguments.get("since"):
            params["since"] = arguments["since"]

        fields = _get_form_fields(form_id, h)
        r = requests.get(f"{BASE_URL}/forms/{form_id}/responses", headers=h, params=params, timeout=20)
        r.raise_for_status()
        items = r.json().get("items", [])

        lines = [f"Responses ({len(items)}) for form {form_id}:"]
        for item in items:
            lines.append(f"\n  Submitted: {item.get('submitted_at', '')[:19]}")
            for answer in item.get("answers", []):
                field_id = answer.get("field", {}).get("id", "")
                question = fields.get(field_id, field_id)
                atype = answer.get("type", "")
                if atype == "text":
                    val = answer.get("text", "")
                elif atype == "choice":
                    val = answer.get("choice", {}).get("label", "")
                elif atype == "choices":
                    val = ", ".join(c.get("label", "") for c in answer.get("choices", {}).get("labels", []))
                elif atype == "number":
                    val = str(answer.get("number", ""))
                elif atype == "boolean":
                    val = str(answer.get("boolean", ""))
                else:
                    val = str(answer.get(atype, ""))
                lines.append(f"    Q: {question[:60]}")
                lines.append(f"    A: {val[:120]}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "typeform_response_summary":
        form_id = arguments["form_id"]
        limit = min(arguments.get("limit", 100), 1000)
        fields = _get_form_fields(form_id, h)
        r = requests.get(f"{BASE_URL}/forms/{form_id}/responses",
            headers=h, params={"page_size": limit, "sort": "submitted_at,desc"}, timeout=20)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        total = data.get("total_items", len(items))

        # Aggregate answers by field
        from collections import defaultdict, Counter
        field_answers: dict = defaultdict(list)
        for item in items:
            for answer in item.get("answers", []):
                field_id = answer.get("field", {}).get("id", "")
                atype = answer.get("type", "")
                if atype == "choice":
                    val = answer.get("choice", {}).get("label", "")
                elif atype == "choices":
                    val = ", ".join(c.get("label","") for c in answer.get("choices",{}).get("labels",[]))
                elif atype == "text":
                    val = answer.get("text", "")[:100]
                elif atype == "number":
                    val = str(answer.get("number", ""))
                elif atype == "boolean":
                    val = "Yes" if answer.get("boolean") else "No"
                else:
                    val = ""
                if val:
                    field_answers[field_id].append(val)

        lines = [f"Summary for form {form_id}", f"Total responses: {total} (summarising {len(items)})"]
        for field_id, question in fields.items():
            answers = field_answers.get(field_id, [])
            if not answers:
                continue
            lines.append(f"\nQ: {question}")
            counts = Counter(answers)
            if len(counts) <= 10:
                for val, count in counts.most_common():
                    pct = round(count / len(answers) * 100)
                    lines.append(f"  {val}: {count} ({pct}%)")
            else:
                lines.append(f"  {len(answers)} text responses (open-ended)")
                for ans in answers[:3]:
                    lines.append(f"    • {ans}")
                if len(answers) > 3:
                    lines.append(f"    ... and {len(answers)-3} more")
        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
