import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";

import { toApiError } from "@/api/errors";
import { products } from "@/resources/catalog";
import { customers } from "@/resources/partners";
import { documentError, formatDocument } from "@/utils/documents";
import { date, money, toDecimal } from "@/utils/format";
import { validate } from "@/utils/validation";

describe("documentos", () => {
  it("aceita CPF e CNPJ válidos e recusa dígito verificador errado", () => {
    expect(documentError("529.982.247-25")).toBeNull();
    expect(documentError("11.222.333/0001-81")).toBeNull();
    expect(documentError("529.982.247-26")).toBe("CPF inválido.");
    expect(documentError("111.111.111-11")).toBe("CPF inválido.");
    expect(documentError("123")).toBe("CPF tem 11 dígitos e CNPJ tem 14.");
  });

  it("formata para exibição", () => {
    expect(formatDocument("52998224725")).toBe("529.982.247-25");
  });
});

describe("formatação", () => {
  it("dinheiro em reais e decimal de volta como texto (sem float na ida e volta)", () => {
    expect(money("45.9").replace(/\s/g, " ")).toBe("R$ 45,90");
    expect(toDecimal("12,5")).toBe("12.50");
    expect(toDecimal("")).toBeNull();
  });

  it("data pura não volta um dia por fuso", () => {
    expect(date("2026-10-21")).toBe("21/10/2026");
  });
});

describe("validação gerada do cadastro", () => {
  it("exige os obrigatórios e ignora campo escondido", () => {
    const errors = validate(products.fields, { name: "", type: "simple", variants: [{ sku: "X", price: null }] });
    expect(errors.name).toBe("Campo obrigatório.");
    expect(errors.variants).toBe("Informe o preço de todas as variantes.");
    // A grade só aparece em produto com variação: não é validada escondida.
    expect(errors.grid).toBeUndefined();
  });

  it("confere o CPF/CNPJ do cliente", () => {
    expect(validate(customers.fields, { name: "Ana", document: "12345678900" }).document).toBe("CPF inválido.");
  });
});

describe("erro da API", () => {
  function axiosError(status: number, data: unknown) {
    const headers = new AxiosHeaders();
    return new AxiosError("x", "ERR", { headers }, null, { status, data, statusText: "", headers, config: { headers } });
  }

  it("traduz o envelope com erros por campo", () => {
    const error = toApiError(axiosError(400, {
      success: false, status_code: 400, error: { code: "invalid", message: { sku: ["Já existe."], items: { quantity: ["Inválida"] } } },
    }));
    expect(error.fields).toEqual({ sku: "Já existe.", "items.quantity": "Inválida" });
    expect(error.message).toBe("Já existe.");
  });

  it("reconhece pedido de autorização de gerente", () => {
    const error = toApiError(axiosError(403, { error: { code: "discount_approval_required", message: "Acima do limite" } }));
    expect(error.needsApproval).toBe(true);
  });

  it("sem resposta vira erro de rede legível", () => {
    expect(toApiError(new Error("boom")).code).toBe("network");
  });
});
