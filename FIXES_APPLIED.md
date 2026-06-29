# Исправления BOTOVODYVROT (PredskazBot)

Дата: автоматический патч.

## Что было сломано

Главная проблема: в `memory.py` v2-хранилище памяти было подключено только наполовину.
Из-за этого почти все команды бота падали с ошибкой ещё до ответа пользователю.

### Критические баги

1. **`memory.py` — `self.v2_store` не создавался.** Атрибут использовался в нескольких
   методах, но в `__init__` его не было → `AttributeError` при `/profile`, `/lore`,
   `/future`, `/summary`. То есть бот падал почти на любой команде.
2. **`memory.py` — `self.v2_jsonl_bridge_enabled` не определён** → ошибка при сохранении
   каждого входящего сообщения.
3. **`memory.py` — `record_v2_message` использовал несуществующие переменные**
   `chat_title`, `chat_type` → `NameError`.
4. **`memory.py` — два метода `record_v2_manual_memory`**, первый — битый мёртвый код
   с неопределёнными переменными.
5. **`memory.py` — не было метода `v2_status_text`**, хотя команда `/v2status` его вызывала.
6. **`memory.py` — не было метода `record_v2_bot_response`**, хотя `/summary` и `/future`
   его вызывали (ответы бота молча не писались в v2).
7. **`src/predskazbot_v2/sqlite_store.py` — `ensure_membership` затирал имя пользователя
   пустыми значениями.** На практике: после `/remember` имя в v2 обнулялось и `/profile`
   показывал UUID вместо имени.

## Что исправлено

- В `MemoryManager.__init__` добавлены `v2_sqlite_path`, `v2_jsonl_bridge_enabled` и
  создание `self.v2_store = SQLiteV2Store(...)` (как описано в `.env.example` и `RUN_LOCAL.md`).
- `record_v2_message` починен; убраны несуществующие переменные; JSONL-bridge корректно
  передаёт `message_id` / `thread_id` / `reply_to`.
- Оставлен один корректный `record_v2_manual_memory` (пишет и в SQLite, и в JSONL-bridge).
- Добавлен `record_v2_bot_response` (пишет ответы бота в `bot_responses_v2`).
- Добавлен `v2_status_text` для команды `/v2status` (показывает storage, путь и счётчик событий).
- `bot.py`: в v2-хранилище теперь передаются название и тип чата.
- `sqlite_store.ensure_membership`: имя/username больше не затираются пустыми значениями
  (`COALESCE(NULLIF(...))`).

## Как проверено

- Все 17 `.py` файлов компилируются без ошибок.
- Все обращения `memory_manager.*` из `bot.py` сопоставлены с методами `MemoryManager`.
- Сквозной тест v2-хранилища: сообщение → /remember → ответ бота → /profile → /lore.
  Имя пользователя сохраняется, claims/память отображаются.

> Не проверено вживую: реальная работа с Telegram и OpenAI (нужны твои токены и запуск
> на твоём ПК). Сам код запускается командой `python bot.py` после заполнения `.env`.

## Изменённые файлы


### `memory.py`

