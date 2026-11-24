/**
 * Impressão do PDV: recibo, comprovantes do caixa e DANFE.
 *
 * - impressora do Windows: o HTML numa janela invisível → `webContents.print` (pelo nome,
 *   ou a padrão). Modo "perguntar" abre a janela de impressão do Windows;
 * - térmica na rede (IP:porta, normalmente 9100): o HTML é desenhado numa janela fora da tela,
 *   vira imagem e segue como raster ESC/POS (GS v 0) pelo TCP, com corte e, se pedido, o pulso
 *   da gaveta. Funciona em qualquer térmica ESC/POS sem driver no Windows. Modo "perguntar"
 *   confirma antes com uma caixa de diálogo.
 */
import { Socket } from "node:net";

import { BrowserWindow, dialog } from "electron";

import type { PrinterTarget, PrintJob, PrintResult, SystemPrinter } from "../shared/ipc";
import { getConfig } from "./config";

const MM_TO_PX = 96 / 25.4;
/** Pontos por linha da cabeça térmica (203 dpi). */
const DOTS: Record<number, number> = { 58: 384, 80: 576 };

export async function listPrinters(win: BrowserWindow | null): Promise<SystemPrinter[]> {
  if (!win) return [];
  const printers = await win.webContents.getPrintersAsync();
  return printers.map((p) => ({ name: p.name, displayName: p.displayName || p.name, isDefault: Boolean((p as { isDefault?: boolean }).isDefault) }));
}

const describe = (t: PrinterTarget) => (t.kind === "network" ? `${t.host}:${t.port}` : t.name || "impressora padrão do Windows");

export async function print(job: PrintJob, parent: BrowserWindow | null): Promise<PrintResult> {
  const config = getConfig().printing;
  const target = job.target ?? config[job.slot];
  const ask = config.mode === "ask" && !job.confirmed;
  const copies = Math.max(1, Math.min(job.copies ?? config.copies ?? 1, 9));
  try {
    if (target.kind === "network") {
      if (!target.host) return { ok: false, error: "Informe o IP da impressora de rede nas configurações." };
      if (ask && parent) {
        const answer = await dialog.showMessageBox(parent, {
          type: "question", buttons: ["Imprimir", "Cancelar"], defaultId: 0, cancelId: 1, title: "Imprimir",
          message: `${job.title ?? "Imprimir"} em ${describe(target)}?`,
        });
        if (answer.response === 1) return { ok: false, cancelled: true };
      }
      const image = await renderRaster(job.html, target.paper === 58 ? 58 : 80);
      const drawer = job.drawer && config.openDrawer;
      await sendRaw(target.host, target.port || 9100, escpos(image, copies, Boolean(drawer)));
      return { ok: true };
    }
    return await printSystem(job.html, target, !ask, copies);
  } catch (error) {
    return { ok: false, error: `${describe(target)}: ${error instanceof Error ? error.message : String(error)}` };
  }
}

/** Carrega o papel numa janela trancada: não navega nem abre outra (R2-26). */
async function load(win: BrowserWindow, html: string) {
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (event) => event.preventDefault());
  await win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
}

async function printSystem(html: string, target: PrinterTarget, silent: boolean, copies: number): Promise<PrintResult> {
  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, javascript: false } });
  try {
    await load(win, html);
    const roll = target.paper !== 210;
    return await new Promise((resolve) => {
      win.webContents.print(
        {
          silent, copies, printBackground: true,
          ...(target.name ? { deviceName: target.name } : {}),
          margins: { marginType: roll ? "none" : "default" },
          ...(roll ? { pageSize: { width: target.paper * 1000, height: 297_000 } } : { pageSize: "A4" as const }),
        },
        (ok, reason) => resolve(ok ? { ok } : { ok, error: reason, cancelled: /cancel/i.test(reason ?? "") }),
      );
    });
  } finally {
    win.destroy();
  }
}

type Raster = { width: number; height: number; bits: Buffer };

