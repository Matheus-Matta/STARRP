/**
 * Tarefas do dia a dia, todas pelo venv/npm da raiz:
 *
 *   npm run test                 backend (pytest, em paralelo) + frontend (vitest)
 *   npm run test:migrations      aplica TODAS as migrations num banco limpo (os testes pulam as migrations)
 *   npm run lint                 ruff + eslint + checagem de tipos
 *   npm run build                build de produção do frontend
 *   npm run api:types            schema OpenAPI do backend → tipos TS do frontend
 *   npm run migrate              aplica migrations
 *   npm run makemigrations       gera migrations
 *   npm run manage -- <args>     qualquer comando do manage.py
 *   npm run account -- "Nome" --admin user --password senha
 */
import { BACKEND, FRONTEND, manage, npm, requireSetup, run, step, venvPython } from "./lib.mjs";

requireSetup();
const [task, ...rest] = process.argv.slice(2);

const tasks = {
  test() {
    step("Testes do backend");
    // Em paralelo (pytest-xdist): um processo por núcleo. `-n 0` nos argumentos roda em série.
    const parallel = rest.some((arg) => arg === "-n" || arg.startsWith("-n")) ? [] : ["-n", "auto"];
    run(venvPython, ["-m", "pytest", ...parallel, ...rest], { cwd: BACKEND });
    step("Testes do frontend");
    run(...npm(["test"]), { cwd: FRONTEND });
  },
  lint() {
    step("Lint do backend (ruff)");
    run(venvPython, ["-m", "ruff", "check", "."], { cwd: BACKEND });
    step("Lint do frontend (eslint)");
    run(...npm(["run", "lint"]), { cwd: FRONTEND });
    step("Tipos do frontend (vue-tsc)");
    run(...npm(["run", "typecheck"]), { cwd: FRONTEND });
  },
  build() {
    run(...npm(["run", "build"]), { cwd: FRONTEND });
  },
  "api:types"() {
    step("Gerando o schema OpenAPI do backend");
    manage(["spectacular", "--file", "schema.yml"]);
    step("Gerando os tipos TypeScript do frontend");
    run(...npm(["run", "api:types"]), { cwd: FRONTEND });
  },
  "test:migrations"() {
    // Os testes criam as tabelas direto dos models (--nomigrations, minutos mais rápido). Isto garante
    // que as migrations aplicam do zero (banco em memória das settings de teste, descartado no fim).
    step("Aplicando todas as migrations num banco limpo");
    manage(["migrate", "--noinput", "--settings=config.settings.test"]);
  },
  migrate: () => manage(["migrate", ...rest]),
  makemigrations: () => manage(["makemigrations", "starrp", ...rest]),
  manage: () => manage(rest),
  account: () => manage(["create_account", ...rest]),
};

const handler = tasks[task];
if (!handler) {
  console.error(`Tarefa desconhecida: ${task}. Opções: ${Object.keys(tasks).join(", ")}`);
  process.exit(1);
}
handler();
