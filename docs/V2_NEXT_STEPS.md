# Что дальше после v1 export

Принятые решения:

1. v2 можно строить рядом с v1 и постепенно заменить v1.
2. Технические решения выбираются по качеству долгосрочной памяти: PostgreSQL для v2, SQLite только для локального v1/export.
3. Privacy mode — вариант B: заложить `/privacy`, `/export_me`, `/delete_me`, `/forget` и admin review.
4. Автоматизация памяти — бот сам предлагает наблюдения, но risky/personal claims уходят в quarantine/review.
5. Текущий запуск — локально на компьютере; production-контур позже можно вынести на бесплатный/дешёвый сервер или VPS.

## Следующий практический этап

После `scripts/export_v1.py` следующий шаг — зафиксировать v2 data model. Для этого добавлен `docs/v2_schema.sql` — PostgreSQL draft схемы evidence-first memory.

Сейчас добавлен практический v2 transition mode:

1. `scripts/build_v2_seed.py` — локальная конвертация v1 export в v2-shaped seed JSONL.
2. `scripts/import_v2_seed.py` — идемпотентная загрузка v2 seed/live JSONL в PostgreSQL после применения `docs/v2_schema.sql`.
3. `V2_FULL_TRANSITION=1` или `V1_MEMORY_FALLBACK_ENABLED=0` — runtime-режим, в котором prompt context строится из v2 seed/live log без v1 memory fallback.
4. Live ingestion пишет Telegram `message_id`, thread id, reply id и `/remember` в v2 JSONL, чтобы события не оставались только в v1 SQLite во время перехода.

Оставшиеся production-задачи:

1. `src/storage/` — async PostgreSQL connection/repositories вместо JSONL-cache в runtime.
2. `src/ingestion/` — прямой idempotent PostgreSQL writer для Telegram events.
3. `src/curation/` — LLM extraction в `memory_observations`, затем validation/scoring.
4. `src/retrieval/` — repository-based выбор claims для `/profile`, `/lore`, `/summary`, `/future`.

## Почему не сразу переписывать bot.py

Сначала нужно защитить данные и определить memory contract. Если сразу переписать handlers, но оставить старую модель памяти, главная проблема не исчезнет: бот продолжит превращать mutable summaries в источник истины.
