/**
 * Endereço pelo CEP com FALLBACK entre serviços públicos (o mesmo do frontend web): tenta um;
 * se cair, demorar (4 s) ou não achar, tenta o próximo. `null` = nenhum achou.
 */
export type CepAddress = { street: string; district: string; city: string; state: string; city_ibge: string; complement: string };

type Provider = { url: (cep: string) => string; read: (d: Record<string, unknown>) => CepAddress | null };
const text = (v: unknown) => (typeof v === "string" ? v.trim() : v == null ? "" : String(v));

const PROVIDERS: Provider[] = [
  { url: (c) => `https://viacep.com.br/ws/${c}/json/`,
    read: (d) => (d.erro ? null : { street: text(d.logradouro), district: text(d.bairro), city: text(d.localidade),
      state: text(d.uf), city_ibge: text(d.ibge), complement: text(d.complemento) }) },
  { url: (c) => `https://brasilapi.com.br/api/cep/v2/${c}`,
    read: (d) => (d.city ? { street: text(d.street), district: text(d.neighborhood), city: text(d.city), state: text(d.state),
      city_ibge: "", complement: "" } : null) },
  { url: (c) => `https://opencep.com/v1/${c}`,
    read: (d) => (d.error || !d.localidade ? null : { street: text(d.logradouro), district: text(d.bairro),
      city: text(d.localidade), state: text(d.uf), city_ibge: text(d.ibge), complement: text(d.complemento) }) },
  { url: (c) => `https://cep.awesomeapi.com.br/json/${c}`,
    read: (d) => (d.city ? { street: text(d.address), district: text(d.district), city: text(d.city), state: text(d.state),
      city_ibge: text(d.city_ibge), complement: "" } : null) },
];

const cache = new Map<string, CepAddress>();

export async function lookupCep(value: string): Promise<CepAddress | null> {
  const digits = value.replace(/\D/g, "");
  if (digits.length !== 8) return null;
  if (cache.has(digits)) return cache.get(digits)!;
  let found = null as CepAddress | null;
  for (const provider of PROVIDERS) {
    try {
      const response = await fetch(provider.url(digits), { signal: AbortSignal.timeout(4000) });
      const answer = response.ok ? provider.read(await response.json()) : null;
      if (!answer) continue;
      if (!found) found = answer;
      else if (answer.city_ibge) found = { ...found, city_ibge: answer.city_ibge }; // só completa o IBGE (NF-e)
      if (found.city_ibge) break;
    } catch {
      // fora do ar / sem rede: próximo serviço
    }
  }
  if (found) cache.set(digits, found);
  return found;
}
