"""
holded_server.py

MCP server for Holded (Spanish business management / ERP).

Env vars:
    HOLDED_API_KEY  - Holded API key (Settings > Integrations > API)

Tools:
    holded_list_invoices   - list sales or purchase invoices
    holded_get_invoice     - get full details of one invoice
    holded_list_contacts   - list contacts (clients, suppliers)
    holded_list_expenses   - list expenses / purchase documents
"""

import os
import sys
from pathlib import Path

import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = "https://api.holded.com/api"
server = Server("holded")


def _headers():
    key = os.environ.get("HOLDED_API_KEY", "")
    if not key:
        raise RuntimeError("HOLDED_API_KEY not set. Get it from Holded Settings > Integrations > API.")
    return {"key": key, "Content-Type": "application/json"}


def _eur(cents) -> str:
    try:
        return f"€{float(cents)/100:,.2f}"
    except Exception:
        return str(cents)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="holded_list_invoices",
            description=(
                "List Holded invoices (sales or purchase). Returns invoice number, date, contact, amount and status. "
                "Use holded_get_invoice for full details."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "'sales' for outgoing invoices, 'purchase' for supplier invoices. Default: sales."},
                    "status": {"type": "string", "description": "Filter by status: 'pending', 'paid', 'overdue'. Leave empty for all."},
                    "limit": {"type": "integer", "description": "Max number to return (default 20)."},
                },
            },
        ),
        Tool(
            name="holded_get_invoice",
            description="Get full details of a Holded invoice by its ID, including line items, taxes, and payment info.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {"type": "string", "description": "Invoice ID from holded_list_invoices."},
                    "type": {"type": "string", "description": "'sales' or 'purchase'. Default: sales."},
                },
                "required": ["invoice_id"],
            },
        ),
        Tool(
            name="holded_list_contacts",
            description="List Holded contacts (clients and suppliers) with name, email, and tax ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "'client', 'supplier', or leave empty for all."},
                    "limit": {"type": "integer", "description": "Max number to return (default 30)."},
                },
            },
        ),
        Tool(
            name="holded_list_expenses",
            description="List recent expense documents in Holded (purchase invoices / supplier bills).",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max number to return (default 20)."},
                    "status": {"type": "string", "description": "Filter by status: 'pending', 'paid'. Leave empty for all."},
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    h = _headers()

    if name == "holded_list_invoices":
        doc_type = arguments.get("type", "sales")
        limit = arguments.get("limit", 20)
        params = {"page": 1}
        if arguments.get("status"):
            params["status"] = arguments["status"]

        endpoint = "invoicing/v1/documents/invoice" if doc_type == "sales" else "invoicing/v1/documents/bill"
        r = requests.get(f"{BASE_URL}/{endpoint}", headers=h, params=params, timeout=15)
        r.raise_for_status()
        docs = r.json() if isinstance(r.json(), list) else r.json().get("docs", r.json().get("data", []))
        docs = docs[:limit]

        lines = [f"{doc_type.title()} invoices ({len(docs)}):"]
        for d in docs:
            num = d.get("docNumber", d.get("number", ""))
            date = d.get("date", "")
            contact = d.get("contactName", d.get("contact", {}).get("name", ""))
            amount = _eur(d.get("total", d.get("amount", 0)))
            status = d.get("status", "")
            doc_id = d.get("id", d.get("_id", ""))
            lines.append(f"  [{status}] {num} | {date} | {contact} | {amount} | id:{doc_id}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "holded_get_invoice":
        doc_type = arguments.get("type", "sales")
        invoice_id = arguments["invoice_id"]
        endpoint = "invoicing/v1/documents/invoice" if doc_type == "sales" else "invoicing/v1/documents/bill"
        r = requests.get(f"{BASE_URL}/{endpoint}/{invoice_id}", headers=h, timeout=15)
        r.raise_for_status()
        d = r.json()

        lines = [
            f"Invoice: {d.get('docNumber', d.get('number', invoice_id))}",
            f"Date: {d.get('date', '')}",
            f"Contact: {d.get('contactName', '')} | NIF/CIF: {d.get('contactCode', '')}",
            f"Status: {d.get('status', '')}",
            f"Total: {_eur(d.get('total', 0))} | Tax: {_eur(d.get('totalTax', 0))} | Base: {_eur(d.get('subtotal', 0))}",
            "",
            "Line items:",
        ]
        for item in d.get("items", []):
            desc = item.get("name", item.get("desc", ""))
            qty = item.get("units", item.get("quantity", 1))
            price = _eur(item.get("subtotal", item.get("price", 0)))
            lines.append(f"  {qty}× {desc} — {price}")

        notes = d.get("notes", "")
        if notes:
            lines.append(f"\nNotes: {notes}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "holded_list_contacts":
        ctype = arguments.get("type", "")
        limit = arguments.get("limit", 30)
        params = {"page": 1}
        if ctype:
            params["type"] = ctype
        r = requests.get(f"{BASE_URL}/crm/v1/contacts", headers=h, params=params, timeout=15)
        r.raise_for_status()
        contacts = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
        contacts = contacts[:limit]
        lines = [f"Contacts ({len(contacts)}):"]
        for c in contacts:
            name = c.get("name", "")
            email = c.get("email", "")
            nif = c.get("code", "")
            cid = c.get("id", c.get("_id", ""))
            lines.append(f"  {name} | {email} | NIF:{nif} | id:{cid}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "holded_list_expenses":
        limit = arguments.get("limit", 20)
        params = {"page": 1}
        if arguments.get("status"):
            params["status"] = arguments["status"]
        r = requests.get(f"{BASE_URL}/invoicing/v1/documents/bill", headers=h, params=params, timeout=15)
        r.raise_for_status()
        docs = r.json() if isinstance(r.json(), list) else r.json().get("docs", r.json().get("data", []))
        docs = docs[:limit]
        lines = [f"Expenses/bills ({len(docs)}):"]
        for d in docs:
            num = d.get("docNumber", d.get("number", ""))
            date = d.get("date", "")
            contact = d.get("contactName", "")
            amount = _eur(d.get("total", 0))
            status = d.get("status", "")
            doc_id = d.get("id", d.get("_id", ""))
            lines.append(f"  [{status}] {num} | {date} | {contact} | {amount} | id:{doc_id}")
        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
