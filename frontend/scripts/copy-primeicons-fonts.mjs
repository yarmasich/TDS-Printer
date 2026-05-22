import { cpSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dest = resolve(root, "public/fonts");
const srcDir = resolve(root, "node_modules/primeicons/fonts");

mkdirSync(dest, { recursive: true });
for (const ext of ["woff2", "woff"]) {
  cpSync(resolve(srcDir, `primeicons.${ext}`), resolve(dest, `primeicons.${ext}`));
}
