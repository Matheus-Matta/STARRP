import { describe, expect, it } from "vitest";

import type { CosmosStatus } from "@/api/cosmos";
import { suggestionsFor } from "@/components/cosmos/suggestions";

const status = (extra: Partial<CosmosStatus> = {}): CosmosStatus => ({
  enabled: true, model: "gpt", can_use: true, can_write: true, can_supervise: false, open_alerts: 0, ...extra,
});
const all = () => true;

describe("atalhos da Cosmos", () => {
  it("no máximo 4, sem repetir", () => {
    const out = suggestionsFor("/", status({ habits: ["sales", "stock", "products"] }), all);
    expect(out.length).toBeLessThanOrEqual(4);
    expect(new Set(out.map((s) => s.text)).size).toBe(out.length);
  });

  it("a tela aberta vem primeiro: registro aberto ganha 'confira este'", () => {
    const out = suggestionsFor("/cadastros/produtos/123", status(), all);
    expect(out[0]!.text).toMatch(/^Confira este produto/);
    expect(out.some((s) => s.text.includes("planilha"))).toBe(true);
  });

  it("segue o que a pessoa mais faz", () => {
    const out = suggestionsFor("/", status({ habits: ["finance"] }), all);
    expect(out[0]!.text).toContain("contas vencem");
  });

  it("respeita o perfil: sem gravar, sem supervisão e sem a área", () => {
    const out = suggestionsFor("/estoque", status({ can_write: false, habits: ["products"] }), (code) => code !== "stock.view");
    expect(out.some((s) => s.text.includes("estoque"))).toBe(false);
    expect(out.some((s) => s.text.includes("cadastrar"))).toBe(false);
    expect(out.some((s) => s.text.includes("equipe"))).toBe(false);
  });

  it("alertas abertos aparecem para quem supervisiona", () => {
    const out = suggestionsFor("/", status({ can_supervise: true, open_alerts: 3 }), all);
    expect(out[0]!.text).toContain("3 alertas abertos");
  });
});
