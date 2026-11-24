/**
 * Access + refresh token do operador, guardados criptografados com o cofre do sistema
 * (`safeStorage`: DPAPI no Windows). Ficam só no processo principal: o renderer nunca os lê.
 */
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { app, safeStorage } from "electron";

export type Tokens = { access: string; refresh: string };

const file = () => join(app.getPath("userData"), "session.bin");
let tokens: Tokens | null = null;
let loaded = false;

export function readTokens(): Tokens | null {
  if (loaded) return tokens;
  loaded = true;
  try {
    if (!existsSync(file())) return null;
    const raw = readFileSync(file());
    if (!safeStorage.isEncryptionAvailable() && app.isPackaged) return null;
    const text = safeStorage.isEncryptionAvailable() ? safeStorage.decryptString(raw) : raw.toString("utf8");
    const parsed = JSON.parse(text) as Partial<Tokens>;
    tokens = parsed.access && parsed.refresh ? { access: parsed.access, refresh: parsed.refresh } : null;
  } catch {
    tokens = null; // arquivo de outro usuário do Windows ou corrompido: pede login de novo
  }
  return tokens;
}

export function saveTokens(next: Tokens) {
  tokens = next;
  loaded = true;
  const text = JSON.stringify(next);
  mkdirSync(dirname(file()), { recursive: true });
  if (!safeStorage.isEncryptionAvailable()) {
    // Sem o cofre do sistema, o token NUNCA vai aberto para o disco no app instalado: fica só na
    // memória (fechou o PDV, pede login de novo). Em desenvolvimento grava aberto para agilizar.
    if (app.isPackaged) return rmSync(file(), { force: true });
    writeFileSync(file(), Buffer.from(text, "utf8"));
    return;
  }
  writeFileSync(file(), safeStorage.encryptString(text));
}

export function clearTokens() {
  tokens = null;
  loaded = true;
  rmSync(file(), { force: true });
}
