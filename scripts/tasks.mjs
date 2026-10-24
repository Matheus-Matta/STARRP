/**
 * Tarefas do dia a dia, todas pelo venv/npm da raiz:
 *
 *   npm run test                 backend (pytest) + frontend (vitest)
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
    run(venvPython, ["-m", "pytest", ...rest], { cwd: BACKEND });
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
