import logging
import os
import time
from collections import defaultdict

from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from database import Database
from memory import MemoryManager
from prompts import CORE_STYLE_SYSTEM, FUTURE_PROMPT, SUMMARY_PROMPT
from utils import clean_bot_reply, extract_mentions, is_too_similar, safe_short


load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("predskazbot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DATABASE_PATH = os.getenv("DATABASE_PATH", "predskazbot.sqlite3")
MAX_RECENT_MESSAGES = int(os.getenv("MAX_RECENT_MESSAGES", "80"))
MAX_RECENT_BOT_RESPONSES = int(os.getenv("MAX_RECENT_BOT_RESPONSES", "80"))
REGENERATION_ATTEMPTS = int(os.getenv("REGENERATION_ATTEMPTS", "3"))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
FUTURE_COOLDOWN_SECONDS = int(os.getenv("FUTURE_COOLDOWN_SECONDS", "20"))
SUMMARY_COOLDOWN_SECONDS = int(os.getenv("SUMMARY_COOLDOWN_SECONDS", "60"))

db = Database(DATABASE_PATH)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
memory_manager = MemoryManager(db, openai_client, OPENAI_MODEL)

future_rate_limit: dict[tuple[int, int], float] = defaultdict(float)
summary_rate_limit: dict[int, float] = defaultdict(float)


def user_display_name(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "Неизвестный"
    name = " ".join(part for part in [user.first_name, user.last_name] if part)
    return name or user.username or str(user.id)


def username_of(update: Update) -> str:
    user = update.effective_user
    if not user:
        return ""
    return user.username or ""


def chat_id_of(update: Update) -> int:
    chat = update.effective_chat
    if not chat:
        raise RuntimeError("No chat in update")
    return int(chat.id)


def user_id_of(update: Update) -> int:
    user = update.effective_user
    if not user:
        raise RuntimeError("No user in update")
    return int(user.id)


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and ADMIN_USER_ID and user.id == ADMIN_USER_ID)


def check_user_cooldown(
    bucket: dict[tuple[int, int], float],
    chat_id: int,
    user_id: int,
    cooldown_seconds: int,
) -> int:
    now = time.time()
    key = (chat_id, user_id)
    allowed_at = bucket.get(key, 0.0)
    if now < allowed_at:
        return int(allowed_at - now) + 1
    bucket[key] = now + cooldown_seconds
    return 0


def check_chat_cooldown(
    bucket: dict[int, float],
    chat_id: int,
    cooldown_seconds: int,
) -> int:
    now = time.time()
    allowed_at = bucket.get(chat_id, 0.0)
    if now < allowed_at:
        return int(allowed_at - now) + 1
    bucket[chat_id] = now + cooldown_seconds
    return 0


async def safe_send(update: Update, text: str, max_len: int = 3500) -> None:
    chat = update.effective_chat
    if not chat:
        logger.warning("safe_send skipped: no effective chat")
        return

    payload = safe_short(text, max_len)
    try:
        await chat.send_message(payload)
    except RetryAfter as exc:
        logger.warning("Telegram rate limit hit: retry_after=%s", exc.retry_after)
    except (BadRequest, Forbidden, TimedOut):
        logger.exception("Failed to send Telegram message")
    except Exception:
        logger.exception("Unexpected Telegram send failure")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Я PredskazBot v1. Я запоминаю конфу, строю досье и выдаю предсказания.\n\n"
        "Команды:\n"
        "/future — предсказание\n"
        "/profile — твоё досье\n"
        "/profile @username — досье участника\n"
        "/lore — лор конфы\n"
        "/remember текст — сохранить мем/факт (только админ)\n"
        "/summary — летопись последних событий"
    )
    await safe_send(update, text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def remember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not is_admin(update):
        await safe_send(update, "Эта команда доступна только админу.")
        return

    chat_id = chat_id_of(update)
    user_id = user_id_of(update)
    text = update.message.text or ""
    memory_text = text.partition(" ")[2].strip()

    if not memory_text:
        await safe_send(update, "Напиши так: /remember важный мем конфы")
        return

    if len(memory_text) > 500:
        await safe_send(update, "Слишком длинная память. Держи её короткой.")
        return

    try:
        db.add_manual_memory(chat_id, user_id, memory_text)
    except Exception:
        logger.exception("Failed to save manual memory")
        await safe_send(update, "Не получилось сохранить память. Попробуй позже.")
        return

    await safe_send(update, "Запомнил.")


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    chat_id = chat_id_of(update)
    target_user_id = user_id_of(update)

    if context.args:
        raw = context.args[0].strip()
        if raw.startswith("@"):
            row = db.get_user_by_username(chat_id, raw)
            if not row:
                await safe_send(update, "Я пока не знаю такого персонажа. Пусть напишет что-нибудь в чат.")
                return
            target_user_id = int(row["user_id"])

    row = db.get_user_profile(chat_id, target_user_id)
    if not row:
        await safe_send(
            update,
            "Досье пока пустое. Мне нужно больше сообщений, чтобы не гадать по кофейной гуще.",
        )
        return

    text = (
        f"Досье: {row['display_name']} (@{row['username']})\n"
        f"Стиль: {row['style_summary']}\n"
        f"Темы: {row['frequent_topics']}\n"
        f"Мемы: {row['personal_memes']}\n"
        f"Ярлыки: {row['soft_labels']}\n"
        f"Активность: {row['energy_level']}/5\n"
        f"Токсичный стиль: {row['toxicity_style']}\n"
        f"Мемность: {row['meme_score']}/5\n"
        f"Ночной режим: {row['night_mode_behavior']}\n"
        f"Уверенность: {row['confidence_score']}"
    )
    await safe_send(update, text)


async def lore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    chat_id = chat_id_of(update)
    row = db.get_chat_memory(chat_id)
    if not row:
        await safe_send(update, "Лор пока не сформировался. Конфе нужно совершить пару исторических ошибок.")
        return

    text = (
        "Лор конфы:\n"
        f"Настроение: {row['mood_today']}\n"
        f"Хаос: {row['chaos_level']}/5\n"
        f"Тема дня: {row['main_topic_today']}\n"
        f"Главный клоун дня: {row['main_clown_today']}\n"
        f"Мем дня: {row['meme_of_the_day']}\n"
        f"Мемы недели: {row['weekly_memes']}\n"
        f"Драма: {row['recent_drama']}\n"
        f"Фразы: {row['local_phrases']}\n"
        f"Артефакты: {row['sacred_artifacts']}\n"
        f"Мифология: {row['chat_mythology']}"
    )
    await safe_send(update, text)


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    chat_id = chat_id_of(update)
    wait_seconds = check_chat_cooldown(summary_rate_limit, chat_id, SUMMARY_COOLDOWN_SECONDS)
    if wait_seconds > 0:
        await safe_send(update, f"Летописец отдыхает. Повтори через {wait_seconds} сек.")
        return

    try:
        await memory_manager.maybe_update_memory(chat_id)
        context_text = memory_manager.build_chat_context(chat_id, 100)

        response = await openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.7,
            messages=[
                {"role": "system", "content": CORE_STYLE_SYSTEM},
                {"role": "user", "content": SUMMARY_PROMPT.format(context=context_text)},
            ],
        )
    except Exception:
        logger.exception("Summary generation failed")
        await safe_send(update, "Летопись не сложилась. Попробуй позже.")
        return

    reply = clean_bot_reply(response.choices[0].message.content or "")
    if not reply:
        reply = "Летопись не сложилась. Видимо, конфа сегодня превзошла письменность."

    try:
        db.add_bot_response(chat_id, None, "summary", reply)
    except Exception:
        logger.exception("Failed to save summary response")

    await safe_send(update, reply)


