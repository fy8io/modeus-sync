"""Снять cookies Modeus в base64 для секрета MODEUS_STATE (запускать на ПК).

Использование:
    python sync/export_state.py

Скрипт откроет сохранённый профиль Playwright, зайдёт на страницу расписания
и сохранит base64 в файл modeus_state.b64. Содержимое файла нужно вставить
в GitHub Secret MODEUS_STATE.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ModeusOutlook" / "profile"
SCHEDULE_URL = "https://sfedu.modeus.org/schedule-calendar/my"


def main() -> int:
    if not PROFILE.exists():
        print(f"Нет профиля: {PROFILE}")
        print("Сначала выполни: python sync.py --login")
        return 1

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(SCHEDULE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        state = ctx.storage_state()
        ctx.close()

    cookies = [c for c in state["cookies"] if "modeus" in c["domain"]]
    if not cookies:
        print("Cookies Modeus не найдены — войди заново: python sync.py --login")
        return 1

    payload = json.dumps(
        {"cookies": cookies, "origins": []}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    b64 = base64.b64encode(payload).decode("ascii")

    out = Path("modeus_state.b64")
    out.write_text(b64, encoding="ascii")
    print(f"Cookies: {len(cookies)}")
    print(f"Размер base64: {len(b64)} символов")
    print(f"Сохранено: {out.resolve()}")
    print("Вставь содержимое файла в GitHub Secret MODEUS_STATE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
