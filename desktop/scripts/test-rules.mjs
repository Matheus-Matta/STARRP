// Contrato de regras do PDV (lado do desktop): roda `shared/pdv-rules.cases.json` contra
// `src/renderer/src/pdv/rules.ts`. O backend roda os mesmos casos em
// `backend/starrp/tests/test_pdv_rules_parity.py`. Os dois têm que dar o mesmo resultado.
//   npm run test:rules
import { readFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "rolldown"; // já vem com o Vite (sem dependência nova)

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const out = join(root, "node_modules", ".cache", "rules-test.mjs");
await build({
  input: join(root, "src/renderer/src/pdv/rules.ts"), platform: "node", logLevel: "silent",
  output: { file: out, format: "esm" },
});
const rules = await import(pathToFileURL(out).href);
const cases = JSON.parse(readFileSync(join(root, "..", "shared", "pdv-rules.cases.json"), "utf8"));

const code = (action) => {
  try {
    action();
    return "ok";
  } catch (error) {
    return error.code ?? `exceção: ${error.message}`;
  }
};

const run = {
  open: (g) => {
    const reg = { id: "r1", name: "Caixa 01", in_use_by: null };
    const registers = g.register === "linked" ? [reg] : g.register === "inactive" ? [{ ...reg, is_active: false }]
      : g.register === "busy" ? [{ ...reg, in_use_by: "Gerente" }] : [];
    return code(() => rules.checkOpen(registers, g.has_session ? { status: "open" } : null, "r1", g.amount));
  },
  movement: (g) => code(() => rules.checkMovement({ status: g.closed ? "closed" : "open" }, g.kind, g.amount, Number(g.drawer))),
  close: (g) => code(() => rules.checkClose({ status: g.closed ? "closed" : "open", pending_movements: 0 }, g.counted, g.pending ?? 0)),
  sale: (g) => {
    const items = g.items.map((q) => ({ status: "active", quantity: q }));
    const total = g.items.reduce((s, q) => s + Number(q) * Number(g.price), 0).toFixed(2);
    const methods = g.payments.map((p, i) => ({ id: `m${i}`, name: p.kind, kind: p.kind, max_installments: p.max_installments ?? 1, requires_reference: Boolean(p.requires_reference) }));
    const boot = {
      rules: { require_open_cash_session: Boolean(g.require_cash), require_seller: Boolean(g.require_seller), require_payment_reference: Boolean(g.require_reference) },
      payment_methods: methods,
    };
    const payments = g.payments.map((p, i) => ({ method: `m${i}`, amount: p.amount, tendered: p.tendered, installments: p.installments ?? 1, nsu: p.nsu }));
    const sale = { items, total, seller: g.seller ? 1 : null, customer: null };
    return code(() => rules.checkSale(sale, payments, boot, g.no_session ? null : { status: "open" }, true));
  },
};

let failed = 0;
let total = 0;
for (const [kind, list] of Object.entries(cases)) {
  if (kind.startsWith("_")) continue;
  for (const c of list) {
    total += 1;
    const got = run[kind](c.given);
    if (got !== c.expect) {
      failed += 1;
      console.log(`✗ ${kind} · ${c.name}: esperado ${c.expect}, deu ${got}`);
    }
  }
}
rmSync(out, { force: true });
console.log(failed ? `${failed} de ${total} casos divergem do backend.` : `✓ ${total} casos iguais ao backend.`);
process.exit(failed ? 1 : 0);
