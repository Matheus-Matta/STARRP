/**
 * Arquivos do PDV na pasta de dados do app (%APPDATA%\Starrp PDV):
 *
 * - `readJson`/`writeJson`: dados comuns (catálogo offline, fila de envio). A gravação é
 *   atômica (arquivo temporário + rename): faltou luz no meio, o arquivo anterior continua inteiro;
 * - `readSecret`/`writeSecret`: segredos (token do ACBr, kit fiscal com o certificado, notas),
 *   criptografados com o cofre do sistema (`safeStorage`/DPAPI) — só este usuário do Windows abre.
 */
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { app, safeStorage } from "electron";

const path = (name: string) => join(app.getPath("userData"), name);

function writeAtomic(name: string, content: Buffer | string) {
  const target = path(name);
  mkdirSync(dirname(target), { recursive: true });
  const temp = `${target}.tmp`;
  writeFileSync(temp, content);
  renameSync(temp, target);
}

export function readJson<T>(name: string, fallback: T): T {
  try {
    return existsSync(path(name)) ? (JSON.parse(readFileSync(path(name), "utf8")) as T) : fallback;
  } catch {
    return fallback;
  }
}

export const writeJson = (name: string, value: unknown) => writeAtomic(name, JSON.stringify(value));

export function readSecret<T>(name: string, fallback: T): T {
  try {
    if (!existsSync(path(name))) return fallback;
    const raw = readFileSync(path(name));
    const text = safeStorage.isEncryptionAvailable() ? safeStorage.decryptString(raw) : raw.toString("utf8");
    return JSON.parse(text) as T;
  } catch {
    return fallback; // de outro usuário do Windows ou corrompido
  }
}

export function writeSecret(name: string, value: unknown) {
  const text = JSON.stringify(value);
  writeAtomic(name, safeStorage.isEncryptionAvailable() ? safeStorage.encryptString(text) : Buffer.from(text, "utf8"));
}

export const removeFile = (name: string) => rmSync(path(name), { force: true });
