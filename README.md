# Барбершоп — онлайн-запись через Telegram

Telegram-бот и Mini App для клиентов, веб-админка для салона, бонусная программа.
Салон: Бишкек (`Asia/Bishkek`), сом (суммы хранятся в тыйынах), языки ru / ky / en.

- **Архитектура, модель данных, API, решения:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Бэкенд:** [backend/README.md](backend/README.md) · **Mini App:** [apps/miniapp/README.md](apps/miniapp/README.md)

```
backend/              FastAPI API · aiogram-бот (webhook) · ARQ-воркер — один Python-пакет
apps/miniapp/         Telegram Mini App (React, Vite, tma.js)          → /app/
apps/admin/           Админка (React, UI в стиле shadcn)               → /admin/
packages/api-client/  TS-типы и клиент, сгенерированные из OpenAPI бэкенда
packages/ui/          деньги, даты, расчёт сумм — общее для обоих приложений
infra/                Dockerfile'ы, Nginx, docker-compose (dev, prod), скрипты деплоя
.github/workflows/    CI на pull request, сборка и деплой из main
```

## Локальная разработка

Нужны Python 3.12, Node 22 (`corepack enable` даёт pnpm 9) и Docker.

```bash
# 1. PostgreSQL 16 + Redis 7 (заодно создаётся база barber_test для тестов)
docker compose -f infra/compose.dev.yml up -d

# 2. Бэкенд
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env    # DATABASE_URL=postgresql+asyncpg://barber:barber@localhost:5432/barber
                        # REDIS_URL=redis://localhost:6379/0, BOT_TOKEN, JWT_SECRET, WEBHOOK_SECRET
.venv/bin/alembic upgrade head
.venv/bin/barber init --name "Barbershop"            # филиал, настройки салона и бонусов, уровни
.venv/bin/barber create-admin --login owner --role owner

.venv/bin/uvicorn app.main:app_factory --factory --reload --port 8000     # API
.venv/bin/uvicorn app.bot.main:app_factory --factory --reload --port 8001 # вебхук бота
.venv/bin/arq app.worker.main.WorkerSettings                              # воркер (ARQ cron)
cd ..

# 3. Фронтенды (dev-сервер проксирует /api на :8000)
pnpm install
pnpm --filter @barber/admin dev                # http://localhost:5180/admin/
pnpm --filter @barber/miniapp dev:init-data    # подписывает dev-initData токеном из backend/.env
pnpm --filter @barber/miniapp dev              # http://localhost:5173/app/ (Telegram замокан)
```

После изменения схем или эндпоинтов бэкенда: `pnpm gen:api` (CI упадёт, если клиент устарел).

### Проверка Mini App внутри Telegram

Telegram открывает Mini App только по HTTPS, поэтому нужен туннель к dev-серверу Mini App:

```bash
cloudflared tunnel --url http://localhost:5173      # или: ngrok http 5173
```

Dev-сервер проксирует `/api` в API (:8000), а `/api/v1/bot/webhook` — в бота (:8001), так что
хватает одного туннеля:

1. В `backend/.env` укажите `MINIAPP_URL=https://<хост-туннеля>/app/` и перезапустите API и бота.
2. Зарегистрируйте вебхук, команды и Menu Button:
   `cd backend && .venv/bin/barber bot-setup --public-url https://<хост-туннеля>`
3. Откройте бота в Telegram → `/start` → «Записаться».

### Регистрация бота в @BotFather

1. `/newbot` → имя и username → токен в `BOT_TOKEN`, username в `BOT_USERNAME`.
2. `/newapp` → выберите бота → название, описание, картинка → **Web App URL**
   `https://<домен>/app/` → short name (например, `app`) → в `MINIAPP_SHORT_NAME`.
   Ссылки тогда выглядят как `https://t.me/<bot>/app?startapp=ref_<код>`.
3. Вебхук с секретом, команды (ru/ky/en) и **Menu Button** ставит
   `barber bot-setup --public-url https://<домен>` (берёт `WEBHOOK_SECRET` и `MINIAPP_URL`).
   Menu Button можно задать и вручную: BotFather → `/mybots` → Bot Settings → Menu Button.
4. Админ-чат: добавьте бота в группу сотрудников, отправьте `/chatid`, вставьте число в
   Админка → Настройки → Уведомления.
