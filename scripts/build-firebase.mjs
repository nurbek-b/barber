// Builds both SPAs and assembles the Firebase Hosting folder:
//   firebase-public/app/   ← apps/miniapp/dist
//   firebase-public/admin/ ← apps/admin/dist
// Runs as firebase.json "predeploy"; `pnpm deploy:firebase` calls it too.
import { execSync } from "node:child_process";
import { cpSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "firebase-public");
const run = (cmd) => execSync(cmd, { cwd: root, stdio: "inherit" });

run("pnpm --filter @barber/miniapp build");
run("pnpm --filter @barber/admin build");
rmSync(out, { recursive: true, force: true });
cpSync(join(root, "apps/miniapp/dist"), join(out, "app"), { recursive: true });
cpSync(join(root, "apps/admin/dist"), join(out, "admin"), { recursive: true });
// manifests are build metadata, not content
rmSync(join(out, "app/.vite"), { recursive: true, force: true });
rmSync(join(out, "admin/.vite"), { recursive: true, force: true });
console.log(`firebase-public ready: ${out}`);
