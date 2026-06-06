"""Live task-run event bus.

A scheduled task executed through the agent loop streams a rich event timeline
(thinking, tool calls, output) that used to be discarded. This module lets the
task scheduler PUBLISH those events to a per-run buffer so the Workspace console
can watch a run in real time and replay it on reconnect.

Unlike :mod:`src.agent_runs` (which DRAINS a generator), here the producer is
the consumer loop already running inside the scheduler, so the API is push-based:
``open_run`` → ``publish`` (many) → ``close_run``. Subscribers replay the buffer
from the start, then stream live until the run ends — identical replay semantics
to ``agent_runs.subscribe`` (reconnect-safe, multi-client).

Durability scope: in-memory; survives client disconnects but not a server
restart. Persisted ``TaskRun.steps`` is the durable record (see task_scheduler).
"""
import asyncio
import json
import logging
from typing import AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)


class _Run:
    __slots__ = ("buffer", "subscribers", "status", "evict_task")

    def __init__(self) -> None:
        self.buffer: list = []          # ordered SSE event strings (replay log)
        self.subscribers: set = set()   # one asyncio.Queue per connected client
        self.status: str = "running"    # running | done | error | stopped
        self.evict_task: Optional[asyncio.Task] = None


_RUNS: Dict[str, _Run] = {}

# How long a FINISHED run (and its replay buffer) is retained after the last
# subscriber disconnects, so a reconnect within the window can still replay.
_EVICT_GRACE_S = 180


def open_run(run_id: str) -> None:
    """Begin a live run. Idempotent — re-opening resets to a fresh buffer."""
    if not run_id:
        return
    prev = _RUNS.get(run_id)
    if prev and prev.evict_task and not prev.evict_task.done():
        prev.evict_task.cancel()
    _RUNS[run_id] = _Run()


def publish(run_id: str, ev: str) -> None:
    """Append one SSE event and fan it out to every live subscriber.

    Best-effort: never raises into the producer (the scheduler's event loop)."""
    run = _RUNS.get(run_id)
    if run is None:
        return
    try:
        run.buffer.append(ev)
        seq = len(run.buffer) - 1
        for q in list(run.subscribers):
            try:
                q.put_nowait((seq, ev))
            except Exception:
                pass
    except Exception:
        pass


def close_run(run_id: str, status: str = "done") -> None:
    """Mark a run terminal, push the end sentinel to subscribers, arm eviction.
    Idempotent — a second call on an already-terminal run is a no-op (avoids a
    duplicate [DONE] in the buffer and a re-armed eviction timer)."""
    run = _RUNS.get(run_id)
    if run is None:
        return
    if run.status != "running":
        return
    run.status = status if status in ("done", "error", "stopped") else "done"
    # Final [DONE] frame so a replaying client closes cleanly even if it never
    # received a live sentinel.
    try:
        run.buffer.append("data: [DONE]\n\n")
    except Exception:
        pass
    for q in list(run.subscribers):
        try:
            q.put_nowait((None, None))
        except Exception:
            pass
    _schedule_evict(run_id)


def _schedule_evict(run_id: str) -> None:
    """(Re)arm a grace-period eviction for a terminal run with no subscribers.
    Identity-checked so a reused run is never evicted by a stale timer."""
    run = _RUNS.get(run_id)
    if run is None:
        return
    if run.evict_task and not run.evict_task.done():
        run.evict_task.cancel()

    async def _evict(run_ref: _Run) -> None:
        try:
            await asyncio.sleep(_EVICT_GRACE_S)
        except asyncio.CancelledError:
            return
        cur = _RUNS.get(run_id)
        if cur is run_ref and cur.status != "running" and not cur.subscribers:
            _RUNS.pop(run_id, None)

    try:
        run.evict_task = asyncio.create_task(_evict(run))
    except RuntimeError:
        # No running loop (called from a sync context with no scheduler) —
        # the run stays until the next open_run/close_run reuses the slot.
        pass


def is_active(run_id: str) -> bool:
    r = _RUNS.get(run_id)
    return bool(r and r.status == "running")


def active_run_ids() -> List[str]:
    """run_ids currently streaming (status == running)."""
    return [rid for rid, r in list(_RUNS.items()) if r.status == "running"]


def get_status(run_id: str) -> Optional[str]:
    r = _RUNS.get(run_id)
    return r.status if r else None


async def subscribe(run_id: str) -> AsyncGenerator[str, None]:
    """Replay the run's buffer from the start, then stream live until it ends.
    Safe to call repeatedly (reconnect) and from multiple clients at once.

    If the run is unknown (never opened, or already evicted) the stream is empty
    bar a closing sentinel — the caller falls back to the persisted steps."""
    run = _RUNS.get(run_id)
    if run is None:
        yield "data: [DONE]\n\n"
        return
    q: asyncio.Queue = asyncio.Queue()
    run.subscribers.add(q)            # register BEFORE replaying so nothing is missed
    if run.evict_task and not run.evict_task.done():
        run.evict_task.cancel()
    try:
        next_seq = 0
        while next_seq < len(run.buffer):
            yield run.buffer[next_seq]
            next_seq += 1
        if run.status != "running":
            return
        while True:
            seq, ev = await q.get()
            if seq is None:            # end sentinel
                while next_seq < len(run.buffer):   # flush any tail the sentinel raced
                    yield run.buffer[next_seq]
                    next_seq += 1
                break
            if seq >= next_seq:        # skip events already replayed from the buffer
                yield ev
                next_seq = seq + 1
    finally:
        run.subscribers.discard(q)
        if not run.subscribers and run.status != "running":
            _schedule_evict(run_id)
