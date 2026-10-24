/**
 * Máscaras de digitação (InputMask do PrimeVue: `9` = dígito, `?` = daqui em diante é opcional)
 * e a mesma formatação para MOSTRAR o valor guardado só com dígitos.
 *
 *   applyMask("01001000", MASKS.cep)  → "01001-000"
 *   applyMask("22021000", MASKS.ncm)  → "2202.10.00"
 */
export const MASKS = {
  cpf: "999.999.999-99",
  cnpj: "99.999.999/9999-99",
  /** Fixo (10 dígitos) ou celular (11): o 11º é opcional. */
  phone: "(99) 9999-9999?9",
  mobile: "(99) 99999-9999",
  cep: "99999-999",
  ncm: "9999.99.99",
  cest: "99.999.99",
  ibge: "9999999",
} as const;

/** Escreve os dígitos no desenho da máscara; sobra de máscara (parte opcional vazia) é cortada. */
export function applyMask(value: unknown, mask: string) {
  const digits = String(value ?? "").replace(/\D/g, "");
  if (!digits) return "";
  const pattern = mask.replace("?", "");
  let out = "";
  let index = 0;
  for (const char of pattern) {
    if (index >= digits.length) break;
    out += char === "9" ? digits[index++] : char;
  }
  return out;
}

/** Celular de 11 dígitos fica "(11) 98765-4321", não "(11) 9876-54321". */
export function formatPhone(value: unknown) {
  const digits = String(value ?? "").replace(/\D/g, "");
  return digits.length === 11 ? applyMask(digits, MASKS.mobile) : applyMask(digits, "(99) 9999-9999");
}

/** Endereço pelo CEP (ViaCEP, público e gratuito). `null` = CEP não existe ou serviço fora. */
export async function lookupCep(cep: string) {
  const digits = cep.replace(/\D/g, "");
  if (digits.length !== 8) return null;
  try {
    const response = await fetch(`https://viacep.com.br/ws/${digits}/json/`);
    const data = await response.json();
    if (!response.ok || data.erro) return null;
    return { street: data.logradouro, district: data.bairro, city: data.localidade, state: data.uf, city_ibge: data.ibge,
             complement: data.complemento } as Record<string, string>;
  } catch {
    return null;
  }
}
