"""Данные для сайта посещаемости: обогащённые занятия + архив.

Modeus отдаёт события только за последние недели, поэтому всё, что когда-либо
встречалось, складывается в архив. В облаке архив читается из gist
(schedule.json), локально может храниться в history.json.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

HISTORY_DAYS = 400


def _link(obj: dict, name: str) -> str:
    return ((obj.get("_links") or {}).get(name) or {}).get("href", "").strip("/")


def _course_short(ev: dict, course_units: dict) -> str:
    cu = course_units.get(_link(ev, "course-unit-realization")) or {}
    return (cu.get("nameShort") or cu.get("name") or ev.get("nameShort") or "").strip().lower()


def drop_excluded(data: dict, names) -> dict:
    """Убирает занятия по списку коротких имён дисциплин (заглушки и т.п.)."""
    ex = {n.strip().lower() for n in (names or []) if n and n.strip()}
    if not ex:
        return data
    course_units = data.get("embedded", {}).get("course-unit-realizations", {})
    events = data.get("events", [])
    kept = [e for e in events if _course_short(e, course_units) not in ex]
    if len(kept) == len(events):
        return data
    return {**data, "events": kept}


def enrich(data: dict) -> list[dict]:
    """Превращает ответ API в плоский список занятий."""
    events = data.get("events", [])
    emb = data.get("embedded", {})

    rooms = emb.get("rooms", {})
    course_units = emb.get("course-unit-realizations", {})
    persons = emb.get("persons", {})

    room_for_event: dict[str, dict] = {}
    for er in emb.get("event-rooms", {}).values():
        ev_id = _link(er, "event")
        room = rooms.get(_link(er, "room"))
        if ev_id and room:
            room_for_event[ev_id] = room

    teachers: dict[str, list[str]] = {}
    for att in emb.get("event-attendees", {}).values():
        if att.get("roleId") != "TEACH":
            continue
        ev_id = _link(att, "event")
        person = persons.get(_link(att, "person"))
        if ev_id and person:
            name = person.get("fullName", "")
            if name:
                teachers.setdefault(ev_id, []).append(name)

    out: list[dict] = []
    for ev in events:
        ev_id = ev.get("id")
        if not ev_id:
            continue
        cu = course_units.get(_link(ev, "course-unit-realization")) or {}
        room = room_for_event.get(ev_id) or {}
        out.append(
            {
                "id": ev_id,
                "start": ev.get("start", ""),
                "end": ev.get("end", ""),
                "type": ev.get("typeId") or "",
                "status": (ev.get("holdingStatus") or {}).get("id") or "DRAFT",
                "title": ev.get("name") or "",
                "subject_id": cu.get("id") or _link(ev, "course-unit-realization") or "",
                "subject": cu.get("nameShort") or cu.get("name") or ev.get("nameShort") or "",
                "subject_full": cu.get("name") or "",
                "room": room.get("name") or "",
                "building": (room.get("building") or {}).get("name") or "",
                "teachers": sorted(set(teachers.get(ev_id, []))),
            }
        )
    return out


def merge_records(old: list[dict], records: list[dict], exclude=()) -> list[dict]:
    """Сливает новые занятия с архивом по id (без файлов)."""
    ex = {n.strip().lower() for n in (exclude or []) if n and n.strip()}
    by_id = {
        r["id"]: r
        for r in (old or [])
        if r.get("id") and (r.get("subject") or "").strip().lower() not in ex
    }
    for r in records:
        if (r.get("subject") or "").strip().lower() in ex:
            by_id.pop(r["id"], None)
            continue
        by_id[r["id"]] = r

    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).isoformat()
    return sorted(
        (r for r in by_id.values() if (r.get("start") or "") >= cutoff),
        key=lambda r: r.get("start", ""),
    )


def merge(path: Path, records: list[dict], exclude=()) -> list[dict]:
    """Локальный вариант: сливает новые занятия с архивом в файле."""
    old: list[dict] = []
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            old = []
    merged = merge_records(old, records, exclude=exclude)
    path.write_text(json.dumps(merged, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return merged


def build(merged: list[dict]) -> str:
    subjects: dict[str, dict] = {}
    for e in merged:
        sid = e.get("subject_id") or e.get("subject") or "?"
        subjects.setdefault(sid, {"name": e.get("subject") or "", "full": e.get("subject_full") or ""})

    payload = {
        "generated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "subjects": subjects,
        "events": merged,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
