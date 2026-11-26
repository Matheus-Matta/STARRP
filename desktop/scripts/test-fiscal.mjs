// Nota fiscal e arquivos do PDV: o que não pode perder venda nem emitir a mesma venda duas vezes (D4-01..D4-03).
//   npm run test:fiscal
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "rolldown";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const cache = join(root, "node_modules", ".cache");
mkdirSync(cache, { recursive: true });
const load = async (input, name, plugins = []) => {
  const file = join(cache, name);
  await build({ input, platform: "node", logLevel: "silent", plugins, output: { file, format: "esm" } });
  return import(`${pathToFileURL(file).href}?${Date.now()}`);
};

/* ── núcleo fiscal ───────────────────────────────────────────────────────── */
const shared = join(root, "..", "shared", "fiscal").replaceAll("\\", "/");
const entry = join(cache, "fiscal-entry.ts");
writeFileSync(entry, `export * from "${shared}/engine"; export * from "${shared}/transport"; export { accessKey, lineTotal } from "${shared}/document";`);
const { createFiscal, CommunicatorUnavailable, accessKey, lineTotal } = await load(entry, "fiscal-test.mjs");

const kit = (storeId, series, next, issuer = {}) => ({
  environment: "2", issuer: { state: "SP", cnpj: "11222333000181", legal_name: "X", city_ibge: "3550308", ...issuer }, simple: true,
  offline_contingency: true, certificate: { valid_until: null }, portal_url: "", default_profile: "p", generated_at: "", storeId,
  series: { 65: { series, next_number: next }, 55: { series, next_number: 1 } }, profiles: { p: { cfop: "5102", csosn: "102" } },
  variants: { v: { ncm: "61091000", cest: "", origin: "0", type: "product", profile: "p", barcode: "" } },
});
const sale = (id) => ({
  id, number: 1, total: "10.00", change_amount: "0", discount: "0", freight: "0",
  items: [{ id: "i1", status: "active", variant: "v", sku: "S", description: "Camiseta", quantity: "1", unit_price: "10.00", total: "10.00", unit: "UN" }],
  payments: [{ method_kind: "cash", method_name: "Dinheiro", amount: "10.00", status: "approved" }],
});
const field = (ini, name) => new RegExp(`^${name}=(.*)$`, "m").exec(ini)?.[1];

/** PDV com um arquivo por filial (como o desktop) e um comunicador de mentira. */
function pdv(answer, post = async () => ({ ok: false, status: 0, data: null })) {
  const disk = {};
  let store = "A";
  const slot = () => (disk[store] ??= { kit: null, numbers: { series: {}, next: {}, bySale: {} }, invoices: [] });
  const calls = [];
  const kits = { A: kit("A", 2, 10), B: kit("B", 2, 1, { state: "RJ", cnpj: "99888777000166" }) };
  const engine = createFiscal({
    storage: {
      kit: () => slot().kit, saveKit: (k) => { slot().kit = k; },
      numbers: () => structuredClone(slot().numbers), saveNumbers: (n) => { slot().numbers = structuredClone(n); },
      invoices: () => slot().invoices, saveInvoices: (i) => { slot().invoices = i; },
    },
    server: { get: async () => ({ ok: true, status: 200, data: kits[store] }), post },
    transport: { kind: "local", health: async () => ({ ok: true }), call: async (path, body) => { calls.push({ path, body }); return answer(path, body); } },
    storeId: () => store, installationId: () => "pc",
  });
  const emit = (ref, extra = {}) => engine.emit({ sale: sale(ref), model: "65", saleRef: ref, ...extra }, { contingency: true });
  return { engine, calls, slot, emit, use: (s) => { store = s; } };
}
const ok = (data) => ({ status: 200, trusted: true, data });
const down = { status: 503, trusted: true, data: { erro: "sem_comunicacao", mensagem: "SEFAZ fora" } };
const lost = () => { throw new CommunicatorUnavailable("tempo esgotado"); };
const asks = (path) => path.endsWith("consultar");

