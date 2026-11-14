// Dev only: sign Telegram initData with the *dev* bot token from backend/.env so the
// Mini App can run in a normal browser against the local backend. Writes .env.development.local.
// Never use a production token here.
import { createHmac } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const backendEnv = resolve(here, "../../../backend/.env");

function readToken() {
  if (process.env.BOT_TOKEN) return process.env.BOT_TOKEN;
  if (existsSync(backendEnv)) {
    const line = readFileSync(backendEnv, "utf8")
      .split("\n")
      .find((l) => l.startsWith("BOT_TOKEN="));
    if (line) return line.slice("BOT_TOKEN=".length).trim();
  }
  throw new Error("BOT_TOKEN is not set (env or backend/.env)");
}

const token = readToken();
const userId = Number(process.env.DEV_TELEGRAM_ID ?? 777000);
const fields = {
  auth_date: String(Math.floor(Date.now() / 1000)),
  query_id: "AAHdev",
  // Telegram also sends an Ed25519 `signature`; the SDK requires the field to exist.
  // It is part of the HMAC data-check-string like any other field.
  signature: "dev",
  user: JSON.stringify({
    id: userId,
    first_name: process.env.DEV_FIRST_NAME ?? "Dev",
    last_name: "User",
    username: "dev_user",
    language_code: process.env.DEV_LANG ?? "ru",
  }),
};
if (process.env.DEV_START_PARAM) fields.start_param = process.env.DEV_START_PARAM;

const check = Object.keys(fields)
  .sort()
  .map((k) => `${k}=${fields[k]}`)
  .join("\n");
const secret = createHmac("sha256", "WebAppData").update(token).digest();
const hash = createHmac("sha256", secret).update(check).digest("hex");
const initData = new URLSearchParams({ ...fields, hash }).toString();

writeFileSync(resolve(here, "../.env.development.local"), `VITE_DEV_INIT_DATA=${initData}\n`);
console.log(`signed initData for user ${userId} → .env.development.local (valid 24 h)`);
