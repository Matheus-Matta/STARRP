/**
 * Endereço do servidor do PDV. No app instalado (produção) é sempre HTTPS: o servidor redireciona
 * http → https, e o token do operador não pode trafegar aberto na rede da loja. `localhost` fica
 * liberado (backend no próprio PC, desenvolvimento).
 */
const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);

export function normalizeServerUrl(value: string) {
  return value.trim().replace(/\/+$/, "");
}

/** Problema do endereço, em texto para o operador; `null` = pode usar. */
export function serverUrlProblem(value: string, production: boolean): string | null {
  let url: URL;
  try {
    url = new URL(normalizeServerUrl(value));
  } catch {
    return "Endereço do servidor inválido (ex.: https://app.suaempresa.com.br).";
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return "O endereço do servidor começa com https://.";
  if (url.pathname !== "/" || url.search || url.hash) return "Informe só o endereço do servidor, sem caminho (ex.: https://app.suaempresa.com.br).";
  if (production && url.protocol === "http:" && !LOOPBACK.has(url.hostname)) {
    return "Use https:// — o PDV não envia a senha nem o login por conexão sem criptografia.";
  }
  return null;
}

/** Comunicador Fiscal DESKTOP: só neste PC (S-14). Ele recebe o certificado A1 e o CSC ao "gravar no
 *  comunicador": um endereço de fora mandaria o certificado para outra máquina. */
export function acbrUrlProblem(value: string): string | null {
  let url: URL;
  try {
    url = new URL(normalizeServerUrl(value));
  } catch {
    return "Endereço do comunicador inválido (ex.: http://127.0.0.1:8030).";
  }
  if (!LOOPBACK.has(url.hostname)) return "O comunicador fiscal precisa estar neste computador (127.0.0.1 ou localhost).";
  if (url.protocol !== "http:" && url.protocol !== "https:") return "O endereço do comunicador começa com http://.";
  return null;
}
