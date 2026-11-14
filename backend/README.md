# Backend

FastAPI API, Telegram-бот (этап 6) и ARQ-воркер (этапы 4–5) в одном пакете `app`.

## Локальный запуск

Нужны Python 3.12, PostgreSQL ≥ 14 (с `btree_gist`, входит в стандартную поставку) и Redis.
Docker Compose появится на этапе 9.

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env          # заполнить DATABASE_URL, BOT_TOKEN, JWT_SECRET

.venv/bin/alembic upgrade head
.venv/bin/barber init --name "Barbershop"        # филиал, настройки салона, бонусы, уровни
.venv/bin/barber create-admin --login owner --role owner

.venv/bin/uvicorn app.main:app_factory --factory --reload --port 8000
```

Swagger (только `ENV=dev|test`): http://localhost:8000/api/docs, схема: `/api/openapi.json`.
Выгрузка схемы без БД: `.venv/bin/barber export-openapi openapi.json`.

## Проверки

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy app tests
TEST_DATABASE_URL=postgresql+asyncpg://localhost:5432/barber_test .venv/bin/pytest
DATABASE_URL=... .venv/bin/alembic check      # модели и миграции не расходятся
```

Тесты создают схему **через реальные миграции Alembic** в отдельной БД (`barber_test`,
пересоздаётся при каждом запуске); Redis подменяется `fakeredis`.

## Слои

```
app/api/v1/{admin,miniapp}   роутеры: HTTP, DTO, зависимости авторизации
app/services                 бизнес-логика, транзакции, аудит (mypy --strict)
app/repositories             запросы SQLAlchemy
app/domain                   чистые функции без IO (слоты, деньги, бонусы — этапы 3–5)
app/models                   ORM-модели, источник для миграций
app/core                     конфиг, БД, Redis, ошибки, логи, initData/JWT/CSRF
```

## Авторизация

- **Mini App**: `Authorization: tma <initData>`; HMAC-SHA256 по bot token, `auth_date` ≤ 24 ч.
  Первый запрос регистрирует клиента; `start_param=ref_<code>` привязывает реферера.
- **Админка**: `POST /api/v1/admin/auth/login` → cookies `access_token` (15 мин, httpOnly),
  `refresh_token` (30 дней, httpOnly, path `/api/v1/admin/auth`, ротация с детектом повторного
  использования), `csrf_token` (читаемый). Мутирующие запросы требуют `X-CSRF-Token`.
  Права роли — в `GET /api/v1/admin/auth/me` → `permissions`.
