/**
 * Utilidades dos comandos `npm run` da raiz. Só Node puro (sem dependências),
 * para funcionar igual no Windows e no Linux antes mesmo do `npm install`.
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
export const BACKEND = join(ROOT, "backend");
export const FRONTEND = join(ROOT, "frontend");
export const VENV = join(ROOT, ".venv");
export const IS_WINDOWS = process.platform === "win32";

/** Python de dentro do venv da raiz. */
export const venvPython = join(VENV, IS_WINDOWS ? "Scripts/python.exe" : "bin/python");
// O npm é chamado pelo próprio Node (`npm_execpath`), SEM shell: com shell, no
// Windows, um argumento com espaço ("Minha Loja") viraria dois.
const npmCli = process.env.npm_execpath;
export const npmCmd = npmCli ? process.execPath : IS_WINDOWS ? "npm.cmd" : "npm";
const npmPrefix = npmCli ? [npmCli] : [];
export const npm = (args) => [npmCmd, [...npmPrefix, ...args]];

// Saída do Python em UTF-8 (o console do Windows trocaria os acentos).
const CHILD_ENV = { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" };

export function step(message) {
  console.log(`\n\x1b[36m▸ ${message}\x1b[0m`);
}

export function fail(message) {
  console.error(`\n\x1b[31m✖ ${message}\x1b[0m`);
  process.exit(1);
}

/** Executa e espera; aborta o comando inteiro se falhar. */
export function run(cmd, args, { cwd = ROOT, env } = {}) {
  const result = spawnSync(cmd, args, { cwd, stdio: "inherit", env: { ...CHILD_ENV, ...env } });
  if (result.status !== 0) fail(`Falhou: ${cmd} ${args.join(" ")}`);
}

/** Inicia em paralelo, com prefixo colorido em cada linha de saída. */
export function start(name, color, cmd, args, { cwd = ROOT } = {}) {
  const child = spawn(cmd, args, { cwd, env: CHILD_ENV });
  const prefix = `\x1b[${color}m[${name}]\x1b[0m `;
  const pipe = (stream, out) =>
    stream.on("data", (chunk) => {
      for (const line of chunk.toString().split(/\r?\n/)) if (line.trim()) out.write(prefix + line + "\n");
    });
  pipe(child.stdout, process.stdout);
  pipe(child.stderr, process.stderr);
  return child;
}

/** Garante que o ambiente existe antes dos comandos que dependem dele. */
export function requireSetup() {
  if (!existsSync(venvPython)) fail("Ambiente Python não encontrado. Rode primeiro: npm run setup");
  if (!existsSync(join(ROOT, ".env"))) fail("Arquivo .env não encontrado. Rode primeiro: npm run setup");
}

/** `python manage.py ...` com o Python do venv. */
export function manage(args, options) {
  run(venvPython, ["manage.py", ...args], { cwd: BACKEND, ...options });
}
