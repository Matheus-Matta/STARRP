import { describe, expect, it } from "vitest";

import type { FieldDef } from "@/resources/types";
import { FORMATS, maskError } from "@/utils/formats";
import { validate } from "@/utils/validation";

const field = (extra: Partial<FieldDef>): FieldDef => ({ name: "x", label: "X", type: "text", ...extra });

describe("formatos com máscara", () => {
  it("acusa valor incompleto e aceita o completo", () => {
    expect(maskError("0100", FORMATS.cep.mask, FORMATS.cep)).toMatch(/Incompleto: 8 dígitos/);
    expect(maskError("01001000", FORMATS.cep.mask, FORMATS.cep)).toBeNull();
    expect(maskError("", FORMATS.cep.mask, FORMATS.cep)).toBeNull();
  });

  it("telefone: fixo ou celular, DDD válido e celular com 9", () => {
    const check = (v: string) => maskError(v, FORMATS.phone.mask, FORMATS.phone);
    expect(check("1133334444")).toBeNull();
    expect(check("11987654321")).toBeNull();
    expect(check("11887654321")).toMatch(/Celular/);
    expect(check("0133334444")).toMatch(/DDD/);
    expect(check("113333")).toMatch(/10 a 11 dígitos/);
  });

  it("CFOP de venda e interestadual", () => {
    expect(maskError("5102", FORMATS.cfop.mask, FORMATS.cfop)).toBeNull();
    expect(maskError("1102", FORMATS.cfop.mask, FORMATS.cfop)).toMatch(/5, 6 ou 7/);
    expect(maskError("5102", FORMATS["cfop-interstate"].mask, FORMATS["cfop-interstate"])).toMatch(/começa com 6/);
  });

  it("chave de acesso confere o dígito verificador", () => {
    const key = "3519101234567800019955001000000001100000001";  // 43 dígitos
    let sum = 0;
    for (let i = 42, w = 2; i >= 0; i--, w = w === 9 ? 2 : w + 1) sum += Number(key[i]) * w;
    const dv = sum % 11 < 2 ? 0 : 11 - (sum % 11);
    const fmt = FORMATS["access-key"];
    expect(maskError(key + dv, fmt.mask, fmt)).toBeNull();
    expect(maskError(key + ((dv + 1) % 10), fmt.mask, fmt)).toMatch(/dígito verificador/);
  });

  it("CST de PIS/COFINS só da tabela", () => {
    expect(maskError("49", FORMATS["cst-pis"].mask, FORMATS["cst-pis"])).toBeNull();
    expect(maskError("48", FORMATS["cst-pis"].mask, FORMATS["cst-pis"])).toMatch(/inexistente/);
  });

  it("o formulário barra antes de enviar", () => {
    const fields = [field({ name: "ncm", format: "ncm" }), field({ name: "zip_code", type: "cep" }),
                    field({ name: "plu", format: "digits6" })];
    expect(validate(fields, { ncm: "2202", zip_code: "01001000", plu: "12" })).toEqual({ ncm: expect.stringMatching(/8 dígitos/) });
    expect(validate(fields, { ncm: "22021000", zip_code: "", plu: "" })).toEqual({});
  });
});
