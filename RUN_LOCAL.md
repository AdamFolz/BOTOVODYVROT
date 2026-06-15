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

Открой `.env` и вставь токены.

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
