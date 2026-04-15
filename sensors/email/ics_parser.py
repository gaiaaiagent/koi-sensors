"""
ICS Calendar Parser for Email Sensor

Parses VCALENDAR payloads from email attachments into structured event dicts
suitable for storage in koi_memories with source_sensor='ics-event'.
"""

import hashlib
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytz
from icalendar import Calendar

logger = logging.getLogger(__name__)

VANCOUVER = pytz.timezone('America/Vancouver')


def _to_utc_datetime(value: Any) -> Optional[datetime]:
    """Normalize an icalendar date/datetime value to aware UTC datetime.

    Handles three cases:
      - DATETIME with TZID: convert via tzinfo to UTC
      - DATETIME floating (no tzinfo): localize to America/Vancouver, then UTC.
        For DST gap/fold, fall back to is_dst=True / is_dst=False respectively.
      - DATE (date-only): treat as midnight UTC
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc)
        try:
            localized = VANCOUVER.localize(value, is_dst=None)
        except pytz.exceptions.NonExistentTimeError:
            localized = VANCOUVER.localize(value, is_dst=True)
        except pytz.exceptions.AmbiguousTimeError:
            localized = VANCOUVER.localize(value, is_dst=False)
        return localized.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 0, 0, 0, tzinfo=timezone.utc)
    return None


def _normalize_dtend(
    dtstart_raw: Any, dtend_raw: Any, duration_raw: Any, dtstart_utc: Optional[datetime]
) -> Optional[datetime]:
    """Resolve DTEND with DURATION/DATE-only fallbacks per RFC 5545 + plan rules."""
    if dtend_raw is not None:
        dtend_utc = _to_utc_datetime(dtend_raw)
        if isinstance(dtstart_raw, date) and not isinstance(dtstart_raw, datetime):
            # RFC 5545: DTEND for DATE is exclusive; subtract 1 second
            if dtend_utc is not None:
                dtend_utc = dtend_utc - timedelta(seconds=1)
        return dtend_utc

    if duration_raw is not None and dtstart_utc is not None:
        try:
            if isinstance(duration_raw, timedelta):
                return dtstart_utc + duration_raw
            return dtstart_utc + duration_raw.dt
        except Exception:
            pass

    if dtstart_utc is None:
        return None

    if isinstance(dtstart_raw, date) and not isinstance(dtstart_raw, datetime):
        return dtstart_utc + timedelta(hours=23, minutes=59, seconds=59)
    return dtstart_utc + timedelta(hours=1)


def _extract_attendees(vevent) -> List[str]:
    """Extract attendee email addresses (strip 'mailto:' prefix)."""
    attendees = []
    raw = vevent.get('ATTENDEE')
    if raw is None:
        return attendees
    items = raw if isinstance(raw, list) else [raw]
    for item in items:
        val = str(item).strip()
        if val.lower().startswith('mailto:'):
            val = val[7:]
        if val:
            attendees.append(val)
    return attendees


def _extract_rrule_text(vevent) -> Optional[str]:
    """Build a human-readable description of RRULE (no instance expansion)."""
    rrule = vevent.get('RRULE')
    if rrule is None:
        return None
    try:
        freq = rrule.get('FREQ', [''])[0] if hasattr(rrule, 'get') else ''
        interval = rrule.get('INTERVAL', [1])[0] if hasattr(rrule, 'get') else 1
        byday = rrule.get('BYDAY', []) if hasattr(rrule, 'get') else []
        parts = []
        if freq:
            parts.append(f"Repeats {freq.lower()}")
        if interval and int(interval) > 1:
            parts.append(f"every {interval} {freq.lower()}s")
        if byday:
            parts.append(f"on {','.join(str(d) for d in byday)}")
        return ' '.join(parts) if parts else str(rrule)
    except Exception:
        try:
            return str(rrule)
        except Exception:
            return None


def _compute_event_rid(provider: str, uid: str) -> str:
    digest = hashlib.sha256(f"{provider}:{uid}".encode()).hexdigest()[:16]
    return f"orn:ics.event:{digest}"


def _synthetic_uid(email_rid: str, att_index: int, dtstart: Any, vevent_index: int) -> str:
    raw = f"{email_rid}{att_index}{dtstart}{vevent_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _parse_vevent(
    vevent, provider: str, email_rid: str, att_index: int, vevent_index: int,
    calendar_method: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Parse a single VEVENT. Returns None for intentional skips (no had_parse_errors signal).

    Raises on true parse errors (malformed, missing required fields for non-cancel).
    """
    if vevent.get('RECURRENCE-ID') is not None:
        logger.info("ICS parser: skipping VEVENT with RECURRENCE-ID")
        return None

    uid_raw = vevent.get('UID')
    uid = str(uid_raw).strip() if uid_raw is not None else ''

    method = str(calendar_method).strip().upper() if calendar_method else None
    status_raw = vevent.get('STATUS')
    status = str(status_raw).strip().lower() if status_raw is not None else None
    if method == 'CANCEL' or (status == 'cancelled'):
        status = 'cancelled'

    if not uid:
        if method == 'CANCEL':
            logger.info("ICS parser: skipping CANCEL VEVENT without UID")
            return None
        dtstart_probe = vevent.get('DTSTART')
        if dtstart_probe is None:
            raise ValueError("VEVENT has neither UID nor DTSTART — cannot identify event")
        uid = _synthetic_uid(email_rid, att_index, dtstart_probe.dt, vevent_index)

    dtstart_raw = vevent.get('DTSTART')
    dtend_raw = vevent.get('DTEND')
    duration_raw = vevent.get('DURATION')

    dtstart_dt = dtstart_raw.dt if dtstart_raw is not None else None
    dtstart_utc = _to_utc_datetime(dtstart_dt)
    dtend_dt = dtend_raw.dt if dtend_raw is not None else None
    duration_val = duration_raw.dt if duration_raw is not None else None
    dtend_utc = _normalize_dtend(dtstart_dt, dtend_dt, duration_val, dtstart_utc)

    summary = str(vevent.get('SUMMARY', '')).strip() or ''
    location = str(vevent.get('LOCATION', '')).strip() or None
    organizer_raw = vevent.get('ORGANIZER')
    organizer = None
    if organizer_raw is not None:
        organizer = str(organizer_raw).strip()
        if organizer.lower().startswith('mailto:'):
            organizer = organizer[7:]
    description = str(vevent.get('DESCRIPTION', '')).strip() or None
    attendees = _extract_attendees(vevent)
    rrule_text = _extract_rrule_text(vevent)

    sequence_raw = vevent.get('SEQUENCE')
    sequence = int(sequence_raw) if sequence_raw is not None else None

    dtstamp_raw = vevent.get('DTSTAMP')
    dtstamp_utc = _to_utc_datetime(dtstamp_raw.dt) if dtstamp_raw is not None else None
    dtstamp = dtstamp_utc.isoformat() if dtstamp_utc is not None else None

    event_rid = _compute_event_rid(provider, uid)

    return {
        'summary': summary or uid,
        'dtstart_utc': dtstart_utc,
        'dtend_utc': dtend_utc,
        'location': location,
        'organizer': organizer,
        'attendees': attendees,
        'description': description,
        'uid': uid,
        'rrule_text': rrule_text,
        'status': status,
        'method': method,
        'sequence': sequence,
        'dtstamp': dtstamp,
        'event_rid': event_rid,
    }


