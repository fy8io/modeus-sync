"""Публикация .ics и schedule.json в GitHub Gist (постоянный raw-URL)."""
from __future__ import annotations

import requests

API = "https://api.github.com"
FILENAME = "schedule.ics"


class GistError(RuntimeError):
    pass


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _check(resp: requests.Response, action: str) -> dict:
    if resp.status_code == 401:
        raise GistError("GitHub отверг токен (401). Проверь, что токен с правом 'gist'.")
    if resp.status_code == 403:
        raise GistError(
            "GitHub: доступ запрещён (403). У токена нет права 'gist' или превышен лимит."
        )
    if resp.status_code >= 400:
        raise GistError(f"GitHub {action}: {resp.status_code} {resp.text[:500]}")
    return resp.json() if resp.content else {}


def raw_url(owner: str, gist_id: str, filename: str = FILENAME) -> str:
    """Постоянная ссылка на последнюю версию файла."""
    return f"https://gist.githubusercontent.com/{owner}/{gist_id}/raw/{filename}"


def read(token: str, gist_id: str, filename: str) -> str:
    """Читает файл из gist (через API, без кэша CDN)."""
    data = _check(
        requests.get(f"{API}/gists/{gist_id}", headers=_headers(token), timeout=30),
        "чтение",
    )
    f = (data.get("files") or {}).get(filename)
    if not f:
        return ""
    if f.get("truncated") and f.get("raw_url"):
        return requests.get(f["raw_url"], timeout=60).text
    return f.get("content") or ""


def publish(
    token: str,
    content: str,
    gist_id: str | None = None,
    extra: dict[str, str] | None = None,
) -> dict:
    """Создаёт или обновляет gist. Возвращает {'id', 'raw_url', 'html_url'}."""
    me = _check(
        requests.get(f"{API}/user", headers=_headers(token), timeout=30), "профиль"
    )
    owner = me["login"]

    files = {FILENAME: {"content": content}}
    for name, text in (extra or {}).items():
        files[name] = {"content": text}

    if gist_id:
        data = _check(
            requests.patch(
                f"{API}/gists/{gist_id}",
                headers=_headers(token),
                json={"files": files},
                timeout=60,
            ),
            "обновление",
        )
    else:
        data = _check(
            requests.post(
                f"{API}/gists",
                headers=_headers(token),
                json={
                    "description": "Расписание Модеус (обновляется автоматически)",
                    "public": False,
                    "files": files,
                },
                timeout=60,
            ),
            "создание",
        )

    new_id = data.get("id") or gist_id
    return {
        "id": new_id,
        "raw_url": raw_url(owner, new_id),
        "html_url": data.get("html_url", ""),
    }
