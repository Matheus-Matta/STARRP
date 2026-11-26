/**
 * Arquivos do PDV na pasta de dados do app (%APPDATA%\Starrp PDV):
 *
 * - `readJson`/`writeJson`: dados comuns (catálogo offline, fila de envio). A gravação é
 *   atômica e vai até o disco (fsync + rename), em duas cópias (o arquivo e o `.bak`);
 * - `readSecret`/`writeSecret`: segredos (token do ACBr, kit fiscal com o certificado, notas),
 *   criptografados com o cofre do sistema (`safeStorage`/DPAPI) — só este usuário do Windows abre.
 * - arquivo ilegível NUNCA vira "vazio" em silêncio: a cópia estragada fica em `.corrupt-…`, a outra
 *   volta e o operador é avisado. Sem conseguir nem LER (arquivo preso por outro programa), a operação
 *   falha com erro em vez de gravar por cima (as vendas da fila sumiriam).
 */
import { closeSync, copyFileSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, rmSync, writeSync } from "node:fs";
import { dirname, join } from "node:path";

import { app, safeStorage } from "electron";

const path = (name: string) => join(app.getPath("userData"), name);

function writeAtomic(name: string, content: Buffer | string) {
  const target = path(name);
  mkdirSync(dirname(target), { recursive: true });
  const data = Buffer.isBuffer(content) ? content : Buffer.from(content, "utf8");
  writeThrough(target, data);
  writeThrough(`${target}.bak`, data);
}

function writeThrough(target: string, data: Buffer) {
  const temp = `${target}.tmp`;
  const fd = openSync(temp, "w");
  try {
    for (let done = 0; done < data.length;) done += writeSync(fd, data, done);
    fsyncSync(fd); // sem isto, queda de luz logo depois deixa o arquivo novo zerado
  } finally {
    closeSync(fd);
  }
  renameSync(temp, target);
}

let onProblem: (message: string) => void = () => undefined;
export const onStorageProblem = (listener: (message: string) => void) => {
  onProblem = listener;
};

/** Antivírus/backup seguram o arquivo por instantes: tenta de novo antes de desistir. */
function readBytes(file: string): Buffer {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return readFileSync(file);
    } catch (error) {
      if (attempt >= 4) throw error;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 50 * (attempt + 1));
    }
  }
}

/** Lê e interpreta; estragado → guarda a cópia em `.corrupt-…` e volta para a cópia (`.bak`). */
function load<T>(name: string, fallback: T, parse: (raw: Buffer) => T): T {
  const target = path(name);
  const backup = `${target}.bak`;
  if (!existsSync(target) && !existsSync(backup)) return fallback;
  if (existsSync(target)) {
    const raw = readBytes(target);
    try {
      return parse(raw);
    } catch {
      renameSync(target, `${target}.corrupt-${Date.now()}`);
    }
  }
  if (existsSync(backup)) {
    const raw = readBytes(backup);
    try {
      const value = parse(raw);
      copyFileSync(backup, target);
      onProblem(`O arquivo ${name} estava estragado: voltou a cópia de segurança. Confira as últimas vendas e notas deste PC.`);
      return value;
    } catch {
      renameSync(backup, `${backup}.corrupt-${Date.now()}`);
    }
  }
  onProblem(`O arquivo ${name} não pôde ser lido e recomeçou vazio. O original ficou guardado na pasta de dados do PDV (.corrupt): chame o suporte antes de continuar.`);
  return fallback;
}

export const readJson = <T>(name: string, fallback: T): T => load(name, fallback, (raw) => JSON.parse(raw.toString("utf8")) as T);

export const writeJson = (name: string, value: unknown) => writeAtomic(name, JSON.stringify(value));

export function readSecret<T>(name: string, fallback: T): T {
  const plain = (raw: Buffer) => JSON.parse(raw.toString("utf8")) as T; // gravado sem o cofre do sistema
  if (!safeStorage.isEncryptionAvailable()) {
    // Cofre fechado (chaveiro do Linux): o arquivo está bom, só não dá para abrir AGORA. Nunca vira ".corrupt".
    if (!hasFile(name)) return fallback;
    try {
      return plain(readBytes(existsSync(path(name)) ? path(name) : `${path(name)}.bak`));
    } catch {
      throw new Error("O cofre de senhas do sistema está bloqueado: desbloqueie-o e abra o PDV de novo.");
    }
  }
  return load(name, fallback, (raw) => {
    let text: string;
    try {
      text = safeStorage.decryptString(raw);
    } catch {
      return plain(raw);
    }
    return JSON.parse(text) as T;
  });
}

export function writeSecret(name: string, value: unknown) {
  const text = JSON.stringify(value);
  writeAtomic(name, safeStorage.isEncryptionAvailable() ? safeStorage.encryptString(text) : Buffer.from(text, "utf8"));
}

export const hasFile = (name: string) => existsSync(path(name)) || existsSync(`${path(name)}.bak`);
export function removeFile(name: string) {
  rmSync(path(name), { force: true });
  rmSync(`${path(name)}.bak`, { force: true });
}
