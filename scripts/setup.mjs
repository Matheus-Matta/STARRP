/**
 * `npm run setup` — prepara tudo na raiz do projeto. Pode rodar de novo à vontade:
 * o que já existe é mantido (o .env nunca é sobrescrito).
 *
 *   1. acha um Python 3.12+ e cria o venv em ./.venv
 *   2. instala as dependências do backend (requirements/dev.txt)
 *   3. cria o ./.env a partir do .env.example, com DJANGO_SECRET_KEY aleatória
 *   4. instala as dependências do frontend
 *   5. aplica as migrations e o catálogo de permissões
 *
 * `npm run setup -- --demo` cria também a conta "Loja Demo" (admin / senha123).
 */
import { randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { BACKEND, FRONTEND, IS_WINDOWS, ROOT, VENV, fail, manage, npm, run, step, venvPython } from "./lib.mjs";

const MIN = [3, 12];

function pythonVersion(cmd, args) {
  const out = spawnSync(cmd, [...args, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"], { encoding: "utf8" });
  if (out.status !== 0) return null;
  const [major, minor] = out.stdout.trim().split(".").map(Number);
  return major > MIN[0] || (major === MIN[0] && minor >= MIN[1]) ? `${major}.${minor}` : null;
}

function findPython() {
  const candidates = IS_WINDOWS
    ? [["py", ["-3.12"]], ["py", ["-3"]], ["python", []]]
    : [["python3.12", []], ["python3", []], ["python", []]];
  for (const [cmd, args] of candidates) {
    const version = pythonVersion(cmd, args);
    if (version) return { cmd, args, version };
  }
  return fail(`Python ${MIN.join(".")} ou mais novo não encontrado. Instale em https://www.python.org/downloads/`);
}

function ensureEnv() {
  const target = join(ROOT, ".env");
  if (existsSync(target)) return console.log("  .env já existe — mantido como está.");
  copyFileSync(join(ROOT, ".env.example"), target);
  const secret = randomBytes(48).toString("base64url");
  const text = readFileSync(target, "utf8").replace(/^DJANGO_SECRET_KEY=.*$/m, `DJANGO_SECRET_KEY=${secret}`);
  writeFileSync(target, text);
  console.log("  .env criado com uma DJANGO_SECRET_KEY nova.");
}

if (!existsSync(venvPython)) {
  const python = findPython();
  step(`Criando o venv em ./.venv (Python ${python.version})`);
  run(python.cmd, [...python.args, "-m", "venv", VENV]);
} else {
  step("venv ./.venv já existe");
}

step("Instalando dependências do backend");
run(venvPython, ["-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"]);
run(venvPython, ["-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", join(BACKEND, "requirements/dev.txt")]);

step("Arquivo de ambiente (.env)");
ensureEnv();

step("Instalando dependências do frontend");
run(...npm(["install", "--no-fund", "--no-audit"]), { cwd: FRONTEND });

step("Preparando o banco de dados");
manage(["migrate", "--noinput"]);
manage(["sync_permissions"]);
manage(["ensure_system_data"]);

if (process.argv.includes("--demo")) {
  step('Criando a conta de demonstração "Loja Demo" (admin / senha123)');
  manage(["create_account", "Loja Demo", "--admin", "admin", "--password", "senha123", "--all-modules"]);
  step("Populando a demonstração (10+ registros por cadastro: lojas, produtos, vendas, financeiro, fiscal)");
  manage(["seed_demo", "--account", "loja-demo"]);
}

console.log("\n\x1b[32m✔ Pronto. Rode `npm run dev` e abra http://localhost:5173\x1b[0m");
