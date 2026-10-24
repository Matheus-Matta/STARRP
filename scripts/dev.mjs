/**
 * `npm run dev` — sobe backend (:8000) e frontend (:5173) juntos, com a saída
 * de cada um prefixada. Ctrl+C derruba os dois; se um cair, o outro também cai
 * (meio ambiente de dev rodando engana mais do que ajuda).
 *
 * `npm run dev:backend` / `npm run dev:frontend` sobem só um deles.
 */
import { spawnSync } from "node:child_process";

import { BACKEND, FRONTEND, IS_WINDOWS, npm, requireSetup, start, venvPython } from "./lib.mjs";

requireSetup();
const only = process.argv[2]; // "backend" | "frontend" | undefined

const children = [];
if (only !== "frontend") {
  children.push(start("backend", "33", venvPython, ["manage.py", "runserver", "8000"], { cwd: BACKEND }));
}
if (only !== "backend") {
  children.push(start("frontend", "36", ...npm(["run", "dev"]), { cwd: FRONTEND }));
}

let stopping = false;
function stopAll(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode !== null) continue;
    // No Windows o processo vem por um shell: só o taskkill derruba a árvore inteira.
    if (IS_WINDOWS) spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    else child.kill("SIGINT");
  }
  process.exit(code);
}

for (const child of children) child.on("exit", (code) => stopAll(code ?? 0));
process.on("SIGINT", () => stopAll(0));
process.on("SIGTERM", () => stopAll(0));
