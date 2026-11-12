import { describe, expect, it } from "vitest";

import type { FieldDef } from "@/resources/types";
import { boundsOf, placeholderOf, unitOf } from "@/utils/fieldHints";
import { validate } from "@/utils/validation";

const field = (extra: Partial<FieldDef>): FieldDef => ({ name: "x", label: "X", type: "text", ...extra });

describe("unidade, limite e placeholder", () => {
  it("pega a unidade do rótulo", () => {
    expect(unitOf(field({ label: "Peso bruto (kg)" }))).toBe("kg");
    expect(unitOf(field({ label: "Prazo (dias úteis)" }))).toBe("dias");
    expect(unitOf(field({ label: "Tolerância (R$)" }))).toBeUndefined();
    expect(unitOf(field({ label: "Usos (0 = ilimitado)" }))).toBeUndefined();
  });

  it("placeholder pelo tipo e pelo nome", () => {
    expect(placeholderOf(field({ type: "money" }))).toBe("R$ 0,00");
    expect(placeholderOf(field({ type: "measure", label: "Altura (cm)" }))).toBe("0,0 cm");
    expect(placeholderOf(field({ name: "street" }))).toMatch(/Rua/);
    expect(placeholderOf(field({ name: "street", placeholder: "Meu" }))).toBe("Meu");
  });

  it("sem negativo e % até 100, salvo `signed`", () => {
    expect(boundsOf(field({ type: "percent" }))).toEqual({ min: 0, max: 100 });
    expect(boundsOf(field({ type: "money", signed: true })).min).toBeUndefined();
    const fields = [field({ name: "price", type: "money" }), field({ name: "rate", type: "percent" }),
                    field({ name: "balance", type: "money", signed: true })];
    expect(validate(fields, { price: "-1.00", rate: "120", balance: "-50" }))
      .toEqual({ price: "Não pode ser negativo.", rate: "Máximo 100 %." });
    expect(validate(fields, { price: "9.90", rate: "12.5", balance: null })).toEqual({});
  });
});