async def future(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    chat_id = chat_id_of(update)
    user_id = user_id_of(update)

    wait_seconds = check_user_cooldown(
        future_rate_limit,
        chat_id,
        user_id,
        FUTURE_COOLDOWN_SECONDS,
    )
    if wait_seconds > 0:
        await safe_send(update, f"Оракул устал именно от тебя. Повтори через {wait_seconds} сек.", max_len=1000)
        return

    try:
        await memory_manager.maybe_update_memory(chat_id)

        context_text = memory_manager.build_context_for_user(chat_id, user_id, MAX_RECENT_MESSAGES)
        previous = db.recent_bot_responses(chat_id, MAX_RECENT_BOT_RESPONSES)

        last_reason = ""
        chosen = ""

        for _attempt in range(REGENERATION_ATTEMPTS):
            extra = ""
            if last_reason:
                extra = (
                    "\n\nПредыдущая попытка была отклонена: "
                    f"{last_reason}. Напиши иначе, с другим началом, другим ритмом и другой шуткой."
                )

            response = await openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                temperature=0.95,
                messages=[
                    {"role": "system", "content": CORE_STYLE_SYSTEM},
                    {"role": "user", "content": FUTURE_PROMPT.format(context=context_text + extra)},
                ],
            )

            candidate = clean_bot_reply(response.choices[0].message.content or "")
            if not candidate:
                continue

            too_similar, reason = is_too_similar(candidate, previous)
            if not too_similar:
                chosen = candidate
                break

            last_reason = reason
            chosen = candidate

    except Exception:
        logger.exception("Future generation failed")
        await safe_send(update, "Оракул завис. Попробуй позже.", max_len=1000)
        return

    if not chosen:
        chosen = "Оракул завис. Видимо, будущее посмотрело на конфу и решило не загружаться."

    try:
        db.add_bot_response(chat_id, user_id, "future", chosen)
    except Exception:
        logger.exception("Failed to save future response")

    await safe_send(update, chosen, max_len=1000)


async def store_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    chat = update.effective_chat
    if not chat:
        return

    if chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP, ChatType.PRIVATE}:
        return

    text = update.message.text.strip()
    if not text:
        return

    try:
        chat_id = chat_id_of(update)
        user_id = user_id_of(update)
    except RuntimeError:
        logger.warning("Skipped update without chat or user")
        return

    display_name = user_display_name(update)
    username = username_of(update)
    mentions = extract_mentions(text)

    try:
        db.add_message(chat_id, user_id, username, display_name, text, mentions)
    except Exception:
        logger.exception("Failed to save incoming message")
        return

    try:
        await memory_manager.maybe_update_memory(chat_id)
    except Exception:
        logger.exception("Memory update failed")


def validate_env() -> None:
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if missing:
        raise RuntimeError("Missing env variables: " + ", ".join(missing))


def main() -> None:
    validate_env()
    db.init()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("future", future))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("lore", lore))
    app.add_handler(CommandHandler("remember", remember))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, store_message))

    logger.info("PredskazBot v1 started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