```diff
--- a/memory.py
+++ b/memory.py
@@ -33,6 +33,11 @@
         self.v1_memory_fallback_enabled = os.getenv("V1_MEMORY_FALLBACK_ENABLED", "1") == "1"
         self.v2_seed_path = Path(os.getenv("V2_SEED_PATH", "exports/v2-seed.jsonl"))
         self.v2_live_events_path = Path(os.getenv("V2_LIVE_EVENTS_PATH", "exports/v2-live-events.jsonl"))
+        self.v2_sqlite_path = Path(os.getenv("V2_SQLITE_PATH", "predskazbot_v2.sqlite3"))
+        self.v2_jsonl_bridge_enabled = os.getenv("V2_JSONL_BRIDGE_ENABLED", "0") == "1"
+        self.v2_store: SQLiteV2Store | None = (
+            SQLiteV2Store(self.v2_sqlite_path) if self.v2_enabled else None
+        )
         self._v2_store_cache: SeedStore | None = None
         self._v2_store_signature: tuple[tuple[str, int, int], ...] = ()
         self.llm_disabled_reason: str | None = None
@@ -69,6 +74,8 @@
         telegram_message_id: int | None = None,
         telegram_thread_id: int | None = None,
         reply_to_message_id: int | None = None,
+        chat_title: str = "",
+        chat_type: str = "telegram",
     ) -> None:
         if not self.v2_enabled:
             return
@@ -94,40 +101,62 @@
                 display_name=display_name,
                 text=text,
                 mentions=mentions,
-            )
-
-
-    def record_v2_manual_memory(
+                telegram_message_id=telegram_message_id,
+                telegram_thread_id=telegram_thread_id,
+                reply_to_message_id=reply_to_message_id,
+            )
+
+    def record_v2_manual_memory(self, *, chat_id: int, author_user_id: int, text: str) -> None:
+        if not self.v2_enabled:
+            return
+        if self.v2_store:
+            self.v2_store.init()
+            self.v2_store.add_manual_memory(
+                telegram_chat_id=chat_id,
+                author_telegram_user_id=author_user_id,
+                text=text,
+            )
+        if self.v2_jsonl_bridge_enabled:
+            LiveEventLog(self.v2_live_events_path).append_manual_memory(
+                telegram_chat_id=chat_id,
+                author_telegram_user_id=author_user_id,
+                text=text,
+            )
+
+    def record_v2_bot_response(
         self,
         *,
         chat_id: int,
-        author_user_id: int,
-        username: str,
-        display_name: str,
-        text: str,
+        user_id: int | None,
+        command: str,
+        response_text: str,
     ) -> None:
         if not self.v2_enabled or not self.v2_store:
             return
         self.v2_store.init()
-        self.v2_store.add_manual_memory(
+        self.v2_store.add_bot_response(
             telegram_chat_id=chat_id,
-            author_telegram_user_id=author_user_id,
-            username=username,
-            display_name=display_name,
-            text=text,
-            mentions=mentions,
-            telegram_message_id=telegram_message_id,
-            telegram_thread_id=telegram_thread_id,
-            reply_to_message_id=reply_to_message_id,
+            telegram_user_id=user_id,
+            command=command,
+            response_text=response_text,
         )
 
-    def record_v2_manual_memory(self, *, chat_id: int, author_user_id: int, text: str) -> None:
+    def v2_status_text(self, chat_id: int) -> str:
         if not self.v2_enabled:
-            return
-        LiveEventLog(self.v2_live_events_path).append_manual_memory(
-            telegram_chat_id=chat_id,
-            author_telegram_user_id=author_user_id,
-            text=text,
+            return "v2 storage: выключено (V2_MEMORY_ENABLED=0)"
+        if not self.v2_store:
+            return "v2 storage: недоступно"
+        self.v2_store.init()
+        count = self.v2_store.count_message_events(chat_id)
+        bridge = "on" if self.v2_jsonl_bridge_enabled else "off"
+        return (
+            "v2 status:\n"
+            "storage: sqlite\n"
+            f"path: {self.v2_sqlite_path}\n"
+            f"chat_message_events: {count}\n"
+            f"jsonl_bridge: {bridge}\n"
+            f"full_transition: {self.v2_full_transition}\n"
+            f"v1_fallback: {self.v1_memory_fallback_enabled}"
         )
 
     def build_v2_profile_text(self, chat_id: int, user_id: int) -> str | None:
```

### `bot.py`

```diff
--- a/bot.py
+++ b/bot.py
@@ -490,6 +490,8 @@
             telegram_message_id=update.message.message_id,
             telegram_thread_id=update.message.message_thread_id,
             reply_to_message_id=reply_to_message_id,
+            chat_title=chat.title or "",
+            chat_type=str(chat.type),
         )
     except Exception:
         logger.exception("Failed to save incoming message to v2 live event log")
```

### `src/predskazbot_v2/sqlite_store.py`

```diff
--- a/src/predskazbot_v2/sqlite_store.py
+++ b/src/predskazbot_v2/sqlite_store.py
@@ -230,8 +230,8 @@
                 )
                 VALUES (?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(chat_id, member_id) DO UPDATE SET
-                    current_username=excluded.current_username,
-                    current_display_name=excluded.current_display_name,
+                    current_username=COALESCE(NULLIF(excluded.current_username, ''), chat_memberships.current_username),
+                    current_display_name=COALESCE(NULLIF(excluded.current_display_name, ''), chat_memberships.current_display_name),
                     aliases_json=excluded.aliases_json,
                     last_seen_at=excluded.last_seen_at
                 """,
```
