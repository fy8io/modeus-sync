"""Сборка .ics из JSON Modeus."""
from __future__ import annotations

from datetime import datetime, timezone

PRODID = "-//Modeus Sync//RU"
MAX_LINE = 73


def _escape(value: str) -> str:
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Складывает строку по 75 октетов (RFC 5545)."""
    encoded = line.encode("utf-8")
    if len(encoded) <= MAX_LINE:
        return line
    chunks = []
    current = b""
    limit = MAX_LINE
    for ch in line:
        b = ch.encode("utf-8")
        if len(current) + len(b) > limit:
            chunks.append(current)
            current = b
            limit = MAX_LINE - 1
        else:
            current += b
    chunks.append(current)
    return "\r\n ".join(c.decode("utf-8") for c in chunks)


def _utc(value: str) -> str:
    dt = datetime.fromisoformat(value)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _by_href(collection: dict) -> dict:
    """Индексирует элементы по id (уже есть) — оставлено для читаемости."""
    return collection


def build_ics(data: dict) -> str:
    events = data.get("events", [])
    emb = data.get("embedded", {})

    rooms = emb.get("rooms", {})
    event_rooms = emb.get("event-rooms", {})
    event_locations = emb.get("event-locations", {})
    attendees = emb.get("event-attendees", {})
    persons = emb.get("persons", {})
    course_units = emb.get("course-unit-realizations", {})

    # eventId -> комната (в ответе локации приходят прямо в event-rooms)
    room_for_event: dict[str, dict] = {}
    for er in event_rooms.values():
        links = er.get("_links") or {}
        ev_id = (links.get("event") or {}).get("href", "").strip("/")
        room_href = (links.get("room") or {}).get("href", "").strip("/")
        room = rooms.get(room_href)
        if ev_id and room:
            room_for_event[ev_id] = room
    # резервный путь через event-locations
    for loc in event_locations.values():
        ev_id = loc.get("eventId")
        href = (((loc.get("_links") or {}).get("event-rooms") or {}).get("href") or "").strip("/")
        er = event_rooms.get(href)
        if not er or not ev_id or ev_id in room_for_event:
            continue
        room_href = (((er.get("_links") or {}).get("room") or {}).get("href") or "").strip("/")
        room = rooms.get(room_href)
        if room:
            room_for_event[ev_id] = room

    # eventId -> [ФИО преподавателей]
    teachers_for_event: dict[str, list[str]] = {}
    for att in attendees.values():
        if att.get("roleId") != "TEACH":
            continue
        ev_id = (((att.get("_links") or {}).get("event") or {}).get("href") or "").strip("/")
        p_id = (((att.get("_links") or {}).get("person") or {}).get("href") or "").strip("/")
        person = persons.get(p_id)
        if ev_id and person:
            teachers_for_event.setdefault(ev_id, []).append(person.get("fullName", ""))

    # eventId -> дисциплина (полное и короткое название)
    course_for_event: dict[str, dict] = {}
    for ev in events:
        href = (((ev.get("_links") or {}).get("course-unit-realization") or {}).get("href") or "").strip("/")
        cu = course_units.get(href)
        if cu:
            course_for_event[ev["id"]] = cu

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:" + PRODID,
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Модеус",
        "X-WR-TIMEZONE:Europe/Moscow",
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    skipped = 0

    for ev in sorted(events, key=lambda e: e.get("start", "")):
        if (ev.get("holdingStatus") or {}).get("id") == "CANCELLED":
            skipped += 1
            continue

        name = ev.get("name") or "Занятие"
        subtitle = ev.get("nameShort") or ""
        cu = course_for_event.get(ev["id"]) or {}
        course_short = cu.get("nameShort") or cu.get("name") or ""
        course_full = cu.get("name") or ""
        summary = f"{course_short} — {name}" if course_short else name

        room = room_for_event.get(ev["id"])
        location = ""
        if room:
            building = (room.get("building") or {}).get("name") or ""
            location = f"{building} / {room.get('name', '')}".strip(" /")

        desc_parts = []
        if subtitle:
            desc_parts.append(subtitle)
        if course_full:
            desc_parts.append(course_full)
        teachers = teachers_for_event.get(ev["id"]) or []
        if teachers:
            desc_parts.append(", ".join(teachers))

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{ev['id']}@modeus.sfedu")
        lines.append(f"DTSTAMP:{stamp}")
        lines.append(f"DTSTART:{_utc(ev['start'])}")
        lines.append(f"DTEND:{_utc(ev['end'])}")
        lines.append("SUMMARY:" + _escape(summary))
        if location:
            lines.append("LOCATION:" + _escape(location))
        if desc_parts:
            lines.append("DESCRIPTION:" + _escape("\n".join(desc_parts)))
        lines.append("TRANSP:OPAQUE")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(ln) for ln in lines) + "\r\n"
