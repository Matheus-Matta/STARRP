// Confere se o app MONTA (build do bundle) para Android e iOS sem abrir o celular: roda o `expo export`
// e grava tudo em mobile/logs/build-<plataforma>-<data>.log. Erro de build (import quebrado, sintaxe, módulo que
// não existe) aparece aqui; erro que só acontece ao ABRIR o app aparece no terminal do `npm run mobile`
// (linhas "[starrp] ERRO ...").
//
// Uso: npm run check:build            (android)
//      npm run check:build -- ios     (ou "all")
import { spawn } from "node:child_process";
import { createWriteStream, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const which = process.argv[2] ?? "android";
const platforms = which === "all" ? ["android", "ios"] : [which];
const logs = join(root, "logs");
mkdirSync(logs, { recursive: true });
const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");

function run(platform) {
  return new Promise((resolve) => {
    const file = join(logs, `build-${platform}-${stamp}.log`);
    const out = createWriteStream(file);
    const dist = join(root, ".build-check", platform);
    rmSync(dist, { recursive: true, force: true });
    const started = Date.now();
    out.write(`# expo export --platform ${platform} (${new Date().toLocaleString("pt-BR")})\n\n`);
    const child = spawn("npx", ["expo", "export", "--platform", platform, "--output-dir", dist],
                        { cwd: root, shell: true, env: { ...process.env, CI: "1" } });
    let text = "";
    const tee = (chunk) => {
      text += chunk;
      out.write(chunk);
      process.stdout.write(chunk);
    };
    child.stdout.on("data", tee);
    child.stderr.on("data", tee);
    child.on("close", (code) => {
      const seconds = ((Date.now() - started) / 1000).toFixed(0);
      const errors = text.split(/\r?\n/).filter((l) => /error|erro|unable to resolve|failed|cannot find/i.test(l));
      const summary = code === 0
        ? `\n✔ ${platform}: build OK em ${seconds}s.`
        : `\n✖ ${platform}: build FALHOU (código ${code}) em ${seconds}s.\n${errors.slice(0, 20).join("\n")}`;
      out.end(`${summary}\n`);
      console.log(`${summary}\n  log: ${file}`);
      rmSync(dist, { recursive: true, force: true });
      resolve(code === 0);
    });
  });
}

let ok = true;
for (const platform of platforms) ok = (await run(platform)) && ok;
process.exit(ok ? 0 : 1);