/** Desenha o HTML na largura da bobina e devolve a imagem em 1 bit (preto = 1). */
async function renderRaster(html: string, paper: 58 | 80): Promise<Raster> {
  const dots = DOTS[paper]!;
  const zoom = dots / (paper * MM_TO_PX);
  const win = new BrowserWindow({
    show: false, width: dots, height: 400, useContentSize: true,
    webPreferences: { offscreen: true, sandbox: true, contextIsolation: true },
  });
  try {
    await load(win, html);
    win.webContents.setZoomFactor(zoom);
    await new Promise((r) => setTimeout(r, 120));
    const cssHeight = Number(await win.webContents.executeJavaScript(
      "Math.ceil(Math.max(document.body.scrollHeight, document.documentElement.scrollHeight))"));
    const height = Math.min(Math.ceil(cssHeight * zoom) + 8, 12_000);
    win.setContentSize(dots, height);
    await new Promise((r) => setTimeout(r, 200));
    const shot = await win.webContents.capturePage({ x: 0, y: 0, width: dots, height });
    const size = shot.getSize();
    const bitmap = shot.resize({ width: dots, height: Math.round((size.height * dots) / size.width) }).toBitmap();
    const width = dots;
    const rows = bitmap.length / 4 / width;
    const bytesPerRow = width / 8;
    const bits = Buffer.alloc(bytesPerRow * rows);
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < width; x++) {
        const i = (y * width + x) * 4; // BGRA
        const lum = 0.114 * bitmap[i]! + 0.587 * bitmap[i + 1]! + 0.299 * bitmap[i + 2]!;
        if (lum < 150 && bitmap[i + 3]! > 0) bits[y * bytesPerRow + (x >> 3)]! |= 0x80 >> (x & 7);
      }
    }
    return { width, height: rows, bits: trimBottom(bits, bytesPerRow) };
  } finally {
    win.destroy();
  }
}

/** Corta o branco do fim (a janela é um pouco maior que o conteúdo). */
function trimBottom(bits: Buffer, bytesPerRow: number) {
  let rows = bits.length / bytesPerRow;
  while (rows > 1 && bits.subarray((rows - 1) * bytesPerRow, rows * bytesPerRow).every((b) => b === 0)) rows--;
  return bits.subarray(0, Math.min(bits.length, (rows + 16) * bytesPerRow));
}

function escpos(image: Raster, copies: number, drawer: boolean) {
  const bytesPerRow = image.width / 8;
  const rows = image.bits.length / bytesPerRow;
  const parts: Buffer[] = [Buffer.from([0x1b, 0x40])]; // ESC @: reinicia
  if (drawer) parts.push(Buffer.from([0x1b, 0x70, 0x00, 0x19, 0xfa])); // ESC p: pulso da gaveta
  for (let copy = 0; copy < copies; copy++) {
    // Faixas de até 255 linhas: algumas térmicas não aceitam um bloco maior de uma vez.
    for (let start = 0; start < rows; start += 255) {
      const band = Math.min(255, rows - start);
      parts.push(Buffer.from([0x1d, 0x76, 0x30, 0x00, bytesPerRow & 0xff, bytesPerRow >> 8, band & 0xff, band >> 8]));
      parts.push(image.bits.subarray(start * bytesPerRow, (start + band) * bytesPerRow));
    }
    parts.push(Buffer.from([0x1b, 0x64, 0x04])); // avança 4 linhas
    parts.push(Buffer.from([0x1d, 0x56, 0x42, 0x00])); // corte parcial
  }
  return Buffer.concat(parts);
}

function sendRaw(host: string, port: number, data: Buffer) {
  return new Promise<void>((resolve, reject) => {
    const socket = new Socket();
    socket.setTimeout(8000);
    socket.once("timeout", () => {
      socket.destroy();
      reject(new Error("a impressora não respondeu (tempo esgotado)"));
    });
    socket.once("error", (error) => reject(new Error(`sem conexão (${error.message})`)));
    socket.connect(port, host, () => socket.end(data, () => resolve()));
  });
}

export const TEST_PAGE = (title: string) => `<!doctype html><html><head><meta charset="utf-8"><style>
@page { size: 80mm auto; margin: 0 } body { width: 72mm; margin: 0; padding: 4mm; font: 12px Consolas, monospace }
h1 { font-size: 15px; text-align: center; margin: 0 0 6px } p { margin: 2px 0 }
</style></head><body><h1>Starrp PDV</h1><p>Teste de impressão</p><p>${title}</p><p>${new Date().toLocaleString("pt-BR")}</p>
<p>████████████████████████████████</p><p>Acentuação: ação, ç, ã, é, ô</p></body></html>`;
