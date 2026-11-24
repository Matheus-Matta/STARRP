import { afterEach, describe, expect, it } from "vitest";

import { findResource } from "@/resources";
import { isCostEntry, setSeesCosts } from "@/utils/costs";

describe("custo e margem só com catalog.view_costs", () => {
  afterEach(() => setSeesCosts(true));

  it("reconhece custo pela chave ou pelo rótulo, sem pegar cliente", () => {
    expect(isCostEntry({ key: "unit_cost", label: "Custo unit." })).toBe(true);
    expect(isCostEntry({ key: "gross_margin_percent", label: "x" })).toBe(true);
    expect(isCostEntry({ key: "x", label: "Menor preço com a margem mínima" })).toBe(true);
    expect(isCostEntry({ key: "customer_name", label: "Cliente" })).toBe(false);
    expect(isCostEntry({ key: "customers", label: "Clientes" })).toBe(false);
  });

  it("tira as colunas e itens de custo dos cadastros de quem não vê", () => {
    const keys = (name: string) => findResource(name)!.columns.map((c) => c.key);
    const allViews = (name: string) => (findResource(name)!.views ?? []).flatMap((v) => v.list?.columns ?? []);
    expect(allViews("produtos").some(isCostEntry)).toBe(true);
    expect(findResource("precificacao")!.columns.some(isCostEntry)).toBe(true);

    setSeesCosts(false);
    expect(keys("movimentacoes-de-estoque")).not.toContain("unit_cost");
    expect(allViews("produtos").some(isCostEntry)).toBe(false);
    const pricing = findResource("precificacao")!;
    expect(pricing.columns.some(isCostEntry)).toBe(false);
    const items = [...(pricing.display?.sections ?? []), ...(pricing.display?.aside ?? [])].flatMap((s) => s.items ?? []);
    expect(items.some(isCostEntry)).toBe(false);
    // Os campos do formulário ficam (entrada de estoque pede o custo da nota).
    expect(findResource("entradas-e-saidas")!.fields.length).toBeGreaterThan(0);
  });
});
