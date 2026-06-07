"""Multi-agent CRUD — list/create/edit/duplicate/delete CrewMembers (agents).

The single default assistant keeps its dedicated routes in assistant_routes.py;
this router manages the *roster* of additional agents. All agent model calls
still flow through the configured endpoint (the claude -p sidecar by default):
endpoint_url is validated against enabled ModelEndpoints, and an empty
model/endpoint means "use the resolver default" (the sidecar).
"""

from datetime import datetime
from typing import List, Optional, Union

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.database import SessionLocal, CrewMember, ScheduledTask
from core.database import Session as DbSession
from src.auth_helpers import get_current_user
from src import crew_service as cs
from src import agent_builder


class AgentCreate(BaseModel):
    name: str
    personality: Optional[str] = None
    description: Optional[str] = None
    greeting: Optional[str] = None
    model: Optional[str] = None
    endpoint_url: Optional[str] = None
    enabled_tools: Optional[Union[List[str], str]] = None  # list, or "all"
    avatar: Optional[str] = None
    user_name: Optional[str] = None
    color: Optional[str] = None
    category: Optional[str] = None
    timezone: Optional[str] = None


class BuilderStart(BaseModel):
    seed_agent_id: Optional[str] = None
    seed_template: Optional[dict] = None


class BuilderMessage(BaseModel):
    message: str


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    personality: Optional[str] = None
    description: Optional[str] = None
    greeting: Optional[str] = None
    model: Optional[str] = None
    endpoint_url: Optional[str] = None
    enabled_tools: Optional[Union[List[str], str]] = None
    allow_autonomous_email: Optional[bool] = None
    avatar: Optional[str] = None
    user_name: Optional[str] = None
    color: Optional[str] = None
    category: Optional[str] = None
    timezone: Optional[str] = None
    engine: Optional[str] = None   # "legacy" | "claude_code"


