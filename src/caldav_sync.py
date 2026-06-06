"""Remote calendar → local SQLite sync (CalDAV account + .ics feeds).

The Settings UI lets users save CalDAV credentials, but the original
sync path was removed when calendar storage was migrated to SQLite.
This module re-wires that gap as a one-way pull (remote → local),
called on calendar open and from a periodic scheduler loop.

Design notes:
- We use the `caldav` lib so PROPFIND discovery + REPORT XML work
  across Radicale / Nextcloud / Apple / Fastmail without us
  reinventing the protocol. It's pure Python.
- The lib is synchronous; we run it in a threadpool via
  `asyncio.to_thread` so the FastAPI event loop stays free.
- Each remote calendar maps to one local `CalendarCal` row with
  `source="caldav"` and `id` = a stable hash of the remote URL so
  re-syncs idempotently target the same row.
- Events upsert by VEVENT UID (kept as the local `uid`). Local
  CalDAV-sourced events not seen in the latest pull are deleted so
  remote deletions propagate.
- Datetimes are converted to UTC and the row is flagged `is_utc=True`
  so the serializer adds the Z suffix and the frontend renders in the
  user's local TZ correctly.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Pull window: 90 days back, 1 year forward. Keeps the REPORT cheap and
# matches what the calendar UI typically renders. Far-future recurring
# events still come through via RRULE expansion on the frontend.
_LOOKBACK_DAYS = 90
_LOOKAHEAD_DAYS = 365


def _stable_cal_id(remote_url: str) -> str:
    """Deterministic local id for a remote CalDAV calendar — same URL
    always maps to the same local row across restarts and re-syncs."""
    h = hashlib.sha256(remote_url.encode("utf-8")).hexdigest()[:24]
    return f"caldav-{h}"


def _to_utc_naive(dt):
    """CalDAV datetimes can be tz-aware (with a TZID) or naive. The DB
    column is naive but we set is_utc=True so the serializer adds Z.
    All-day events stay as date and get widened to datetime here."""
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None), False
        return dt, False  # naive → treat as local
    # date-only (all-day)
    return datetime(dt.year, dt.month, dt.day), True


def _stable_ics_cal_id(feed_url: str) -> str:
    """Deterministic local id for an .ics subscription feed — same URL
    always maps to the same local row across restarts and re-syncs."""
    h = hashlib.sha256(feed_url.encode("utf-8")).hexdigest()[:24]
    return f"ics-{h}"


def _upsert_vevent(db, comp, calendar_id: str, pending: dict):
    """Upsert one parsed VEVENT component into `calendar_id`. Returns the
    event's UID, or None when the component is unusable (no DTSTART).
    `pending` tracks rows added to the session but not yet committed so
    duplicate UIDs within the same batch are updated, not re-inserted
    (which would violate the UNIQUE constraint on commit)."""
    from core.database import CalendarEvent

    uid_val = str(comp.get("uid", "")) or str(uuid.uuid4())
    dtstart_p = comp.get("dtstart")
    if not dtstart_p:
        return None
    start_dt, all_day = _to_utc_naive(dtstart_p.dt)

    dtend_p = comp.get("dtend")
    if dtend_p:
        end_dt, _ = _to_utc_naive(dtend_p.dt)
    elif all_day:
        end_dt = start_dt + timedelta(days=1)
    else:
        end_dt = start_dt + timedelta(hours=1)

    # is_utc reflects whether the source carried a TZ we converted
    # from. All-day = no TZ semantics.
    row_is_utc = (
        not all_day
        and isinstance(dtstart_p.dt, datetime)
        and dtstart_p.dt.tzinfo is not None
    )

    summary = str(comp.get("summary", ""))
    description = str(comp.get("description", ""))
    location = str(comp.get("location", ""))
    rrule = (
        comp.get("rrule").to_ical().decode()
        if comp.get("rrule")
        else ""
    )

    existing = pending.get(uid_val) or db.query(CalendarEvent).filter(
        CalendarEvent.uid == uid_val,
    ).first()
    if existing:
        existing.calendar_id = calendar_id
        existing.summary = summary
        existing.description = description
        existing.location = location
        existing.dtstart = start_dt
        existing.dtend = end_dt
        existing.all_day = all_day
        existing.is_utc = row_is_utc
        existing.rrule = rrule
    else:
        new_ev = CalendarEvent(
            uid=uid_val,
            calendar_id=calendar_id,
            summary=summary,
            description=description,
            location=location,
            dtstart=start_dt,
            dtend=end_dt,
            all_day=all_day,
            is_utc=row_is_utc,
            rrule=rrule,
        )
        db.add(new_ev)
        pending[uid_val] = new_ev
    return uid_val


def _sync_blocking(owner: str, url: str, username: str, password: str) -> dict:
    """The actual sync — synchronous, intended to run in a threadpool.
    Returns counts: {calendars, events, deleted, errors}."""
    # Lazy imports so a missing `caldav` dep doesn't break app startup —
    # the integrations form still works, sync just no-ops with an error.
    import caldav
    from caldav.lib.error import AuthorizationError, NotFoundError
    from core.database import CalendarCal, CalendarEvent, SessionLocal

    result = {"calendars": 0, "events": 0, "deleted": 0, "errors": []}

    client = caldav.DAVClient(url=url, username=username, password=password)

    # Discovery: try principal → calendars first; if the server doesn't
    # support discovery (or the URL points directly at a calendar), fall
    # back to treating the URL as a single calendar.
    calendars = []
    try:
        principal = client.principal()
        calendars = principal.calendars()
    except (AuthorizationError, NotFoundError) as e:
        result["errors"].append(f"Discovery failed: {e}")
        return result
    except Exception as e:
        logger.info(f"CalDAV principal discovery failed, trying URL as calendar: {e}")
        try:
            calendars = [client.calendar(url=url)]
        except Exception as e2:
            result["errors"].append(f"Could not open URL as calendar: {e2}")
            return result

    if not calendars:
        try:
            calendars = [client.calendar(url=url)]
        except Exception as e:
            result["errors"].append(f"No calendars and URL fallback failed: {e}")
            return result

    start = datetime.utcnow() - timedelta(days=_LOOKBACK_DAYS)
    end = datetime.utcnow() + timedelta(days=_LOOKAHEAD_DAYS)

    db = SessionLocal()
    try:
        for remote_cal in calendars:
            try:
                remote_url = str(remote_cal.url)
                cal_id = _stable_cal_id(remote_url)
                display_name = (remote_cal.name or "").strip() or "CalDAV"

                local_cal = db.query(CalendarCal).filter(
                    CalendarCal.id == cal_id,
                    CalendarCal.owner == owner,
                ).first()
                if not local_cal:
                    local_cal = CalendarCal(
                        id=cal_id,
                        owner=owner,
                        name=display_name,
                        color="#5b8abf",
                        source="caldav",
                    )
                    db.add(local_cal)
                    db.commit()
                else:
                    # Refresh the display name if the user renamed it
                    # remotely; preserve any local color override.
                    if local_cal.name != display_name:
                        local_cal.name = display_name
                        db.commit()
                result["calendars"] += 1

                # Fetch events in window. `date_search` returns CalendarObject
                # resources; each may contain one VEVENT (most servers) or
                # several (rare).
                from icalendar import Calendar as iCal

                seen_uids = set()
                # Track events added to the session but not yet committed so
                # duplicate UIDs within the same batch are updated, not re-inserted
                # (which would violate the UNIQUE constraint on commit).
                pending: dict = {}
                try:
                    objs = remote_cal.date_search(start=start, end=end, expand=False)
                except Exception as e:
                    result["errors"].append(f"{display_name}: date_search failed ({e})")
                    continue

                for obj in objs:
                    try:
                        ical = iCal.from_ical(obj.data)
                    except Exception as e:
                        result["errors"].append(f"{display_name}: parse failed ({e})")
                        continue

                    for comp in ical.walk():
                        if comp.name != "VEVENT":
                            continue
                        uid_val = _upsert_vevent(db, comp, local_cal.id, pending)
                        if uid_val:
                            seen_uids.add(uid_val)
                            result["events"] += 1
                db.commit()

                # Prune locally-cached CalDAV events that vanished
                # upstream (only within our sync window — events outside
                # the window aren't in `objs`, so we'd false-delete them).
                stale = db.query(CalendarEvent).filter(
                    CalendarEvent.calendar_id == local_cal.id,
                    CalendarEvent.dtstart >= start,
                    CalendarEvent.dtstart <= end,
                    ~CalendarEvent.uid.in_(seen_uids) if seen_uids else CalendarEvent.uid.isnot(None),
                ).all()
                for ev in stale:
                    db.delete(ev)
                result["deleted"] += len(stale)
                db.commit()
            except Exception as e:
                logger.exception("CalDAV sync failed for one calendar")
                result["errors"].append(str(e)[:200])
                db.rollback()
    finally:
        db.close()

    return result


def _sync_ics_blocking(owner: str, subs: list) -> dict:
    """Pull each subscribed .ics feed into its own local calendar.
    Unlike CalDAV there's no date-range REPORT — the feed IS the whole
    calendar — so we upsert every VEVENT and prune anything that
    disappeared from the feed (no window concerns)."""
    from icalendar import Calendar as iCal
    from core.database import CalendarCal, CalendarEvent, SessionLocal

    result = {"calendars": 0, "events": 0, "deleted": 0, "errors": []}
    db = SessionLocal()
    try:
        for sub in subs:
            feed_url = (sub.get("url") or "").strip()
            if not feed_url:
                continue
            label = (sub.get("name") or "").strip()
            try:
                import httpx
                r = httpx.get(feed_url, timeout=20.0, follow_redirects=True)
                r.raise_for_status()
                ical = iCal.from_ical(r.text)
            except Exception as e:
                result["errors"].append(
                    f"{label or feed_url}: fetch/parse failed ({e})"[:200])
                continue

            cal_id = _stable_ics_cal_id(feed_url)
            # User-given name wins; else the feed's self-declared name.
            display_name = (
                label
                or str(ical.get("X-WR-CALNAME", "")).strip()
                or "Subscription"
            )
            local_cal = db.query(CalendarCal).filter(
                CalendarCal.id == cal_id,
                CalendarCal.owner == owner,
            ).first()
            if not local_cal:
                local_cal = CalendarCal(
                    id=cal_id,
                    owner=owner,
                    name=display_name,
                    color="#5b8abf",
                    source="ics",
                )
                db.add(local_cal)
                db.commit()
            elif local_cal.name != display_name:
                local_cal.name = display_name
                db.commit()
            result["calendars"] += 1

            seen_uids = set()
            pending: dict = {}
            for comp in ical.walk():
                if comp.name != "VEVENT":
                    continue
                uid_val = _upsert_vevent(db, comp, local_cal.id, pending)
                if uid_val:
                    seen_uids.add(uid_val)
                    result["events"] += 1
            db.commit()

            # The feed is the complete source of truth — any local event
            # no longer present in it was deleted upstream.
            stale_q = db.query(CalendarEvent).filter(
                CalendarEvent.calendar_id == local_cal.id)
            if seen_uids:
                stale_q = stale_q.filter(~CalendarEvent.uid.in_(seen_uids))
            stale = stale_q.all()
            for ev in stale:
                db.delete(ev)
            result["deleted"] += len(stale)
            db.commit()
    except Exception as e:
        logger.exception("ICS subscription sync failed")
        result["errors"].append(str(e)[:200])
        db.rollback()
    finally:
        db.close()

    return result


async def sync_caldav(owner: str) -> dict:
    """Pull every remote calendar source (the CalDAV account plus any
    .ics feed subscriptions) into the local DB for `owner`. Returns
    merged counts + errors. Loads config from the user's prefs; no-ops
    with a clear error if nothing is configured."""
    from routes.prefs_routes import _load_for_user

    prefs = _load_for_user(owner) or {}
    cfg = prefs.get("caldav", {}) or {}
    url = (cfg.get("url") or "").strip()
    user = (cfg.get("username") or "").strip()
    pw = cfg.get("password") or ""
    subs = [s for s in (prefs.get("ics_subs") or [])
            if (s.get("url") or "").strip()]

    caldav_ready = bool(url and user and pw)
    if not caldav_ready and not subs:
        return {
            "calendars": 0, "events": 0, "deleted": 0,
            "errors": ["No calendar sources configured"],
        }

    totals = {"calendars": 0, "events": 0, "deleted": 0, "errors": []}

    def _merge(r: dict):
        for k in ("calendars", "events", "deleted"):
            totals[k] += r.get(k, 0)
        totals["errors"].extend(r.get("errors") or [])

    if caldav_ready:
        try:
            _merge(await asyncio.to_thread(_sync_blocking, owner, url, user, pw))
        except Exception as e:
            logger.exception("CalDAV sync raised")
            _merge({"errors": [str(e)[:200]]})
    if subs:
        try:
            _merge(await asyncio.to_thread(_sync_ics_blocking, owner, subs))
        except Exception as e:
            logger.exception("ICS subscription sync raised")
            _merge({"errors": [str(e)[:200]]})
    return totals