{ // resposta perdida e a nota SAIU: consulta a mesma chave e não reenvia
  const p = pdv((path) => (asks(path) ? ok({ situacao: "autorizada", protocolo: "1" }) : lost()));
  await p.engine.refreshKit();
  assert.equal((await p.emit("off:a")).ok, false);
  const ini = p.calls[0].body.ini;
  const again = await p.emit("off:a", { saleId: "srv-1" });
  assert.equal(again.ok, true, again.error);
  assert.deepEqual(p.calls.map((c) => c.path), ["/v1/nfe/emitir", "/v1/nfe/consultar"]);
  const key = p.calls[1].body.chave;
  assert.equal(key.length, 44);
  assert.equal(key.slice(0, 2), "35");
  assert.equal(key.slice(6, 20), "11222333000181");
  assert.equal(Number(key.slice(25, 34)), Number(field(ini, "nNF")));
  assert.equal(key.slice(35, 43), field(ini, "cNF"));
  assert.equal(again.invoice.saleId, "srv-1");
  assert.equal(again.invoice.access_key, key);
}
{ // resposta perdida e a nota NÃO saiu: reenvia com o mesmo número e o mesmo cNF
  let n = 0;
  const p = pdv((path) => (asks(path) ? ok({ situacao: "nao_encontrada" }) : n++ ? ok({ situacao: "autorizada", chave: "1" }) : lost()));
  await p.engine.refreshKit();
  await p.emit("off:a");
  assert.equal((await p.emit("off:a")).ok, true);
  const sent = p.calls.filter((c) => !asks(c.path)).map((c) => [field(c.body.ini, "nNF"), field(c.body.ini, "cNF")]);
  assert.deepEqual(sent[0], sent[1]);
}
// incerta + SEFAZ fora: NUNCA contingência nem reenvio (a normal pode ter sido autorizada)
for (const unsure of [lost, () => ({ status: 500, trusted: true, data: { erro: "incerto" } }), () => ({ status: 0, trusted: false, data: { erro: "sem_resposta" } })]) {
  let n = 0;
  const p = pdv((path) => (asks(path) ? down : n++ ? ok({ situacao: "contingencia", chave: "1", xml: "<x/>" }) : unsure()));
  await p.engine.refreshKit();
  await p.emit("off:a");
  assert.equal((await p.emit("off:a")).ok, false);
  assert.equal(p.calls.filter((c) => c.path.endsWith("emitir")).length, 1);
}
{ // comunicador fechado (nem saiu) não trava: depois, SEFAZ fora → contingência normal
  let n = 0;
  const p = pdv((_path, body) => {
    if (n++ === 0) throw new CommunicatorUnavailable("fechado", false);
    return body.tp_emis === "9" ? ok({ situacao: "contingencia", chave: "1", xml: "<x/>" }) : down;
  });
  await p.engine.refreshKit();
  await p.emit("off:a");
  assert.equal((await p.emit("off:a")).invoice?.status, "contingency");
}
{ // numeração, notas e contingência são da filial
  const p = pdv((path, body) => {
    if (!path.endsWith("emitir")) return ok({ situacao: "rejeitada" });
    return body.tp_emis === "9" ? ok({ situacao: "contingencia", chave: "1", xml: "<A/>" }) : down;
  });
  await p.engine.refreshKit();
  assert.equal((await p.emit("off:a1")).invoice.number, 10);
  p.use("B");
  await p.engine.refreshKit();
  await p.engine.transmitPending();
  assert.equal(p.calls.filter((c) => c.path.endsWith("transmitir")).length, 0);
  assert.equal((await p.emit("off:b1")).invoice.number, 1);
  p.use("A");
  await p.engine.refreshKit();
  assert.equal((await p.emit("off:a2")).invoice.number, 11);
}
{ // numeração perdida não repete o número de uma nota guardada
  const p = pdv(() => ok({ situacao: "autorizada", chave: "1" }));
  await p.engine.refreshKit();
  await p.emit("s1");
  p.slot().numbers = { series: {}, next: {}, bySale: {} };
  assert.equal((await p.emit("s2")).invoice.number, 11);
}
{ // nota que saiu depois do envio da venda continua pendente de registro; a que foi junto, não
  const p = pdv(() => ok({ situacao: "autorizada", chave: "1" }));
  await p.engine.refreshKit();
  const { invoice } = await p.emit("off:a");
  p.engine.linkInvoices("off:a", "srv-1");
  assert.deepEqual([p.slot().invoices[0].saleId, p.slot().invoices[0].synced], ["srv-1", false]);
  p.engine.linkInvoices("off:a", "srv-1", invoice.key);
  assert.equal(p.slot().invoices[0].synced, true);
}
for (const status of [403, 404]) { // recusa ao registrar que não é definitiva
  const p = pdv(() => ok({ situacao: "autorizada", chave: "1" }), async () => ({ ok: false, status, data: null }));
  await p.engine.refreshKit();
  await p.emit("srv-1");
  assert.equal(await p.engine.registerInvoice(p.slot().invoices[0]), false);
  assert.equal(p.slot().invoices[0].synced, false);
}
{ // 200 com corpo cortado não é decisão: consulta antes de reenviar, e nunca contingência
  const p = pdv((path) => (asks(path) ? down : { status: 200, trusted: true, data: {} }));
  await p.engine.refreshKit();
  await p.emit("off:a");
  assert.equal((await p.emit("off:a")).ok, false);
  assert.deepEqual(p.calls.map((c) => c.path), ["/v1/nfe/emitir", "/v1/nfe/consultar"]);
  const { localTransport } = await import(`${pathToFileURL(join(cache, "fiscal-test.mjs")).href}?t`);
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response('{"situacao": "autor', { status: 200 });
  assert.equal((await localTransport(() => ({ url: "http://x", token: "t" })).call("/v1/nfe/emitir", {})).trusted, false);
  globalThis.fetch = original;
}
{ // nota emitida por versão antiga (id do servidor) não é emitida de novo pelo id local
  const p = pdv(() => ok({ situacao: "autorizada", chave: "1" }));
  await p.engine.refreshKit();
  await p.emit("srv-1");
  assert.equal((await p.emit("off:l", { saleId: "srv-1" })).invoice.number, 10);
  assert.equal(p.calls.length, 1);
}
{ // clique duplo: uma emissão só
  const p = pdv(() => ok({ situacao: "autorizada", chave: "1" }));
  await p.engine.refreshKit();
  await Promise.all([p.emit("off:a"), p.emit("off:a")]);
  assert.equal(p.calls.length, 1);
}
assert.equal(lineTotal(0.045, 53), 2.39); // meio centavo: igual ao servidor
assert.equal(lineTotal(3, 10.1), 30.3);
// cadastro sem o IBGE da cidade: sem chave (não inventa)
assert.equal(accessKey({ issuer: { cnpj: "11222333000181" }, model: "65", series: 1, number: 1, cNF: "1", issuedAt: new Date() }), null);

