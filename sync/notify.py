"""Уведомления в Telegram: изменения расписания и сбои синхронизации."""
from __future__ import annotations

import html
import os
import sys
from datetime import datetime, timedelta

import requests

API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LEN = 3900

GROUPS = [
    ("added", "➕ Новые пары"),
    ("moved", "🕒 Переносы"),
    ("cancelled", "❌ Отмены"),
    ("room", "📍 Аудитории"),
    ("teacher", "👤 Преподаватели"),
    ("restored", "✅ Снова в расписании"),
    ("removed", "🗑 Убрано из расписания"),
]


def _dt(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _when(event: dict) -> str:
    dt = _dt(event.get("start") or "")
    return dt.strftime("%d.%m %H:%M") if dt else "?"


def _slot(event: dict) -> str:
    start = _dt(event.get("start") or "")
    end = _dt(event.get("end") or "")
    if not start:
        return "?"
    if end and end.date() == start.date():
        return f"{start:%d.%m %H:%M}–{end:%H:%M}"
    return start.strftime("%d.%m %H:%M")


def _subject(event: dict) -> str:
    return (event.get("subject") or event.get("title") or "Занятие").strip()


def _room(event: dict) -> str:
    room = (event.get("room") or "").strip()
    building = (event.get("building") or "").strip()
    if room and building:
        return f"{room} ({building})"
    return room or building or "—"


def _place(event: dict) -> str:
    room = _room(event)
    return f", ауд. {room}" if room != "—" else ""


def _teachers(event: dict) -> str:
    return ", ".join(event.get("teachers") or []) or "—"


def diff(old: list[dict], new: list[dict], days_ahead: int = 120, now: datetime | None = None) -> list[dict]:
    """Сравнивает архив с новыми событиями и возвращает список изменений."""
    now = now or datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    horizon = now + timedelta(days=days_ahead + 1)

    old_by = {e["id"]: e for e in (old or []) if e.get("id")}
    new_by = {e["id"]: e for e in (new or []) if e.get("id")}
    out: list[dict] = []

    for eid, event in new_by.items():
        start = _dt(event.get("start") or "")
        if not start or start < today or start > horizon:
            continue

        old_event = old_by.get(eid)
        if old_event is None:
            if event.get("status") != "CANCELLED":
                out.append({"kind": "added", "event": event})
            continue

        if event.get("status") == "CANCELLED" and old_event.get("status") != "CANCELLED":
            out.append({"kind": "cancelled", "event": event})
            continue
        if old_event.get("status") == "CANCELLED" and event.get("status") != "CANCELLED":
            out.append({"kind": "restored", "event": event})
            continue

        if (old_event.get("start"), old_event.get("end")) != (event.get("start"), event.get("end")):
            out.append({"kind": "moved", "event": event, "old": old_event})
        if (old_event.get("room"), old_event.get("building")) != (event.get("room"), event.get("building")):
            out.append({"kind": "room", "event": event, "old": old_event})
        if (old_event.get("teachers") or []) != (event.get("teachers") or []):
            out.append({"kind": "teacher", "event": event, "old": old_event})

    for eid, old_event in old_by.items():
        start = _dt(old_event.get("start") or "")
        if not start or start < today or start > horizon:
            continue
        if eid in new_by or old_event.get("status") == "CANCELLED":
            continue
        out.append({"kind": "removed", "event": old_event})

    return out


def _line(change: dict) -> str:
    kind = change["kind"]
    event = change["event"]
    old = change.get("old") or {}

    if kind == "moved":
        return f"{_subject(event)}: {_slot(old)} → {_slot(event)}{_place(event)}"
    if kind == "room":
        return f"{_when(event)} — {_subject(event)}: {_room(old)} → {_room(event)}"
    if kind == "teacher":
        return f"{_when(event)} — {_subject(event)}: {_teachers(old)} → {_teachers(event)}"
    if kind == "cancelled":
        return f"{_when(event)} — {_subject(event)}{_place(event)} (отменена)"
    if kind == "restored":
        return f"{_when(event)} — {_subject(event)}{_place(event)} (снова активна)"
    if kind == "removed":
        return f"{_when(event)} — {_subject(event)}{_place(event)} (убрана из расписания)"
    return f"{_when(event)} — {_subject(event)}{_place(event)}"


def format_message(changes: list[dict]) -> str:
    lines = ["🔔 <b>Расписание изменилось</b>", ""]
    for kind, title in GROUPS:
        items = [c for c in changes if c["kind"] == kind]
        if not items:
            continue
        items.sort(key=lambda c: c["event"].get("start") or "")
        lines.append(f"<b>{title}</b>")
        for change in items:
            lines.append("• " + html.escape(_line(change)))
        lines.append("")
    return "\n".join(lines).strip()


def _truncate(text: str, limit: int = MAX_LEN) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit("\n", 1)[0]
    return cut + "\n…"


def send(token: str, chat_id: str, text: str, silent: bool = False) -> None:
    resp = requests.post(
        API.format(token=token),
        json={
            "chat_id": chat_id,
            "text": _truncate(text),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "disable_notification": silent,
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Telegram {resp.status_code}: {resp.text[:300]}")


def _config() -> tuple[str, str]:
    return (
        (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip(),
        (os.environ.get("TELEGRAM_CHAT_ID") or "").strip(),
    )


def notify_changes(changes: list[dict]) -> bool:
    token, chat_id = _config()
    if not changes or not token or not chat_id:
        return False
    send(token, chat_id, format_message(changes))
    return True


def main() -> int:
    args = sys.argv[1:]
    token, chat_id = _config()
    if not token or not chat_id:
        print("Telegram не настроен: нет TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return 0

    if "--test" in args:
        send(token, chat_id, "✅ <b>Modeus Sync</b>\nУведомления подключены.")
        print("Тестовое сообщение отправлено.")
        return 0

    if "--failure" in args:
        url = args[args.index("--failure") + 1] if args.index("--failure") + 1 < len(args) else ""
        text = "⚠️ <b>Синхронизация расписания упала</b>"
        if url:
            text += f'\n<a href="{html.escape(url)}">Открыть лог</a>'
        text += "\n\nПроверь сессию Modeus — возможно, её нужно обновить."
        try:
            send(token, chat_id, text)
            print("Уведомление о сбое отправлено.")
        except Exception as exc:  # noqa: BLE001
            print(f"Не удалось отправить: {exc}")
        return 0

    print("Использование: notify.py --test | --failure <url>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
