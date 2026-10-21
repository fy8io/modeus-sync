"""Снять cookies Modeus + Microsoft SSO в base64 для секрета MODEUS_STATE.

Использование:
    python export_state.py          # сохранить modeus_state.b64
    python export_state.py --push   # сразу обновить секрет MODEUS_STATE

Скрипт откроет сохранённый профиль Playwright, зайдёт на страницу расписания
и сохранит base64 в файл modeus_state.b64. С --push он также отправит его
в GitHub Actions (нужен secrets.json с github_token).

Важно: сохраняются не только cookies Modeus, но и cookies Microsoft SSO.
Без них облако не сможет молча переавторизоваться, когда сессия WSO2 истечёт.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ModeusOutlook" / "profile"
SCHEDULE_URL = "https://sfedu.modeus.org/schedule-calendar/my"
REPO = "fy8io/modeus-sync"


def _find_secrets() -> Path | None:
    here = Path(__file__).resolve().parent
    for candidate in (Path.cwd() / "secrets.json", here / "secrets.json", here.parent / "secrets.json"):
        if candidate.exists():
            return candidate
    return None


def push_secret(b64: str) -> int:
    try:
        import requests
        from nacl import encoding, public
    except Exception as exc:  # noqa: BLE001
        print(f"Не могу обновить секрет: {exc}")
        print("Установи зависимости: pip install requests pynacl")
        return 1

    secrets_path = _find_secrets()
    if secrets_path is None:
        print("secrets.json не найден — обнови секрет вручную.")
        return 1

    token = (json.loads(secrets_path.read_text(encoding="utf-8-sig")).get("github_token") or "").strip()
    if not token:
        print("В secrets.json нет github_token — обнови секрет вручную.")
        return 1

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    key = requests.get(
        f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
        headers=headers,
        timeout=30,
    ).json()
    box = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder()))
    encrypted = base64.b64encode(box.encrypt(b64.encode("ascii"))).decode("ascii")
    resp = requests.put(
        f"https://api.github.com/repos/{REPO}/actions/secrets/MODEUS_STATE",
        headers=headers,
        json={"encrypted_value": encrypted, "key_id": key["key_id"]},
        timeout=30,
    )
    if resp.status_code in (201, 204):
        print(f"Секрет MODEUS_STATE обновлён в {REPO}.")
        return 0
    print(f"GitHub API {resp.status_code}: {resp.text[:300]}")
    return 1


def main(push: bool = False) -> int:
    if not PROFILE.exists():
        print(f"Нет профиля: {PROFILE}")
        print("Сначала выполни: python modeus.py --login")
        return 1

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(SCHEDULE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        state = ctx.storage_state()
        ctx.close()

    cookies = [c for c in state["cookies"] if "yandex" not in c["domain"]]
    if not cookies:
        print("Cookies не найдены — войди заново: python modeus.py --login")
        return 1

    ms = sum(1 for c in cookies if "microsoft" in c["domain"])
    if not ms:
        print("Внимание: cookies Microsoft SSO не найдены.")
        print("Облако сможет работать, только пока жива сессия Modeus.")

    payload = json.dumps(
        {"cookies": cookies, "origins": []}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    b64 = base64.b64encode(payload).decode("ascii")

    out = Path("modeus_state.b64")
    out.write_text(b64, encoding="ascii")
    print(f"Cookies: {len(cookies)} (Microsoft: {ms})")
    print(f"Размер base64: {len(b64)} символов")
    print(f"Сохранено: {out.resolve()}")
    if push:
        return push_secret(b64)
    print("Вставь содержимое файла в GitHub Secret MODEUS_STATE.")
    print("Или запусти с --push, чтобы обновить секрет автоматически.")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Снять cookies Modeus для MODEUS_STATE")
    parser.add_argument("--push", action="store_true", help="сразу обновить секрет в GitHub")
    raise SystemExit(main(push=parser.parse_args().push))
