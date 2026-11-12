/**
 * Endereço pelo CEP direto do navegador (sem passar pelo backend), com FALLBACK entre serviços
 * públicos e gratuitos: tenta um; se cair, demorar (4 s) ou responder erro, tenta o próximo.
 *
 *   1. ViaCEP      viacep.com.br        (traz o código IBGE)
 *   2. BrasilAPI   brasilapi.com.br     (junta Correios e outros)
 *   3. OpenCEP     opencep.com          (traz o código IBGE)
 *   4. AwesomeAPI  cep.awesomeapi.com.br (traz o código IBGE)
 *
 * "CEP não existe" num serviço que respondeu certo ainda deixa os outros tentarem (bases
 * diferentes têm CEPs novos em tempos diferentes). `null` = nenhum achou.
 */
export type CepAddress = { street: string; district: string; city: string; state: string; city_ibge: string;
                           complement: string; source: string };

type Provider = { name: string; url: (cep: string) => string; read: (data: Record<string, unknown>) => CepAddress | null };

const text = (value: unknown) => (typeof value === "string" ? value.trim() : value == null ? "" : String(value));

export const CEP_PROVIDERS: Provider[] = [
  { name: "ViaCEP", url: (cep) => `https://viacep.com.br/ws/${cep}/json/`,
    read: (d) => (d.erro ? null : { street: text(d.logradouro), district: text(d.bairro), city: text(d.localidade),
                                    state: text(d.uf), city_ibge: text(d.ibge), complement: text(d.complemento), source: "ViaCEP" }) },
  { name: "BrasilAPI", url: (cep) => `https://brasilapi.com.br/api/cep/v2/${cep}`,
    read: (d) => (d.city ? { street: text(d.street), district: text(d.neighborhood), city: text(d.city), state: text(d.state),
                             city_ibge: "", complement: "", source: "BrasilAPI" } : null) },
  { name: "OpenCEP", url: (cep) => `https://opencep.com/v1/${cep}`,
    read: (d) => (d.error || !d.localidade ? null : { street: text(d.logradouro), district: text(d.bairro), city: text(d.localidade),
                                                     state: text(d.uf), city_ibge: text(d.ibge), complement: text(d.complemento),
                                                     source: "OpenCEP" }) },
  { name: "AwesomeAPI", url: (cep) => `https://cep.awesomeapi.com.br/json/${cep}`,
    read: (d) => (d.city ? { street: text(d.address), district: text(d.district), city: text(d.city), state: text(d.state),
                             city_ibge: text(d.city_ibge), complement: "", source: "AwesomeAPI" } : null) },
];

const TIMEOUT_MS = 4000;
const cache = new Map<string, CepAddress | null>();

async function ask(provider: Provider, cep: string, fetcher: typeof fetch): Promise<CepAddress | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetcher(provider.url(cep), { signal: controller.signal, headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    return provider.read(await response.json());
  } catch {
    return null; // fora do ar, sem internet, demorou: vai para o próximo
  } finally {
    clearTimeout(timer);
  }
}

/** Endereço do CEP; `null` se nenhum serviço achou. O resultado fica em cache na sessão. */
export async function lookupCep(cep: string, fetcher: typeof fetch = fetch): Promise<CepAddress | null> {
  const digits = cep.replace(/\D/g, "");
  if (digits.length !== 8) return null;
  if (cache.has(digits)) return cache.get(digits)!;
  let found = null as CepAddress | null;
  for (const provider of CEP_PROVIDERS) {
    const answer = await ask(provider, digits, fetcher);
    if (!answer) continue;
    if (!found) found = answer;
    // Achou sem o código IBGE (a NF-e precisa dele): o próximo serviço só completa o IBGE.
    else if (answer.city_ibge) found = { ...found, city_ibge: answer.city_ibge };
    if (found.city_ibge) break;
  }
  if (found) cache.set(digits, found); // não guarda o "não achei": pode ter sido a rede
  return found;
}
