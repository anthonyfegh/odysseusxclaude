"""Per-agent on-disk workspace + path confinement.

Each agent (CrewMember) gets a real folder at ``data/agents/<crew_member_id>/``.
When a run executes AS that agent — a chat-bound session or a scheduled task —
its file tools are rooted in that folder: ``write_file``/``read_file`` resolve
relative paths under it and reject any path that escapes it, and ``bash``/
``python`` run with it as the working directory. The folder is the agent's
sandbox and the place its authored files live, surfaced by the Workspace
console.

The path is derived from the agent id, so there is no DB column and no
migration; the directory is created lazily on first use.

Confinement caveat: rooting + path checks confine the *file tools*. The
``cwd`` we set for ``bash``/``python`` only changes the default working
directory — it does NOT jail the subprocess, which can still open an absolute
path. True process isolation (container / restricted user) is out of scope; the
shell security posture is unchanged from before this module existed.
"""

import os
from typing import Optional

from src.constants import AGENT_WORKSPACES_DIR


class WorkspaceEscape(ValueError):
    """Raised when a path would resolve outside the agent's workspace root."""


def workspace_root(crew_member_id: str) -> str:
    """Absolute path to the agent's workspace folder, created on demand."""
    if not crew_member_id:
        raise ValueError("crew_member_id required for a workspace root")
    root = os.path.realpath(os.path.join(AGENT_WORKSPACES_DIR, str(crew_member_id)))
    os.makedirs(root, exist_ok=True)
    return root


def _within(base: str, candidate: str) -> bool:
    """True if ``candidate`` is ``base`` or lives inside it."""
    try:
        return os.path.commonpath([base, candidate]) == base
    except ValueError:
        # Different drives (Windows) or mixed abs/rel — treat as outside.
        return False


def resolve_in_workspace(root: str, path: str) -> str:
    """Resolve ``path`` to an absolute path confined to the workspace ``root``.

    Relative paths are rooted at the workspace; absolute paths are taken as
    given and must already fall inside it. Empty / ``.`` / ``/`` mean the root
    itself. Raises :class:`WorkspaceEscape` for anything that would land outside
    (``..``, a symlink that points out, or an absolute path outside the root).

    For writes the leaf may not exist yet, so confinement is checked against the
    realpath of the *parent* directory, then the basename is rejoined; a final
    realpath of the leaf catches a symlinked leaf pointing outward.
    """
    base = os.path.realpath(root)
    raw = (path or "").strip()
    if raw in ("", ".", "/", "./"):
        return base
    joined = raw if os.path.isabs(raw) else os.path.join(base, raw)
    norm = os.path.normpath(joined)
    parent = os.path.realpath(os.path.dirname(norm) or base)
    if not _within(base, parent):
        raise WorkspaceEscape(f"path escapes workspace: {path}")
    resolved = os.path.join(parent, os.path.basename(norm))
    if not _within(base, os.path.realpath(resolved)):
        raise WorkspaceEscape(f"path escapes workspace: {path}")
    return resolved
