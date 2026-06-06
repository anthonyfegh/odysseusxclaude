"""Agent workspace aggregation — the Workspace console's data plane.

Surfaces everything an agent has produced, owner-scoped by ``crew_member_id``:
  * its on-disk sandbox folder (``data/agents/<id>/``) — browse + read files
  * documents it authored (Document → Session.crew_member_id)
  * generated images (GalleryImage → Session.crew_member_id)
  * deep-research reports (data/deep_research/<session_id>.json)

Run outputs are already served by ``/api/tasks/runs/recent?crew_member_id=``.

These routes share the ``/api/agents`` prefix with crew_routes; the path shapes
(``/{id}/files`` etc.) don't collide with the CRUD routes there.
"""

import json
import logging
import os
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from core.database import SessionLocal, Document, GalleryImage, ScheduledTask
from core.database import Session as DbSession
from src.auth_helpers import get_current_user
from src import crew_service as cs
from src.agent_workspace import workspace_root, resolve_in_workspace, WorkspaceEscape

logger = logging.getLogger(__name__)

_MAX_FILE_READ = 200_000  # chars returned by the file viewer

# Research/document previews sometimes carry the agent's leaked chain-of-thought
# and tool-call scaffolding. Strip <think> blocks and cut at the first tool/skill
# marker so the Workspace card shows a clean human-readable snippet.
_THINK_RE = re.compile(r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>", re.I)
_CUT_RE = re.compile(r"<tool_call|<function_call|__ODY_TOOL__|<skill\b", re.I)


def _clean_preview(text: str, n: int = 280) -> str:
    t = _THINK_RE.sub("", text or "")
    m = _CUT_RE.search(t)
    if m:
        t = t[:m.start()]
    return re.sub(r"\s+", " ", t).strip()[:n]


def setup_agent_workspace_routes() -> APIRouter:
    router = APIRouter(prefix="/api/agents", tags=["agent-workspace"])

    def _owner(request: Request) -> str:
        owner = get_current_user(request)
        if not owner:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return owner

    def _require_agent(db, agent_id: str, owner: str):
        crew = cs.find_agent(db, agent_id, owner)
        if not crew:
            raise HTTPException(status_code=404, detail="Agent not found")
        return crew

    def _agent_session_ids(db, agent_id: str, owner: str) -> set:
        """Session ids this agent owns/ran in (chat-bound + research tasks)."""
        ids = set()
        try:
            for (sid,) in (db.query(DbSession.id)
                           .filter(DbSession.crew_member_id == agent_id).all()):
                if sid:
                    ids.add(sid)
        except Exception:
            pass
        try:
            for (sid,) in (db.query(ScheduledTask.session_id)
                           .filter(ScheduledTask.crew_member_id == agent_id,
                                   ScheduledTask.session_id.isnot(None)).all()):
                if sid:
                    ids.add(sid)
        except Exception:
            pass
        return ids

    # ---- On-disk sandbox folder ----

    @router.get("/{agent_id}/files")
    async def list_files(agent_id: str, request: Request, path: str = ""):
        """List one level of the agent's workspace folder."""
        owner = _owner(request)
        db = SessionLocal()
        try:
            _require_agent(db, agent_id, owner)
        finally:
            db.close()
        root = workspace_root(agent_id)
        try:
            target = resolve_in_workspace(root, path)
        except WorkspaceEscape:
            raise HTTPException(status_code=400, detail="Path is outside the workspace")
        if not os.path.exists(target):
            raise HTTPException(status_code=404, detail="Path not found")
        if not os.path.isdir(target):
            raise HTTPException(status_code=400, detail="Not a directory")
        entries = []
        try:
            with os.scandir(target) as it:
                for e in it:
                    try:
                        st = e.stat()
                        entries.append({
                            "name": e.name,
                            "is_dir": e.is_dir(),
                            "size": 0 if e.is_dir() else st.st_size,
                            "mtime": datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z",
                        })
                    except OSError:
                        continue
        except OSError as ex:
            raise HTTPException(status_code=500, detail=f"Cannot read directory: {ex}")
        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        rel = os.path.relpath(target, root)
        return {"path": "" if rel == "." else rel, "entries": entries}

    @router.get("/{agent_id}/files/read")
    async def read_file(agent_id: str, request: Request, path: str):
        """Return a single workspace file's contents (text), confined + capped."""
        owner = _owner(request)
        db = SessionLocal()
        try:
            _require_agent(db, agent_id, owner)
        finally:
            db.close()
        root = workspace_root(agent_id)
        try:
            target = resolve_in_workspace(root, path)
        except WorkspaceEscape:
            raise HTTPException(status_code=400, detail="Path is outside the workspace")
        if not os.path.isfile(target):
            raise HTTPException(status_code=404, detail="File not found")
        st = os.stat(target)
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = f.read(_MAX_FILE_READ + 1)
            binary = False
        except (UnicodeDecodeError, ValueError):
            data = ""
            binary = True
        truncated = (not binary) and len(data) > _MAX_FILE_READ
        if truncated:
            data = data[:_MAX_FILE_READ]
        rel = os.path.relpath(target, root)
        return {
            "path": rel,
            "name": os.path.basename(target),
            "size": st.st_size,
            "mtime": datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z",
            "binary": binary,
            "truncated": truncated,
            "content": data,
        }

    # ---- Documents ----

    @router.get("/{agent_id}/documents")
    async def list_documents(agent_id: str, request: Request):
        """Documents authored in this agent's sessions (library card shape)."""
        owner = _owner(request)
        db = SessionLocal()
        try:
            _require_agent(db, agent_id, owner)
            rows = (db.query(Document, DbSession.name)
                    .join(DbSession, Document.session_id == DbSession.id)
                    .filter(DbSession.crew_member_id == agent_id,
                            Document.is_active == True,  # noqa: E712
                            Document.archived == False)  # noqa: E712
                    .order_by(Document.updated_at.desc())
                    .limit(200).all())
            return {"documents": [{
                "id": d.id,
                "session_id": d.session_id,
                "session_name": sname,
                "title": d.title,
                "language": d.language or "text",
                "preview": (d.current_content or "")[:500],
                "version_count": d.version_count,
                "created_at": (d.created_at.isoformat() + "Z") if d.created_at else None,
                "updated_at": (d.updated_at.isoformat() + "Z") if d.updated_at else None,
            } for (d, sname) in rows]}
        finally:
            db.close()

    # ---- Generated images ----

    @router.get("/{agent_id}/images")
    async def list_images(agent_id: str, request: Request):
        """Gallery images generated in this agent's sessions."""
        owner = _owner(request)
        db = SessionLocal()
        try:
            _require_agent(db, agent_id, owner)
            rows = (db.query(GalleryImage, DbSession.name)
                    .join(DbSession, GalleryImage.session_id == DbSession.id)
                    .filter(DbSession.crew_member_id == agent_id,
                            GalleryImage.is_active == True)  # noqa: E712
                    .order_by(GalleryImage.created_at.desc())
                    .limit(200).all())
            try:
                from routes.gallery_helpers import _image_to_dict
                images = [_image_to_dict(img, sname) for (img, sname) in rows]
            except Exception:
                images = [{
                    "id": img.id,
                    "filename": img.filename,
                    "url": f"/api/generated-image/{img.filename}",
                    "prompt": img.prompt,
                    "session_id": img.session_id,
                    "session_name": sname,
                    "created_at": img.created_at.isoformat() if img.created_at else None,
                } for (img, sname) in rows]
            return {"images": images}
        finally:
            db.close()

    # ---- Deep-research reports ----

    @router.get("/{agent_id}/research")
    async def list_research(agent_id: str, request: Request):
        """Deep-research reports produced in this agent's sessions."""
        owner = _owner(request)
        db = SessionLocal()
        try:
            _require_agent(db, agent_id, owner)
            session_ids = _agent_session_ids(db, agent_id, owner)
        finally:
            db.close()
        if not session_ids:
            return {"research": []}
        try:
            from src.research_handler import RESEARCH_DATA_DIR
            base = str(RESEARCH_DATA_DIR)
        except Exception:
            base = os.path.join("data", "deep_research")
        reports = []
        for sid in session_ids:
            fp = os.path.join(base, f"{sid}.json")
            if not os.path.isfile(fp):
                continue
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    rec = json.load(f)
            except Exception:
                continue
            if owner and rec.get("owner") and rec.get("owner") != owner:
                continue

            def _iso(ts):
                try:
                    return datetime.utcfromtimestamp(float(ts)).isoformat() + "Z"
                except Exception:
                    return None

            srcs = rec.get("sources") or []
            reports.append({
                "session_id": sid,
                "research_id": sid,
                "query": rec.get("query") or "Research",
                "status": rec.get("status") or "done",
                "source_count": len(srcs) if isinstance(srcs, list) else 0,
                "preview": _clean_preview(rec.get("result") or rec.get("raw_report") or ""),
                "started_at": _iso(rec.get("started_at")),
                "completed_at": _iso(rec.get("completed_at")),
            })
        reports.sort(key=lambda r: r.get("completed_at") or r.get("started_at") or "", reverse=True)
        return {"research": reports}

    return router
