// Regras de segurança do PDV que não dependem do Electron: o endereço do servidor (HTTPS no app instalado).
//   npm run test:security
import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "rolldown";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "node_modules", ".cache", "security-test.mjs");
await build({ input: join(root, "src/shared/serverUrl.ts"), platform: "node", logLevel: "silent", output: { file: out, format: "esm" } });
const { serverUrlProblem, normalizeServerUrl, acbrUrlProblem } = await import(pathToFileURL(out).href);

const ok = (url, production) => assert.equal(serverUrlProblem(url, production), null, `${url} deveria valer`);
const bad = (url, production) => assert.notEqual(serverUrlProblem(url, production), null, `${url} deveria ser recusado`);

ok("https://app.loja.com.br", true);
ok("https://app.loja.com.br/", true);
ok("http://localhost:8001", true);
ok("http://127.0.0.1:8001", true);
bad("http://192.168.0.10:8001", true); // rede da loja sem criptografia: não no app instalado
ok("http://192.168.0.10:8001", false); // desenvolvimento
bad("ftp://app.loja.com.br", false);
bad("https://app.loja.com.br/api/v1", true); // só a origem
bad("não é url", false);
assert.equal(normalizeServerUrl("  https://a.com// "), "https://a.com");
// Comunicador fiscal: só neste PC (recebe o certificado A1) — S-14.
assert.equal(acbrUrlProblem("http://127.0.0.1:8030"), null);
assert.equal(acbrUrlProblem("http://localhost:8030"), null);
assert.notEqual(acbrUrlProblem("http://192.168.0.50:8030"), null);
assert.notEqual(acbrUrlProblem("https://atacante.example:8030"), null);
console.log("✓ endereço do servidor: https no app instalado; comunicador fiscal só neste PC.");