5. Мастера: Админка → Мастера → мастер → «Ссылка для Telegram». Мастер открывает ссылку,
   и его чат начинает получать уведомления о записях.

## Тесты и проверки

```bash
cd backend && .venv/bin/ruff check . && .venv/bin/mypy app tests && .venv/bin/pytest   # нужен PostgreSQL
pnpm lint && pnpm typecheck && pnpm test && pnpm build
pnpm --filter @barber/miniapp e2e && pnpm --filter @barber/admin e2e                    # Playwright
pip install pre-commit && pre-commit install                                            # git-хуки
```

Тестовую базу задаёт `TEST_DATABASE_URL` (dev-compose создаёт `barber_test`).

## Деплой

Образы собирает CI и публикует в GHCR:

| Образ            | Что запускается                                                                   |
| ---------------- | --------------------------------------------------------------------------------- |
| `barber-backend` | `api` (uvicorn), `bot` (вебхук), `worker` (ARQ cron), `migrate` (alembic, разово) |
| `barber-nginx`   | TLS, CSP, статика Mini App и админки, прокси `/api`, WebSocket, вебхук            |

### Вариант A — один VPS (рекомендую для начала)

Ubuntu 22.04+ / Debian 12, для одного салона хватит 2 vCPU / 2 ГБ RAM.

```bash
# на сервере
curl -fsSL https://get.docker.com | sh
sudo mkdir -p /opt/barber && sudo chown $USER /opt/barber && cd /opt/barber
# скопируйте из репозитория: infra/compose.prod.yml, infra/scripts/, infra/.env.example, infra/backend.env.example
cp .env.example .env && cp backend.env.example backend.env && chmod 600 .env backend.env
# заполните: DOMAIN, REGISTRY, POSTGRES_PASSWORD; BOT_TOKEN, WEBHOOK_SECRET, JWT_SECRET (openssl rand -hex 32)
echo $GHCR_TOKEN | docker login ghcr.io -u <user> --password-stdin   # токен с read:packages

EMAIL=you@example.com ./scripts/init-cert.sh      # первый сертификат (A-запись домена уже на сервер)
IMAGE_TAG=latest ./scripts/deploy.sh               # pull → миграции → up → проверка здоровья
docker compose -f compose.prod.yml --env-file .env exec api barber init --name "Barbershop"
docker compose -f compose.prod.yml --env-file .env exec api barber create-admin --login owner --role owner
docker compose -f compose.prod.yml --env-file .env exec api barber bot-setup --public-url https://$DOMAIN
(crontab -l; echo "0 3 * * * /opt/barber/scripts/backup.sh") | crontab -
```

Staging — то же самое на втором сервере или во втором каталоге со своим доменом.
Сертификаты продлевает сервис `certbot`. `deploy.sh` можно запускать повторно; он записывает
задеплоенный `IMAGE_TAG` в `.env`. Откат: `IMAGE_TAG=<предыдущий sha> ./scripts/deploy.sh`.

### Вариант B — Firebase Hosting + Cloud Run (britva-barber)

Схема: `https://britva-barber.web.app` отдаёт `/app/` и `/admin/` с CDN Firebase и
переписывает `/api/**` и `/media/**` → Cloud Run `barber-api`, `/api/v1/bot/**` → `barber-bot`.
База — Neon (PostgreSQL), Redis — Upstash, фото — приватный бакет Cloud Storage.
Настройки — `infra/cloudrun/config.env`, секреты — Secret Manager.

| Сервис Cloud Run         | Роль образа   | Доступ                                                                           |
| ------------------------ | ------------- | -------------------------------------------------------------------------------- |
| `barber-api`             | `api`         | публичный; WebSocket админки идёт сюда напрямую                                  |
| `barber-bot`             | `bot`         | публичный (вебхук Telegram через Firebase)                                       |
| `barber-worker`          | `worker-http` | только IAM; Cloud Scheduler: `/tasks/tick` раз в минуту, `/tasks/bonus` ежечасно |
| `barber-migrate` (job)   | `migrate`     | запускается при каждом деплое                                                    |
| `barber-bot-setup` (job) | `bot-setup`   | вебхук, команды и кнопка меню                                                    |

Особенности, которые учтены в коде:

- Firebase пропускает в Cloud Run только cookie `__session`, поэтому `COOKIE_MODE=session`
  хранит в ней access, refresh и CSRF. CSRF-токен клиент берёт из ответа login/refresh.