def setup_crew_routes() -> APIRouter:
    router = APIRouter(prefix="/api/agents", tags=["agents"])

    def _owner(request: Request) -> str:
        owner = get_current_user(request)
        if not owner:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return owner

    def _check_endpoint(db, endpoint_url: Optional[str], owner: str):
        if not cs.validate_endpoint_url(db, endpoint_url, owner):
            raise HTTPException(
                status_code=400,
                detail="endpoint_url must be a configured, enabled model endpoint (e.g. the claude -p sidecar).",
            )

    @router.get("")
    async def list_agents(request: Request):
        owner = _owner(request)
        db = SessionLocal()
        try:
            return {"agents": [cs.crew_to_dict(a) for a in cs.list_agents(db, owner)]}
        finally:
            db.close()

    @router.post("")
    async def create_agent(payload: AgentCreate, request: Request):
        owner = _owner(request)
        if not (payload.name or "").strip():
            raise HTTPException(status_code=400, detail="name is required")
        db = SessionLocal()
        try:
            _check_endpoint(db, payload.endpoint_url, owner)
            # Place new agents after existing ones.
            max_sort = db.query(CrewMember).filter(CrewMember.owner == owner).count()
            crew = CrewMember(
                id=cs.new_agent_id(),
                owner=owner,
                name=payload.name.strip(),
                is_default_assistant=False,
                is_active=True,
                sort_order=max_sort,
                status=None,
            )
            cs.apply_crew_fields(crew, payload.model_dump(exclude_unset=True))
            db.add(crew)
            db.commit()
            db.refresh(crew)
            return {"agent": cs.crew_to_dict(crew)}
        finally:
            db.close()

    @router.get("/{agent_id}")
    async def get_agent(agent_id: str, request: Request):
        owner = _owner(request)
        db = SessionLocal()
        try:
            crew = cs.find_agent(db, agent_id, owner)
            if not crew:
                raise HTTPException(status_code=404, detail="Agent not found")
            return {"agent": cs.crew_to_dict(crew)}
        finally:
            db.close()

    @router.patch("/{agent_id}")
    async def update_agent(agent_id: str, payload: AgentUpdate, request: Request):
        owner = _owner(request)
        db = SessionLocal()
        try:
            crew = cs.find_agent(db, agent_id, owner)
            if not crew:
                raise HTTPException(status_code=404, detail="Agent not found")
            if payload.endpoint_url is not None:
                _check_endpoint(db, payload.endpoint_url, owner)
            cs.apply_crew_fields(crew, payload.model_dump(exclude_unset=True))
            crew.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(crew)
            return {"agent": cs.crew_to_dict(crew)}
        finally:
            db.close()

    @router.post("/{agent_id}/reset_session")
    async def reset_agent_session(agent_id: str, request: Request):
        """Start a fresh chat for this agent: archive ALL of its current ongoing
        chats (kept searchable) and clear its session pins, so the agent's working
        memory resets while the past chats are preserved. The fresh session is
        created lazily on the next message (avoids leaving an empty, sweep-prone
        session behind), so one-chat-per-agent resolves to a clean new chat."""
        owner = _owner(request)
        db = SessionLocal()
        try:
            crew = cs.find_agent(db, agent_id, owner)
            if not crew:
                raise HTTPException(status_code=404, detail="Agent not found")
            # The ongoing chat is linked by crew_member_id, not only by the
            # CrewMember.session_id pin — archive every non-archived bound session.
            rows = db.query(DbSession).filter(
                DbSession.crew_member_id == agent_id,
                DbSession.archived == False,  # noqa: E712
            ).all()
            archived_ids = [r.id for r in rows]
            for r in rows:
                r.archived = True
            crew.session_id = None
            crew.claude_session_id = None  # mints a new claude session on next message
            db.commit()
            return {"ok": True, "archived_sessions": archived_ids, "new_session": None}
        finally:
            db.close()

    @router.delete("/{agent_id}")
    async def delete_agent(agent_id: str, request: Request):
        owner = _owner(request)
        db = SessionLocal()
        try:
            crew = cs.find_agent(db, agent_id, owner)
            if not crew:
                raise HTTPException(status_code=404, detail="Agent not found")
            if crew.is_default_assistant:
                raise HTTPException(status_code=400, detail="Cannot delete the default assistant")
            # Orphan-safe: unbind tasks and sessions (existing code falls back to
            # owner defaults when crew_member_id is null).
            db.query(ScheduledTask).filter(ScheduledTask.crew_member_id == agent_id).update(
                {ScheduledTask.crew_member_id: None}, synchronize_session=False)
            db.query(DbSession).filter(DbSession.crew_member_id == agent_id).update(
                {DbSession.crew_member_id: None}, synchronize_session=False)
            db.delete(crew)
            db.commit()
            return {"deleted": True, "id": agent_id}
        finally:
            db.close()

    @router.post("/{agent_id}/duplicate")
    async def duplicate_agent(agent_id: str, request: Request):
        owner = _owner(request)
        db = SessionLocal()
        try:
            src = cs.find_agent(db, agent_id, owner)
            if not src:
                raise HTTPException(status_code=404, detail="Agent not found")
            max_sort = db.query(CrewMember).filter(CrewMember.owner == owner).count()
            copy = CrewMember(
                id=cs.new_agent_id(),
                owner=owner,
                name=f"{src.name} (copy)",
                avatar=src.avatar,
                user_name=src.user_name,
                personality=src.personality,
                model=src.model,
                endpoint_url=src.endpoint_url,
                greeting=src.greeting,
                enabled_tools=src.enabled_tools,
                description=getattr(src, "description", None),
                color=getattr(src, "color", None),
                category=getattr(src, "category", None),
                timezone=src.timezone,
                engine=getattr(src, "engine", "claude_code"),  # copy the source's engine pin (don't silently re-default)
                session_id=None,
                is_default_assistant=False,
                is_active=True,
                sort_order=max_sort,
                status=None,
            )
            db.add(copy)
            db.commit()
            db.refresh(copy)
            return {"agent": cs.crew_to_dict(copy)}
        finally:
            db.close()

    # ---- Conversational builder ----

    @router.post("/builder/start")
    async def builder_start(payload: BuilderStart, request: Request):
        owner = _owner(request)
        try:
            return agent_builder.start(owner, payload.seed_agent_id, payload.seed_template)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.post("/builder/{builder_id}/message")
    async def builder_message(builder_id: str, payload: BuilderMessage, request: Request):
        owner = _owner(request)
        try:
            return await agent_builder.step(owner, builder_id, payload.message)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.post("/builder/{builder_id}/commit")
    async def builder_commit(builder_id: str, request: Request):
        owner = _owner(request)
        try:
            return {"agent": agent_builder.commit(owner, builder_id)}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/{agent_id}/activity")
    async def agent_activity(agent_id: str, request: Request, limit: int = 50):
        """Recent task-run history for this agent (join TaskRun → ScheduledTask)."""
        owner = _owner(request)
        db = SessionLocal()
        try:
            if not cs.find_agent(db, agent_id, owner):
                raise HTTPException(status_code=404, detail="Agent not found")
            from core.database import TaskRun
            rows = (db.query(TaskRun, ScheduledTask)
                    .join(ScheduledTask, TaskRun.task_id == ScheduledTask.id)
                    .filter(ScheduledTask.owner == owner,
                            ScheduledTask.crew_member_id == agent_id)
                    .order_by(TaskRun.started_at.desc()).limit(limit).all())
            return {"runs": [{
                "id": r.id, "task_id": r.task_id, "task_name": t.name,
                "task_type": t.task_type or "llm", "status": r.status,
                "started_at": r.started_at.isoformat() + "Z" if r.started_at else None,
                "result": (r.result or r.error or "")[:400],
            } for (r, t) in rows]}
        finally:
            db.close()

    return router
