import type { StarrpBridge } from "../shared/ipc";

declare global {
  interface Window {
    starrp: StarrpBridge;
  }
}

export {};
