/**
 * Roda o electron-vite sem `ELECTRON_RUN_AS_NODE` herdado (o VS Code e outros apps Electron o
 * passam para os processos filhos; com ele o Electron sobe como Node puro e `app` fica undefined).
 */
import { spawn } from "node:child_process";

delete process.env.ELECTRON_RUN_AS_NODE;
const child = spawn("electron-vite", process.argv.slice(2), { stdio: "inherit", shell: true, env: process.env });
child.on("exit", (code) => process.exit(code ?? 0));
