"""Shared CrewMember (agent) helpers used by both the single-assistant routes
and the multi-agent manager (CRUD + chat binding).

Keep all crew serialization / field-application / resolution logic here so the
assistant router and the /api/agents router never diverge.
"""

import json
import uuid
from typing import Any, Dict, List, Optional

from core.database import SessionLocal, CrewMember, ModelEndpoint
from core.database import Session as DbSession


# Tools that grant the agent the ability to send mail on the user's behalf.
EMAIL_TOOLS = {"send_email", "reply_to_email"}


def new_agent_id() -> str:
    return uuid.uuid4().hex


def parse_enabled_tools(raw: Optional[str]) -> List[str]:
    """Return the agent's enabled-tool list. Empty list == unrestricted ("all"
    or unset). Mirrors how the task scheduler interprets enabled_tools."""
    if not raw or raw == "all":
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except Exception:
        return []


def crew_to_dict(c: CrewMember) -> Dict[str, Any]:
    """Serialize an agent for the API. Superset of the assistant settings shape
    (additive keys are ignored by the existing assistant UI)."""
    tools = parse_enabled_tools(c.enabled_tools)
    return {
        "id": c.id,
        "name": c.name,
        "avatar": c.avatar,
        "user_name": getattr(c, "user_name", None),
        "personality": c.personality,
        "description": getattr(c, "description", None),
        "model": c.model,
        "endpoint_url": c.endpoint_url,
        "greeting": c.greeting,
        "enabled_tools": tools,
        "session_id": c.session_id,
        "is_default_assistant": bool(c.is_default_assistant),
        "timezone": c.timezone,
        "color": getattr(c, "color", None),
        "category": getattr(c, "category", None),
        "status": getattr(c, "status", None),
        "sort_order": c.sort_order or 0,
        "is_active": bool(c.is_active),
        "allow_autonomous_email": any(t in EMAIL_TOOLS for t in tools),
        "engine": getattr(c, "engine", None) or "legacy",
        "claude_session_id": getattr(c, "claude_session_id", None),
    }


def get_or_create_agent_session(db, crew: CrewMember, session_manager=None) -> str:
    """Return the agent's single ONGOING Odysseus chat session id, creating it if
    absent. Under the claude_code engine each agent has exactly one eternal chat
    (CrewMember.session_id) that holds its full permanent transcript; this is the
    one front-door for both interactive chat and scheduled tasks."""
    from datetime import datetime
    if crew.session_id:
        s = db.query(DbSession).filter(
            DbSession.id == crew.session_id, DbSession.archived == False).first()
        if s:
            return s.id
    sid = uuid.uuid4().hex
    s = DbSession(
        id=sid, name=crew.name, endpoint_url=(crew.endpoint_url or ""),
        model=(crew.model or ""), owner=crew.owner, crew_member_id=crew.id,
        archived=False, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    db.add(s)
    crew.session_id = sid
    db.commit()
    if session_manager is not None:
        try:
            session_manager.sessions[sid] = session_manager._db_to_session_meta(s)
        except Exception:
            pass
    return sid


# Sentinel so "field present and set to None/empty" is distinguishable from
# "field not provided". Callers pass a dict of ONLY the fields they want changed.
def apply_crew_fields(crew_db: CrewMember, fields: Dict[str, Any]) -> None:
    """Apply scalar agent fields from a dict of present keys. Used by both the
    assistant PATCH and the /api/agents create/update paths."""
    if "name" in fields and fields["name"] is not None:
        crew_db.name = (fields["name"].strip() or crew_db.name)
    for key in ("avatar", "personality", "greeting", "user_name", "description", "color", "category"):
        if key in fields and fields[key] is not None:
            setattr(crew_db, key, fields[key])
    for key in ("model", "endpoint_url", "timezone"):
        if key in fields and fields[key] is not None:
            setattr(crew_db, key, (fields[key] or None))
    # Reasoning engine flip (phased Claude Code rollout). Only valid values.
    if fields.get("engine") in ("legacy", "claude_code"):
        crew_db.engine = fields["engine"]

    # Tool list: explicit list, the literal "all", or the convenience email toggle.
    if "enabled_tools" in fields and fields["enabled_tools"] is not None:
        et = fields["enabled_tools"]
        crew_db.enabled_tools = "all" if et == "all" else json.dumps(list(et))
    if fields.get("allow_autonomous_email") is not None:
        existing = parse_enabled_tools(crew_db.enabled_tools)
        if fields["allow_autonomous_email"]:
            for t in EMAIL_TOOLS:
                if t not in existing:
                    existing.append(t)
        else:
            existing = [t for t in existing if t not in EMAIL_TOOLS]
        crew_db.enabled_tools = json.dumps(existing)


def find_agent(db, agent_id: str, owner: Optional[str]) -> Optional[CrewMember]:
    """Owner-checked single-agent fetch (None if missing or cross-owner)."""
    if not agent_id:
        return None
    crew = db.query(CrewMember).filter(CrewMember.id == agent_id).first()
    if not crew:
        return None
    if owner and crew.owner and crew.owner != owner:
        return None
    return crew


def default_assistant_id(db, owner: Optional[str]) -> Optional[str]:
    """The id of this owner's default-assistant CrewMember, or None if they don't
    have one yet. Used to attribute otherwise-unassigned tasks to the assistant."""
    if not owner:
        return None
    crew = (db.query(CrewMember)
            .filter(CrewMember.owner == owner,
                    CrewMember.is_default_assistant == True)  # noqa: E712
            .first())
    return crew.id if crew else None


def list_agents(db, owner: str) -> List[CrewMember]:
    """All of this owner's real agents (not drafts), default assistant first."""
    rows = db.query(CrewMember).filter(
        CrewMember.owner == owner,
        (CrewMember.status == None) | (CrewMember.status != "draft"),  # noqa: E711
    ).all()
    rows.sort(key=lambda c: (0 if c.is_default_assistant else 1, c.sort_order or 0, (c.name or "").lower()))
    return rows


def validate_endpoint_url(db, endpoint_url: Optional[str], owner: Optional[str]) -> bool:
    """True when endpoint_url is empty (→ resolver picks the default sidecar) or
    matches an enabled ModelEndpoint visible to this owner. Enforces that agents
    only ever point at a configured endpoint (the claude -p sidecar by default),
    never an arbitrary/direct API URL."""
    if not endpoint_url:
        return True
    q = db.query(ModelEndpoint).filter(
        ModelEndpoint.base_url == endpoint_url,
        ModelEndpoint.is_enabled == True,  # noqa: E712
    )
    for ep in q.all():
        if ep.owner is None or ep.owner == owner:
            return True
    return False


def resolve_session_crew(session_id: Optional[str], owner: Optional[str]) -> Optional[CrewMember]:
    """Resolve the agent bound to a chat session (sessions.crew_member_id).

    Returns a detached CrewMember (loaded columns stay accessible) or None when
    the session is unbound / the agent is a draft / cross-owner — in which case
    the chat keeps its current (pre-agent) behavior.
    """
    if not session_id:
        return None
    db = SessionLocal()
    try:
        sess = db.query(DbSession).filter(DbSession.id == session_id).first()
        crew_id = getattr(sess, "crew_member_id", None) if sess else None
        if not crew_id:
            return None
        crew = db.query(CrewMember).filter(CrewMember.id == crew_id).first()
        if not crew:
            return None
        if owner and crew.owner and crew.owner != owner:
            return None
        if getattr(crew, "status", None) == "draft":
            return None
        db.expunge(crew)  # keep loaded attributes usable after close
        return crew
    finally:
        db.close()
