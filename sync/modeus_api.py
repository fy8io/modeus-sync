"""Клиент API Modeus для GitHub Actions.

В облаке нет профиля браузера: сессия восстанавливается из storage_state
(cookies Modeus), который лежит в секрете MODEUS_STATE в base64.
Перехватываем заголовок Authorization у запроса расписания и дальше ходим
обычным requests.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import requests
from playwright.sync_api import sync_playwright

SCHEDULE_URL = "https://sfedu.modeus.org/schedule-calendar/my"
API = "https://sfedu.modeus.org/schedule-calendar-v2/api/calendar/events/search"


class NeedsLogin(RuntimeError):
    pass


def _capture(page, timeout: float = 60) -> dict:
    captured: dict = {}

    def on_request(req):
        if "events/search" not in req.url or captured:
            return
        headers = {k.lower(): v for k, v in req.headers.items()}
        auth = headers.get("authorization")
        if not auth:
            return
        captured["authorization"] = auth
        try:
            captured["body"] = json.loads(req.post_data or "{}")
        except Exception:
            captured["body"] = {}

    page.on("request", on_request)
    return captured


def _get_credentials(state: dict) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=state,
            viewport={"width": 1440, "height": 1000},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )
        page = context.new_page()
        captured = _capture(page)
        try:
            page.goto(SCHEDULE_URL, wait_until="domcontentloaded", timeout=60000)
            deadline = time.time() + 60
            while time.time() < deadline and "authorization" not in captured:
                page.wait_for_timeout(500)
        finally:
            browser.close()
    if "authorization" not in captured:
        raise NeedsLogin(
            "Не удалось получить токен Modeus. Скорее всего, истекла сессия: "
            "обнови MODEUS_STATE (см. README)."
        )
    return captured


def fetch_events(state: dict, days_ahead: int = 180, days_back: int = 7) -> dict:
    creds = _get_credentials(state)
    person_ids = creds.get("body", {}).get("attendeePersonId") or []
    headers = {
        "Authorization": creds["authorization"],
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }

    start = datetime.now().date() - timedelta(days=days_back)
    end = datetime.now().date() + timedelta(days=days_ahead)

    merged: dict[str, dict] = {}
    embedded: dict[str, dict] = {}
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=60), end)
        payload = {
            "size": 500,
            "timeMin": datetime.combine(cursor, datetime.min.time()).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timeMax": datetime.combine(chunk_end, datetime.min.time()).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "attendeePersonId": person_ids,
        }
        resp = requests.post(
            API, params={"tz": "Europe/Moscow"}, headers=headers, json=payload, timeout=60
        )
        if resp.status_code == 401:
            raise NeedsLogin("Токен Modeus отклонён (401) — обнови MODEUS_STATE.")
        if resp.status_code >= 400:
            raise RuntimeError(f"Modeus API {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        body = data.get("_embedded", {})
        for ev in body.get("events", []):
            merged[ev["id"]] = ev
        for key, items in body.items():
            if key == "events":
                continue
            bucket = embedded.setdefault(key, {})
            for item in items:
                if "id" in item:
                    bucket[item["id"]] = item
        cursor = chunk_end
        if chunk_end >= end:
            break

    return {"events": list(merged.values()), "embedded": embedded}
