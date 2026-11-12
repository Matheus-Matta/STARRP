import { describe, expect, it } from "vitest";

import { lookupCep } from "@/utils/cep";

const json = (body: unknown, ok = true) => Promise.resolve({ ok, json: () => Promise.resolve(body) } as Response);

describe("busca de CEP com fallback", () => {
  it("o 1º serviço fora: usa o 2º e completa o IBGE pelo 3º", async () => {
    const called: string[] = [];
    const fetcher = ((url: string) => {
      called.push(new URL(url).host);
      if (url.includes("viacep")) return Promise.reject(new Error("fora do ar"));
      if (url.includes("brasilapi")) return json({ street: "Av. Paulista", neighborhood: "Bela Vista", city: "São Paulo", state: "SP" });
      if (url.includes("opencep")) return json({ localidade: "São Paulo", uf: "SP", ibge: "3550308" });
      return json({}, false);
    }) as typeof fetch;

    const found = await lookupCep("01310-100", fetcher);

    expect(found).toMatchObject({ street: "Av. Paulista", city: "São Paulo", state: "SP", city_ibge: "3550308", source: "BrasilAPI" });
    expect(called).toEqual(["viacep.com.br", "brasilapi.com.br", "opencep.com"]);
  });

  it("nenhum acha: null (e CEP incompleto nem consulta)", async () => {
    let calls = 0;
    const fetcher = (() => { calls++; return json({ erro: true }); }) as unknown as typeof fetch;

    expect(await lookupCep("99999999", fetcher)).toBeNull();
    expect(calls).toBe(4);
    expect(await lookupCep("123", fetcher)).toBeNull();
    expect(calls).toBe(4);
  });
});