def parse_ics_bytes(
    payload: bytes, provider: str, email_rid: str, att_index: int
) -> Tuple[List[Dict[str, Any]], bool]:
    """Parse an ICS payload into a list of event dicts.

    Returns:
        (events, had_parse_errors)
        - events: list of successfully parsed VEVENT dicts (empty if all skipped/failed)
        - had_parse_errors: True iff any VEVENT (or VCALENDAR itself) raised during parse.
          Intentional skips (RECURRENCE-ID; METHOD:CANCEL with no UID) do NOT set this.
    """
    events: List[Dict[str, Any]] = []
    had_parse_errors = False

    try:
        cal = Calendar.from_ical(payload)
    except Exception as e:
        logger.error(f"VCALENDAR parse failure: {e}")
        return [], True

    method_raw = cal.get('METHOD') if hasattr(cal, 'get') else None
    calendar_method = str(method_raw).strip() if method_raw is not None else None

    vevents = list(cal.walk('VEVENT'))
    for idx, vevent in enumerate(vevents):
        try:
            parsed = _parse_vevent(vevent, provider, email_rid, att_index, idx, calendar_method)
            if parsed is not None:
                events.append(parsed)
        except Exception as e:
            logger.warning(f"VEVENT parse error (idx={idx}): {e}")
            had_parse_errors = True

    return events, had_parse_errors


def _fmt_dt(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.strftime('%Y-%m-%d %H:%M UTC')


def format_event_text(event: Dict[str, Any]) -> str:
    """Render an event dict as human-readable text for koi_memories.content.text.

    Gracefully omits null fields (e.g. cancelled events without DTSTART/DTEND).
    """
    summary = event.get('summary') or event.get('uid') or 'Untitled'
    status = event.get('status')

    if status == 'cancelled' and not event.get('dtstart_utc'):
        head = f"Cancelled Calendar Event: {summary}"
    else:
        head = f"Calendar Event: {summary}"

    lines = [head]
    dtstart_s = _fmt_dt(event.get('dtstart_utc'))
    dtend_s = _fmt_dt(event.get('dtend_utc'))
    if dtstart_s and dtend_s:
        lines.append(f"Date: {dtstart_s} – {dtend_s}")
    elif dtstart_s:
        lines.append(f"Date: {dtstart_s}")
    if event.get('location'):
        lines.append(f"Location: {event['location']}")
    if event.get('organizer'):
        lines.append(f"Organizer: {event['organizer']}")
    if event.get('attendees'):
        lines.append(f"Attendees: {', '.join(event['attendees'])}")
    if status:
        lines.append(f"Status: {status}")
    if event.get('rrule_text'):
        lines.append(event['rrule_text'])
    if event.get('description'):
        lines.append(f"Description: {event['description']}")
    return '\n'.join(lines)
