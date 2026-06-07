"""
internal_routes.py — localhost-only tool execution for per-agent Claude Code sessions.

A claude_code agent runs as a full Claude Code session; Odysseus's own app tools
are exposed to it via an MCP server (mcp_servers/odysseus_server.py) that is a thin
PROXY — it forwards every tool call here so the tool runs INSIDE the main app
process, with full runtime state (the injected memory manager, ui_control's live
event bus, in-flight sessions, the research engine, …). Running tools in the MCP
subprocess can't reach that state.

Auth reuses the existing internal-token mechanism: the auth middleware (app.py)
already authenticates a trusted-loopback request carrying X-Odysseus-Internal-Token
(matching core.middleware.INTERNAL_TOOL_TOKEN) and impersonates X-Odysseus-Owner.
We re-check the token here as defense in depth.
"""
import json
import logging
import secrets
from types import SimpleNamespace

from fastapi import APIRouter, Request, HTTPException

from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
from src.auth_helpers import get_current_user

logger = logging.getLogger(__name__)


def setup_internal_routes() -> APIRouter:
    router = APIRouter(prefix="/api/internal", tags=["internal"])

    @router.post("/agent_tool")
    async def agent_tool(request: Request):
        # Defense in depth: require the internal token even though the auth
        # middleware already gated us. Constant-time compare.
        hdr = request.headers.get(INTERNAL_TOOL_HEADER) or ""
        if not (hdr and secrets.compare_digest(hdr, INTERNAL_TOOL_TOKEN)):
            raise HTTPException(403, "forbidden")
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "invalid json body")

        tool = (body.get("tool") or "").strip()
        if not tool:
            raise HTTPException(400, "tool required")
        args = body.get("args") or {}
        session_id = body.get("session_id") or None
        workspace_root = body.get("workspace_root") or None
        # Owner is set by the middleware's X-Odysseus-Owner impersonation.
        owner = get_current_user(request)

        from src.tool_execution import execute_tool_block
        from src.tool_schemas import function_call_to_tool_block
        # Reuse the SAME native-args -> ToolBlock conversion the agent loop uses
        # (agent_loop.py:1017) so every tool gets its content in the exact format
        # it expects (and email routes to its MCP server).
        block = function_call_to_tool_block(tool, json.dumps(args))
        if block is None:
            return {"ok": False, "error": f"Unknown or invalid tool: {tool}"}
        try:
            _desc, result = await execute_tool_block(
                block, session_id=session_id, owner=owner, workspace_root=workspace_root)
        except Exception as e:
            logger.exception("internal agent_tool '%s' failed", tool)
            return {"ok": False, "error": str(e)}
        return {"ok": True, "result": result}

    return router