/* ── pré-venda ───────────────────────────────────────────────────────────── */
const presale = await load(join(root, "src/renderer/src/pdv/presale.ts"), "presale-test.mjs", [{
  name: "alias", resolveId: (id) => (id.startsWith("@/") ? join(root, "src/renderer/src", `${id.slice(2)}.ts`) : null),
}]);
{ // o serviço vai no QR ligado ao item dele, mesmo listado antes
  const row = (id, parent, price) => ({ id, parent_item: parent, variant: id, quantity: "1", unit_price: price, discount: "0", description: id, status: "active" });
  const code = await presale.encodePresale({ id: "off:1", number: 1, seller: 1, seller_name: "V", customer: null, customer_name: "", discount: "0",
    total: "150", created_at: "", items: [row("montagem", "roupeiro", "50"), row("roupeiro", null, "100"), { ...row("x", null, "9"), status: "cancelled" }] });
  assert.ok(presale.isPresaleCode(code));
  assert.deepEqual((await presale.decodePresale(code)).items.map((i) => [i.variant, i.parent]), [["roupeiro", null], ["montagem", 0]]);
}

/* ── arquivos ────────────────────────────────────────────────────────────── */
const data = mkdtempSync(join(tmpdir(), "starrp-pdv-"));
const electron = {
  name: "electron",
  resolveId: (id) => (id === "electron" ? "\0electron" : null),
  load: (id) => (id === "\0electron" ? `export const app = { getPath: () => ${JSON.stringify(data)} };
    export const safeStorage = { isEncryptionAvailable: () => true, encryptString: (t) => Buffer.from("c:" + t),
      decryptString: (b) => { const t = b.toString(); if (!t.startsWith("c:")) throw new Error("DPAPI"); return t.slice(2); } };` : null),
};
const files = await load(join(root, "src/main/files.ts"), "files-test.mjs", [electron]);
const alerts = [];
files.onStorageProblem((message) => alerts.push(message));
const queue = [{ id: "v1" }, { id: "v2" }, { id: "v3" }];
assert.deepEqual(files.readJson("outbox.json", []), []);
files.writeJson("outbox.json", queue);
writeFileSync(join(data, "outbox.json"), Buffer.alloc(200)); // queda de energia: arquivo zerado
assert.deepEqual(files.readJson("outbox.json", []), queue);
files.writeJson("outbox.json", [...files.readJson("outbox.json", []), { id: "v4" }]);
assert.equal(JSON.parse(readFileSync(join(data, "outbox.json"), "utf8")).length, 4);
assert.equal(alerts.length, 1);
files.writeSecret("notas.bin", [1]);
for (const name of ["notas.bin", "notas.bin.bak"]) writeFileSync(join(data, name), "lixo");
assert.deepEqual(files.readSecret("notas.bin", []), []);
assert.equal(alerts.length, 2);
assert.equal(readdirSync(data).filter((name) => name.startsWith("notas") && name.includes(".corrupt-")).length, 2); // nada se perde
rmSync(data, { recursive: true, force: true });

console.log("✓ nota sem duplicar (resposta perdida), numeração por filial e fila que sobrevive a arquivo estragado.");
