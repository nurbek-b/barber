# Mini App

React 18 + Vite + TypeScript, Telegram SDK `@telegram-apps/sdk-react` v2, TanStack Query,
Zustand, Tailwind. Served by Nginx under `/app/`, API on the same origin under `/api/`.

## Run

```bash
pnpm install                          # from the repo root
pnpm --filter @barber/miniapp dev     # http://localhost:5173/app/ (proxies /api → :8000)
```

**Outside Telegram (dev):** the app mocks the Telegram environment when `VITE_DEV_INIT_DATA`
is set. Generate a signed initData with the _dev_ bot token from `backend/.env`:

```bash
pnpm --filter @barber/miniapp dev:init-data   # writes .env.development.local (valid 24 h)
```

Native MainButton/BackButton are replaced by in-page buttons when not running in Telegram.

**Inside Telegram:** expose the dev server over HTTPS (`cloudflared tunnel --url
http://localhost:5173` or `ngrok http 5173`), set `MINIAPP_URL` in the backend and run
`barber bot-setup --public-url <https url>` (details in the root README, stage 9).

## Checks

```bash
pnpm --filter @barber/miniapp test        # Vitest + Testing Library
pnpm --filter @barber/miniapp e2e         # Playwright, mocked API, mobile viewport
pnpm --filter @barber/miniapp build       # tsc + vite build + first-screen budget (200 KB gzip)
```

## Structure

```
src/telegram/   SDK wrapper (init, mock, buttons, haptics, signed contact) + React hooks
src/api.ts      typed client (@barber/api-client) + TanStack Query hooks, optimistic cancel
src/store/      booking draft (Zustand, sessionStorage)
src/pages/      Home, MyBookings, Bonus, booking/{Barber,Services,Time,Confirm,Done}Step
src/i18n.ts     ru / ky / en
```
