// Fails the build when the first screen (entry chunk + its static imports + CSS) exceeds the
// budget. Lazy step chunks are not part of the first screen.
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const BUDGET_KB = 200;
const dist = resolve(dirname(fileURLToPath(import.meta.url)), "../dist");
const manifest = JSON.parse(readFileSync(join(dist, ".vite/manifest.json"), "utf8"));

const entry = Object.values(manifest).find((chunk) => chunk.isEntry);
const seen = new Set();
const files = [];
(function walk(chunk) {
  if (seen.has(chunk.file)) return;
  seen.add(chunk.file);
  files.push(chunk.file, ...(chunk.css ?? []));
  for (const key of chunk.imports ?? []) walk(manifest[key]);
})(entry);

let total = 0;
for (const file of new Set(files)) {
  const size = gzipSync(readFileSync(join(dist, file))).length;
  total += size;
  console.log(`${(size / 1024).toFixed(1).padStart(7)} KB  ${file}`);
}
const lazy = Object.values(manifest).filter((c) => c.isDynamicEntry).length;
console.log(
  `first screen: ${(total / 1024).toFixed(1)} KB gzip (budget ${BUDGET_KB} KB), lazy chunks: ${lazy}`,
);
if (total / 1024 > BUDGET_KB) {
  console.error("bundle budget exceeded");
  process.exit(1);
}
