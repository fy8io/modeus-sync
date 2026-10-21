# Modeus Sync

Автоматическая синхронизация расписания Modeus → GitHub Gist. Работает в
GitHub Actions каждые 30 минут, компьютер не нужен.

```
Modeus API → cloud_sync.py → gist (schedule.ics, schedule.json)
                                   ↓
                        Outlook / сайт посещаемости
```

## Что обновляется

- `schedule.ics` — календарь для Outlook;
- `schedule.json` — расписание для сайта посещаемости.

`attendance.json` (отметки) этот workflow не трогает: его обновляет сайт.

## Секреты репозитория

`Settings → Secrets and variables → Actions`:

| Секрет | Что внутри |
|--------|------------|
| `MODEUS_STATE` | base64 от storage_state с cookies Modeus + Microsoft SSO |
| `GH_PAT` | GitHub-токен с правом `gist` |
| `TELEGRAM_BOT_TOKEN` | токен бота от @BotFather |
| `TELEGRAM_CHAT_ID` | id чата для уведомлений |

`MODEUS_STATE` — это не пароль, а cookies текущей сессии Modeus и Microsoft SSO.
Они лежат в зашифрованном секрете и в логи не попадают. Microsoft-cookies нужны,
чтобы облако могло молча переавторизоваться, когда сессия WSO2 истечёт.

## Как обновить сессию Modeus

Сессия WSO2 со временем истекает. Если `MODEUS_STATE` содержит cookies Microsoft
SSO, облако обычно переавторизуется само. Если job всё же упал с ошибкой
«Не удалось получить токен Modeus»:

1. На компьютере войди в Modeus (в папке локального проекта):
   ```
   python modeus.py --login
   ```
2. Сними свежие cookies и сразу обнови секрет:
   ```
   python export_state.py --push
   ```
   Скрипт сохраняет и Modeus, и Microsoft SSO cookies. Без `--push` он просто
   создаст `modeus_state.b64` — тогда скопируй его содержимое в секрет вручную.
3. Если `--push` не сработал: GitHub → репозиторий → Settings → Secrets and
   variables → Actions → `MODEUS_STATE` → Update.
4. Запусти workflow вручную: Actions → **Sync schedule** → **Run workflow**.

## Уведомления в Telegram

Бот присылает:

- переносы, отмены и новые пары;
- смену аудитории и преподавателя;
- сообщение, если синхронизация упала (например, истекла сессия).

Как подключить:

1. Открой **@BotFather** → `/newbot` → придумай имя → получи токен.
2. Напиши своему боту любое сообщение (нажми **Start**).
3. Открой в браузере
   `https://api.telegram.org/bot<ТОКЕН>/getUpdates` и найди `"chat":{"id":...}`.
4. Добавь секреты `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`.
5. Проверка: `python sync/notify.py --test`.

## Ручной запуск

Actions → **Sync schedule** → **Run workflow**.

## Локальная проверка

```
set MODEUS_STATE=<base64>
set GH_PAT=<token>
python sync/cloud_sync.py --dry-run
```

`--dry-run` собирает расписание, но ничего не публикует.

## Файлы

| Файл | Назначение |
|------|-----------|
| `sync/cloud_sync.py` | точка входа для Actions |
| `sync/modeus_api.py` | получение событий из API Modeus |
| `sync/sitedata.py` | обогащение событий и архив |
| `sync/icsgen.py` | сборка `.ics` |
| `sync/gist.py` | публикация и чтение gist |
| `sync/config.json` | id gist, горизонт, исключения |
| `sync/export_state.py` | снятие cookies Modeus + Microsoft SSO для секрета (на ПК) |
| `.github/workflows/sync.yml` | расписание запусков |