- Firebase не проксирует WebSocket. Админка получает одноразовый билет
  (`POST /admin/auth/ws-ticket`) и подключается к `wss://barber-api-….run.app` (`VITE_WS_URL`).
- Ответы `/api/**` идут с `Cache-Control: private, no-store`, чтобы CDN их не кешировал.
- Уведомления в Telegram уходят с задержкой до 1 минуты: воркер будит Cloud Scheduler.

Первый запуск:

1. Включите тариф **Blaze** у проекта `britva-barber` в консоли Firebase.
2. Создайте базу в [Neon](https://neon.tech) и Redis в [Upstash](https://upstash.com), оба в
   регионе Frankfurt (`eu-central-1`), рядом с Cloud Run `europe-west3`.
3. Выполните `gcloud auth login`, затем `infra/cloudrun/setup.sh`. Скрипт включит API, создаст
   реестр, сервисные аккаунты, бакет и секреты (`JWT_SECRET`, `WEBHOOK_SECRET` и `TASKS_TOKEN`
   генерирует сам) и напечатает команды для остальных секретов: `DATABASE_URL` (строка Neon с
   `-pooler`), `DATABASE_URL_DIRECT` (без `-pooler`), `REDIS_URL` (`rediss://…` из Upstash)
   и `BOT_TOKEN`.
4. Впишите `BOT_USERNAME` в `infra/cloudrun/config.env`.
5. Запустите `infra/cloudrun/deploy.sh`. Он собирает образ в Cloud Build и применяет
   миграции. Затем выкладывает сервисы, планировщик, Firebase Hosting и вебхук бота.
6. Создайте салон и владельца со своего компьютера по прямой строке Neon. Строку вставьте
   в терминал сами, в чат её не присылайте:

   ```bash
   cd backend
   export DATABASE_URL='<строка Neon без -pooler>' ENV=dev
   .venv/bin/barber init --name "Britva"
   .venv/bin/barber create-admin --login owner --role owner
   ```

`firebase deploy` проверяет, что сервисы Cloud Run уже существуют. Поэтому Hosting с этими
rewrites выкладывается только через `deploy.sh`, после сервисов. Повторный деплой выполняется
той же командой. Для отката выполните `TAG=<sha> SKIP_BOT_SETUP=1 infra/cloudrun/deploy.sh`,
если образ уже есть в реестре.

### CI/CD (GitHub Actions)

- **Pull request** (`ci.yml`, запускаются только задачи изменённых частей — `dorny/paths-filter`):
  бэкенд — ruff, mypy, pytest с PostgreSQL и Redis как services, `alembic check`;
  фронтенд — установка с кэшем pnpm, актуальность api-client, ESLint, Prettier, tsc, Vitest,
  сборка (с бюджетом бандла Mini App); Playwright e2e; сборка Docker-образов и `nginx -t`.
- **main** (`deploy-cloudrun.yml`): CI → `infra/cloudrun/deploy.sh` → проверка
  `/api/v1/health/live`. Нужен secret `GCP_SA_KEY` (ключ `barber-deploy@`, команду печатает
  `setup.sh`). Пока ключа нет, деплой пропускается.
- **Вручную** (`deploy.yml`, вариант A): сборка образов в GHCR → **staging** по SSH →
  **smoke**-тесты Playwright → **production** с подтверждением.

Настройки репозитория: environments `staging` и `production`; secrets `STAGING_HOST`,
`PRODUCTION_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `SMOKE_ADMIN_LOGIN`,
`SMOKE_ADMIN_PASSWORD` (отдельный аккаунт на staging); variables `STAGING_URL`, `PRODUCTION_URL`.

## Эксплуатация

- Логи в JSON (`docker compose logs -f api`). Каждый ответ несёт `X-Request-ID` — он же
  в логах API и в теле ошибки.
- Здоровье: `GET /api/v1/health/live`, `/api/v1/health/ready` (PostgreSQL + Redis), Nginx `/healthz`.
- Ошибки: `SENTRY_DSN` в `backend.env`.
- Бэкапы: `scripts/backup.sh` (pg_dump, хранится 14 дней). Восстановление:
  `gunzip -c backups/<файл>.sql.gz | docker compose -f compose.prod.yml exec -T postgres psql -U barber barber`.
