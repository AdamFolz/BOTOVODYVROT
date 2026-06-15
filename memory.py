import json
import logging
import os
from typing import Any

from openai import AsyncOpenAI

from database import Database
from prompts import MEMORY_CURATOR_PROMPT
from utils import safe_short


logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self, db: Database, openai_client: AsyncOpenAI, model: str) -> None:
        self.db = db
        self.client = openai_client
        self.model = model

    def build_context_for_user(self, chat_id: int, user_id: int, max_recent_messages: int = 80) -> str:
        profile = self.db.get_user_profile(chat_id, user_id)
        chat_memory = self.db.get_chat_memory(chat_id)
        recent_messages = self.db.recent_messages(chat_id, max_recent_messages)
        user_messages = self.db.recent_user_messages(chat_id, user_id, 25)
        relationships = self.db.recent_relationships_for_user(chat_id, user_id, 20)
        manual_memories = self.db.recent_manual_memories(chat_id, 10)
        recent_bot_responses = self.db.recent_bot_responses(chat_id, 20)

        blocks: list[str] = []

        if profile:
            blocks.append(
                "ДОСЬЕ УЧАСТНИКА:\n"
                f"Имя: {profile['display_name']} (@{profile['username']})\n"
                f"Стиль: {profile['style_summary']}\n"
                f"Темы: {profile['frequent_topics']}\n"
                f"Упоминания: {profile['mentioned_users']}\n"
                f"Связи: {profile['relationship_notes']}\n"
                f"Личные мемы: {profile['personal_memes']}\n"
                f"Мягкие ярлыки: {profile['soft_labels']}\n"
                f"Активность: {profile['energy_level']}/5\n"
                f"Токсичный стиль: {profile['toxicity_style']}\n"
                f"Мемность: {profile['meme_score']}/5\n"
                f"Ночной режим: {profile['night_mode_behavior']}\n"
                f"Уверенность наблюдений: {profile['confidence_score']}"
            )
        else:
            blocks.append("ДОСЬЕ УЧАСТНИКА: пока почти пустое, используй только свежий контекст.")

        if chat_memory:
            blocks.append(
                "ПАМЯТЬ КОНФЫ:\n"
                f"Настроение дня: {chat_memory['mood_today']}\n"
                f"Уровень хаоса: {chat_memory['chaos_level']}/5\n"
                f"Главная тема: {chat_memory['main_topic_today']}\n"
                f"Главный клоун дня: {chat_memory['main_clown_today']}\n"
                f"Мем дня: {chat_memory['meme_of_the_day']}\n"
                f"Мемы недели: {chat_memory['weekly_memes']}\n"
                f"Недавняя драма: {chat_memory['recent_drama']}\n"
                f"Популярные темы: {chat_memory['popular_topics']}\n"
                f"Локальные фразы: {chat_memory['local_phrases']}\n"
                f"Артефакты: {chat_memory['sacred_artifacts']}\n"
                f"Мифология: {chat_memory['chat_mythology']}"
            )
        else:
            blocks.append("ПАМЯТЬ КОНФЫ: пока пустая.")

        if relationships:
            rel_text = "\n".join(
                f"- {row['relation_type']}: {row['notes']} (наблюдений: {row['evidence_count']})"
                for row in relationships
            )
            blocks.append("СВЯЗИ УЧАСТНИКА:\n" + rel_text)

        if manual_memories:
            mem_text = "\n".join(f"- {row['text']}" for row in manual_memories)
            blocks.append("РУЧНАЯ ПАМЯТЬ ОТ КОНФЫ:\n" + mem_text)

        if user_messages:
            user_text = "\n".join(
                f"{row['display_name']}: {row['text']}"
                for row in user_messages[-15:]
            )
            blocks.append("ПОСЛЕДНИЕ СООБЩЕНИЯ УЧАСТНИКА:\n" + user_text)

        if recent_messages:
            recent_text = "\n".join(
                f"{row['display_name']}: {row['text']}"
                for row in recent_messages[-35:]
            )
            blocks.append("СВЕЖИЙ КОНТЕКСТ ЧАТА:\n" + recent_text)

        if recent_bot_responses:
            old_text = "\n".join(f"- {text}" for text in recent_bot_responses[:15])
            blocks.append("НЕДАВНИЕ ОТВЕТЫ БОТА, ИХ НЕЛЬЗЯ ПОВТОРЯТЬ:\n" + old_text)

        return safe_short("\n\n".join(blocks), 12000)

    def build_chat_context(self, chat_id: int, max_recent_messages: int = 100) -> str:
        chat_memory = self.db.get_chat_memory(chat_id)
        recent_messages = self.db.recent_messages(chat_id, max_recent_messages)
        manual_memories = self.db.recent_manual_memories(chat_id, 10)

        blocks: list[str] = []

        if chat_memory:
            blocks.append(
                "ПАМЯТЬ КОНФЫ:\n"
                f"Настроение дня: {chat_memory['mood_today']}\n"
                f"Уровень хаоса: {chat_memory['chaos_level']}/5\n"
                f"Главная тема: {chat_memory['main_topic_today']}\n"
                f"Главный клоун дня: {chat_memory['main_clown_today']}\n"
                f"Мем дня: {chat_memory['meme_of_the_day']}\n"
                f"Мемы недели: {chat_memory['weekly_memes']}\n"
                f"Недавняя драма: {chat_memory['recent_drama']}\n"
                f"Популярные темы: {chat_memory['popular_topics']}\n"
                f"Локальные фразы: {chat_memory['local_phrases']}\n"
                f"Артефакты: {chat_memory['sacred_artifacts']}\n"
                f"Мифология: {chat_memory['chat_mythology']}"
            )

        if manual_memories:
            blocks.append("РУЧНАЯ ПАМЯТЬ:\n" + "\n".join(f"- {row['text']}" for row in manual_memories))

        if recent_messages:
            blocks.append(
                "ПОСЛЕДНИЕ СООБЩЕНИЯ:\n"
                + "\n".join(f"{row['display_name']}: {row['text']}" for row in recent_messages[-50:])
            )

        return safe_short("\n\n".join(blocks), 12000)

    async def maybe_update_memory(self, chat_id: int) -> None:
        every = int(os.getenv("MEMORY_UPDATE_EVERY_MESSAGES", "40"))
        min_messages = int(os.getenv("MEMORY_MIN_MESSAGES", "20"))

        count = self.db.count_messages(chat_id)
        last = self.db.get_meta_int(chat_id, "last_memory_update_message_count", 0)

        if count < min_messages:
            return
        if count - last < every:
            return

        await self.update_memory(chat_id)
        self.db.set_meta(chat_id, "last_memory_update_message_count", count)

    async def update_memory(self, chat_id: int) -> None:
        messages = self.db.recent_messages(chat_id, 120)
        if not messages:
            return

        packed_messages = [
            {
                "user_id": row["user_id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "text": row["text"],
                "created_at": row["created_at"],
            }
            for row in messages
        ]

        prompt = MEMORY_CURATOR_PROMPT.format(
            messages=json.dumps(packed_messages, ensure_ascii=False, indent=2)
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": "Ты аккуратный аналитик памяти. Возвращай только валидный JSON.",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
            )
        except Exception:
            logger.exception("Memory update OpenAI request failed")
            return

        content = response.choices[0].message.content or "{}"
        data = self._parse_json_object(content)
        if not data:
            logger.warning("Memory update returned invalid JSON")
            return

        chat_memory = data.get("chat_memory")
        if isinstance(chat_memory, dict):
            try:
                self.db.upsert_chat_memory(chat_id, chat_memory)
            except Exception:
                logger.exception("Failed to upsert chat memory")

        profiles = data.get("user_profiles", [])
        if isinstance(profiles, list):
            for profile in profiles:
                if isinstance(profile, dict) and profile.get("user_id"):
                    try:
                        self.db.upsert_user_profile(chat_id, profile)
                    except Exception:
                        logger.exception("Failed to upsert user profile")

        relationships = data.get("relationships", [])
        if isinstance(relationships, list):
            for relation in relationships:
                if isinstance(relation, dict):
                    try:
                        self.db.upsert_relationship(chat_id, relation)
                    except Exception:
                        logger.exception("Failed to upsert relationship")

    def _parse_json_object(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json\n", "", 1).strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end >= start:
            cleaned = cleaned[start:end + 1]

        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError:
            return {}

        return obj if isinstance(obj, dict) else {}
