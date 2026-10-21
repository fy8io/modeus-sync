"""Синхронизация расписания Modeus -> GitHub Gist. Запускается в GitHub Actions.

Секреты:
    MODEUS_STATE  base64(storage_state с cookies Modeus + Microsoft SSO)
    GH_PAT        токен GitHub с правом gist

Локальная проверка:
    python -m sync.cloud_sync --dry-run
"""
from __future__ import annotations

import base64
import json
import os
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import gist  # noqa: E402
import icsgen  # noqa: E402
import modeus_api  # noqa: E402
import notify  # noqa: E402
import sitedata  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    args = sys.argv[1:]
    dry = "--dry-run" in args

    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8-sig"))
    excluded = cfg.get("exclude_subjects") or []
    days = int(cfg.get("days_ahead", 120))
    gist_id = (cfg.get("gist_id") or "").strip()

    state_b64 = (os.environ.get("MODEUS_STATE") or "").strip()
    token = (os.environ.get("GH_PAT") or "").strip()

    if not state_b64:
        log("Ошибка: не задан MODEUS_STATE")
        return 2
    if not token:
        log("Ошибка: не задан GH_PAT")
        return 2

    try:
        state = json.loads(base64.b64decode(state_b64))
    except Exception as exc:
        log(f"Ошибка: MODEUS_STATE не декодируется: {exc}")
        return 2

    log("Тяну расписание из Modeus...")
    data = modeus_api.fetch_events(state, days_ahead=days, days_back=21)
    log(f"Событий из API: {len(data['events'])}")

    if excluded:
        before = len(data["events"])
        data = sitedata.drop_excluded(data, excluded)
        log(f"Отфильтровано занятий: {before - len(data['events'])}")

    old: list[dict] = []
    if gist_id:
        try:
            raw = gist.read(token, gist_id, "schedule.json")
            old = (json.loads(raw) or {}).get("events", []) if raw else []
            log(f"Архив из gist: {len(old)}")
        except Exception as exc:  # noqa: BLE001
            log(f"Предупреждение: архив не прочитан ({exc})")

    records = sitedata.enrich(data)
    merged = sitedata.merge_records(old, records, exclude=excluded)
    log(f"Архив после слияния: {len(merged)}")

    if old:
        changes = notify.diff(old, records, days_ahead=days)
        if changes:
            log(f"Изменений для уведомления: {len(changes)}")
    else:
        changes = []
        log("Первый запуск: уведомления об изменениях пропущены")

    cutoff = (date.today() - timedelta(days=7)).isoformat()
    ics_events = [e for e in data["events"] if (e.get("start") or "")[:10] >= cutoff]
    ics_text = icsgen.build_ics({**data, "events": ics_events})
    schedule_json = sitedata.build(merged)
    log(f"ICS: {len(ics_text.encode('utf-8'))} байт, JSON: {len(schedule_json.encode('utf-8'))} байт")

    if dry:
        log(f"dry-run: публикация пропущена (изменений: {len(changes)})")
        return 0

    info = gist.publish(token, ics_text, gist_id or None, extra={"schedule.json": schedule_json})
    log(f"Gist обновлён: {info['html_url'] or info['id']}")
    log(f"Ссылка для Outlook: {info['raw_url']}")

    if changes:
        try:
            if notify.notify_changes(changes):
                log("Telegram: уведомление отправлено")
        except Exception as exc:  # noqa: BLE001
            log(f"Telegram: не отправлено ({exc})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise
