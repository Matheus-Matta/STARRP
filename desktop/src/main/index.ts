/**
 * Processo principal do PDV desktop: a janela, a ponte com a tela (IPC), a impressão
 * (`printing.ts`), a nota fiscal pelo comunicador ACBr local (`fiscal.ts`) e o modo offline
 * (`sync.ts`).
 *
 * A tela (renderer) roda isolada (contextIsolation, sem Node). Tudo que toca a rede com o
 * token passa por aqui (`api.ts`), então o access e o refresh nunca chegam ao JavaScript da tela.
 */
import { join } from "node:path";

import { app, BrowserWindow, dialog, ipcMain, Menu, session, shell } from "electron";

import type { ApiRequest, AppConfig, AuthorizeRequest, EmitRequest, OfflineCache, PrinterTarget, PrintJob } from "../shared/ipc";
import * as api from "./api";
import { getConfig, installationId, setConfig } from "./config";
import * as fiscal from "./fiscal";
import * as local from "./local";
import * as printing from "./printing";
import * as sync from "./sync";

let win: BrowserWindow | null = null;

function createWindow() {
  // Windows lê o .ico; Linux, o .png.
  const iconFile = process.platform === "win32" ? "icon.ico" : "icon.png";
  const icon = app.isPackaged
    ? join(process.resourcesPath, iconFile)
    : join(__dirname, "../../build", iconFile);

  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 640,
    show: false,
    fullscreen: true,
    title: "Starrp PDV",
    icon,
    backgroundColor: getConfig().theme === "dark" ? "#09090b" : "#f1f5f9",
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      // App instalado: sem ferramentas do desenvolvedor (nada de mexer na venda pelo console).
      devTools: !app.isPackaged,
    },
  });
  win.once("ready-to-show", () => {
    win?.show();
  });

  // Links externos abrem no navegador, nunca dentro do PDV — e só http(s): `file:`, `ms-...:` e
  // outros protocolos poderiam rodar programas do Windows.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  // A tela NUNCA sai do app: uma página de fora teria a ponte `window.starrp` (API com o token).
  win.webContents.on("will-navigate", (event, url) => {
    if (url !== win?.webContents.getURL()) event.preventDefault();
  });
  win.webContents.on("will-attach-webview", (event) => event.preventDefault());

  // A tela pede para não fechar no meio de uma venda: confirma com o operador.
  win.webContents.on("will-prevent-unload", (event) => {
    const choice = dialog.showMessageBoxSync(win!, {
      type: "warning",
      buttons: ["Continuar no PDV", "Fechar mesmo assim"],
      defaultId: 0,
      cancelId: 0,
      title: "Venda em andamento",
      message: "Há uma venda em andamento.",
      detail: "Ela continua salva no servidor e volta quando você abrir o PDV de novo.",
    });
    if (choice === 1) event.preventDefault();
  });

  // F11 alterna o modo tela cheia, como no navegador. DevTools só em desenvolvimento (Ctrl+Shift+I).
  win.webContents.on("before-input-event", (event, input) => {
    if (input.type === "keyDown" && input.key === "F11" && !input.shift && !input.control && !input.alt && !input.meta) {
      if (!input.isAutoRepeat) win?.setFullScreen(!win.isFullScreen());
      event.preventDefault();
      return;
    }
    if (!app.isPackaged && input.type === "keyDown" && input.control && input.shift && input.key.toLowerCase() === "i") {
      win?.webContents.toggleDevTools();
      event.preventDefault();
    }
  });

  if (!app.isPackaged && process.env.ELECTRON_RENDERER_URL) void win.loadURL(process.env.ELECTRON_RENDERER_URL);
  else void win.loadFile(join(__dirname, "../renderer/index.html"));
}

function registerIpc() {
  ipcMain.handle("api:request", async (_e, req: ApiRequest) => {
    const response = await api.request(req);
    sync.reportFailure(response.status);
    return response;
  });
  ipcMain.handle("auth:login", async (_e, username: string, password: string) => {
    const result = await api.login(username, password);
    if (result.ok) local.learnOperator(username, password); // desbloquear a tela sem servidor
    return result;
  });
  ipcMain.handle("auth:logout", () => api.logout());
  ipcMain.handle("auth:has-session", () => api.hasSession());
  ipcMain.handle("config:get", () => getConfig());
  ipcMain.handle("config:set", (_e, patch: Partial<AppConfig>) => setConfig(patch));
  ipcMain.handle("config:installation-id", (_e, storeId: string) => installationId(storeId));
  ipcMain.handle("printers:list", () => printing.listPrinters(win));
  ipcMain.handle("printers:print", (_e, job: PrintJob) => printing.print(job, win));
  ipcMain.handle("printers:test", (_e, slot: "receipt" | "fiscal", target?: PrinterTarget) =>
    printing.print({ html: printing.TEST_PAGE(slot === "fiscal" ? "Impressora da nota fiscal" : "Impressora de recibos"),
                     slot, target, confirmed: true, copies: 1, title: "Teste" }, win));
  ipcMain.handle("fiscal:secrets", () => fiscal.secretStatus());
  ipcMain.handle("fiscal:set-secrets", (_e, values: { token?: string }) => fiscal.setSecrets(values));
  ipcMain.handle("fiscal:health", () => fiscal.health());
  ipcMain.handle("fiscal:store-emitter", () => fiscal.storeEmitter());
  ipcMain.handle("fiscal:kit", () => fiscal.getKitInfo());
  ipcMain.handle("fiscal:refresh-kit", () => fiscal.refreshKit());
  ipcMain.handle("fiscal:emit", (_e, req: EmitRequest) => fiscal.emit(req));
  ipcMain.handle("fiscal:invoices", (_e, saleRef?: string) => fiscal.invoicesFor(saleRef));
  ipcMain.handle("offline:status", () => sync.status());
  ipcMain.handle("offline:snapshot", () => sync.getSnapshot());
  ipcMain.handle("offline:refresh-snapshot", () => sync.refreshSnapshot());
  ipcMain.handle("offline:cache", () => sync.getCache());
  ipcMain.handle("offline:save-cache", (_e, cache: OfflineCache) => sync.saveCache(cache));
  ipcMain.handle("offline:enqueue-sale", (_e, payload: Record<string, unknown>, label: string, hold?: boolean) =>
    sync.enqueueSale(payload, label, hold));
  ipcMain.handle("offline:flush", (_e, id: string) => sync.flush(id));
  ipcMain.handle("offline:enqueue-cash", (_e, payload: Record<string, unknown>, label: string) => sync.enqueueCash(payload, label));
  ipcMain.handle("local:cash", () => local.cashState());
  ipcMain.handle("local:save-cash", (_e, state: local.CashState) => local.saveCashState(state));
  ipcMain.handle("local:current", (_e, userId: number) => local.currentSale(userId));
  ipcMain.handle("local:save-current", (_e, userId: number, sale: { id: string } | null) => local.saveCurrentSale(userId, sale));
  ipcMain.handle("local:parked", () => local.parked());
  ipcMain.handle("local:park", (_e, sale: { id: string }) => local.park(sale));
  ipcMain.handle("local:unpark", (_e, id: string) => local.unpark(id));
  ipcMain.handle("local:history", () => local.history());
  ipcMain.handle("local:remember", (_e, sale: { id: string }) => local.remember(sale));
  ipcMain.handle("local:authorize", (_e, body: AuthorizeRequest) => sync.authorize(body));
  ipcMain.handle("local:unlock", (_e, username: string, password: string) => sync.unlock(username, password));
  ipcMain.handle("offline:next-number", () => sync.nextLocalNumber());
  ipcMain.handle("offline:outbox", () => sync.listOutbox());
  ipcMain.handle("offline:retry", (_e, id?: string) => sync.retry(id));
  ipcMain.handle("offline:discard", (_e, id: string) => sync.discard(id));
  ipcMain.handle("offline:sync-now", () => sync.tick());
  ipcMain.handle("app:version", () => app.getVersion());
  ipcMain.handle("app:fullscreen", () => win?.setFullScreen(!win.isFullScreen()));
  ipcMain.handle("app:quit", () => app.quit());
  api.onExpired(() => win?.webContents.send("auth:expired"));
}

// Um PDV por computador: abrir de novo só traz a janela para a frente.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win?.isMinimized()) win.restore();
    win?.focus();
  });
  void app.whenReady().then(() => {
    app.setAppUserModelId("br.com.starrp.pdv");
    Menu.setApplicationMenu(null);
    // O PDV não usa câmera, microfone, localização nem notificações do navegador: nega tudo.
    session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
    session.defaultSession.setPermissionCheckHandler(() => false);
    registerIpc();
    createWindow();
    sync.start(win!);
  });
  app.on("window-all-closed", () => app.quit());
}
