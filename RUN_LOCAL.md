# Быстрый запуск для новичка

## 1. Установи Python

Скачай Python 3.11+:
https://www.python.org/downloads/

При установке на Windows обязательно отметь:

```text
Add Python to PATH
```

## 2. Распакуй проект

Открой терминал в папке проекта.

## 3. Создай виртуальное окружение

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

## 4. Установи зависимости

```bash
pip install -r requirements.txt
```

## 5. Создай .env

macOS / Linux:

```bash
cp .env.example .env
```

Windows:

```bash
copy .env.example .env
```

Открой `.env` и вставь токены. Без `TELEGRAM_BOT_TOKEN` и `OPENAI_API_KEY` команда `python bot.py` завершится ошибкой.

Проверка на Windows PowerShell:

```powershell
copy .env.example .env
notepad .env
```

После вставки токенов запускай:

```powershell
python bot.py
```

Если `predskazbot.sqlite3` ещё не существует, это нормально: он появится после успешного старта бота.


Если на Windows/Python 3.14 была ошибка `There is no current event loop`, обнови код до версии с `ensure_event_loop()` и снова запусти:

```powershell
python bot.py
```


## 6. Telegram token

В Telegram:

```text
@BotFather
/newbot
```

Скопируй токен в:

```text
TELEGRAM_BOT_TOKEN=
```

Выключи privacy mode:

```text
/mybots
Bot Settings
Group Privacy
Turn off
```

## 7. OpenAI key

Создай API key и вставь:

```text
OPENAI_API_KEY=
```

## 8. Запусти

```bash
python bot.py
```

## 9. Проверь

В группе:

```text
/future
/remember Андрей — леший, который вызывает предсказания чаще, чем здравый смысл
/lore
/profile
/summary
```

## 10. Экспорт памяти v1 перед rewrite

Перед переходом на v2 сделай JSONL-снимок текущей SQLite-базы. Это безопасный первый шаг миграции: v1 продолжает работать, а v2 сможет импортировать историю, профили, лор и ручные воспоминания из файла.

```bash
python scripts/export_v1.py --db predskazbot.sqlite3 --out exports/v1-export.jsonl
```

Если база старая или частично пустая и в ней нет всех таблиц v1, можно сделать частичный экспорт:

```bash
python scripts/export_v1.py --db predskazbot.sqlite3 --out exports/v1-export.jsonl --allow-missing-tables
```

## 11. Подготовь v2 seed из v1 export

После экспорта можно локально сконвертировать v1 JSONL в v2-shaped seed JSONL. Для этого PostgreSQL пока не нужен: файл нужен, чтобы проверить будущую миграцию до подключения реальной v2 базы.

```bash
python scripts/build_v2_seed.py --in exports/v1-export.jsonl --out exports/v2-seed.jsonl
```


## 12. Одна команда для локальной проверки миграции

Если не хочешь запускать export и seed отдельно, используй одну команду:

```bash
python scripts/migration_preview.py --db predskazbot.sqlite3
```

Она создаст локальные приватные файлы `exports/v1-export.jsonl` и `exports/v2-seed.jsonl`.

## 13. Посмотри, что v2 уже достаёт из памяти

После `migration_preview.py` можно посмотреть retrieval preview без запуска Telegram-бота:

```bash
python scripts/query_v2_seed.py --seed exports/v2-seed.jsonl --chat-id <TELEGRAM_CHAT_ID> --mode lore
python scripts/query_v2_seed.py --seed exports/v2-seed.jsonl --chat-id <TELEGRAM_CHAT_ID> --mode profile --user-id <TELEGRAM_USER_ID>
```


## 14. Включение v2 памяти в боте

По умолчанию бот теперь пытается использовать `exports/v2-seed.jsonl` для `/profile`, `/lore` и LLM-контекста команд. Если seed-файла нет, бот автоматически остаётся на v1 памяти.

Можно явно задать путь:

```text
V2_MEMORY_ENABLED=1
V2_SEED_PATH=exports/v2-seed.jsonl
```

Если нужно временно отключить v2:

```text
V2_MEMORY_ENABLED=0
```


## 15. Live v2 ingestion

При `V2_MEMORY_ENABLED=1` новые сообщения теперь пишутся ещё и в live v2 JSONL-журнал:

```text
V2_LIVE_EVENTS_PATH=exports/v2-live-events.jsonl
```

Это не заменяет будущую PostgreSQL v2 базу, но уже не даёт новым сообщениям оставаться только в v1 SQLite во время перехода.


## 16. Ошибка OpenAI 401 / invalid API key

Если в консоли видно `Incorrect API key provided` или `401 Unauthorized`, Telegram-бот уже запустился, но OpenAI key в `.env` неверный.

Что сделать:

1. Создай новый OpenAI API key.
2. Вставь его в `.env`:

```text
OPENAI_API_KEY=sk-...
```

3. Полностью останови бота (`Ctrl+C`) и запусти снова:

```powershell
python bot.py
```

После ошибки 401 memory updates временно отключаются до перезапуска, чтобы консоль не засыпало traceback-ами.


## 17. Как обновлять файлы без скачивания ZIP

Не скачивай архив с GitHub каждый раз. Один раз склонируй репозиторий через Git:

```powershell
cd M:/
git clone https://github.com/AdamFolz/BOTOVODYVROT.git
cd BOTOVODYVROT
copy .env.example .env
notepad .env
```

После этого для обновления используй:

```powershell
git pull --ff-only
python -m pip install -r requirements.txt
python bot.py
```

Или одной командой из папки проекта:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/update_and_run.ps1
```

Важно: `.env`, SQLite-база и `exports/*.jsonl` не должны попадать в GitHub. Они локальные и уже игнорируются через `.gitignore`.

### Как обновления попадают на GitHub

Я делаю изменения в ветке и оформляю PR. Чтобы они появились в основном репозитории на GitHub, PR нужно смерджить. После merge у себя на ПК запускаешь `git pull --ff-only`.
