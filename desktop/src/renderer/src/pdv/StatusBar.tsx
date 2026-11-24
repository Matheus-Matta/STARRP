/**
 * Barra de status (fina, no topo): loja (troca aqui, se o operador tiver mais de uma), situação
 * do caixa, operador, turno, terminal, conexão, bloquear e tema.
 */
import { hour } from "@/lib/format";
import { net } from "@/state/net";
import { session, switchStore, toggleTheme } from "@/state/session";
import { useStore } from "@/state/store";
import { cx } from "@/ui";

type Props = {
  cashOpen: boolean; operator: string; since: string | null; terminal: string; seller: boolean; canSwitchStore: boolean;
  onLock: () => void; onCash: () => void; onSettings: () => void;
};

export default function StatusBar({ cashOpen, operator, since, terminal, seller, canSwitchStore, onLock, onCash, onSettings }: Props) {
  const { me, storeId, config } = useStore(session);
  const status = useStore(net);
  const online = status.online;
  const stores = me?.stores ?? [];
  const storeName = stores.find((s) => s.id === storeId)?.name ?? "Sem filial";

  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b border-nav-line bg-nav px-3.5 text-[12.5px] text-nav-text">
      <img src="./mark.png" alt="Starrp" className="size-[26px]" />
      {stores.length > 1 && canSwitchStore ? (
        <select value={storeId ?? ""} onChange={(e) => void switchStore(e.target.value)} title="Trocar de filial"
          className="max-w-[220px] cursor-pointer rounded-md bg-transparent py-1 text-[13.5px] font-bold text-nav-strong outline-0 hover:bg-nav-hover">
          {stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      ) : (
        <strong className="text-[13.5px] whitespace-nowrap text-nav-strong">{storeName}</strong>
      )}
      {seller ? (
        <span className="inline-flex items-center gap-1.5 text-[12px] font-bold text-brand-text"><i className="pi pi-shopping-bag" /> Modo vendedor</span>
      ) : cashOpen ? (
        <span className="text-[12px] font-bold text-success-text">Caixa aberto</span>
      ) : (
        <button type="button" title="Abrir o caixa" onClick={onCash}
          className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[12px] font-bold text-warning-text hover:bg-warning-subtle">
          <i className="pi pi-lock" /> Caixa fechado
        </button>
      )}
      <span className="h-[18px] w-px bg-nav-line" />
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap"><i className="pi pi-user text-[11px] text-nav-muted" /> {operator}</span>
      {since && !seller && (
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap"><i className="pi pi-clock text-[11px] text-nav-muted" /> Turno desde {hour(since)}</span>
      )}
      {terminal && (
        <span className="hidden items-center gap-1.5 whitespace-nowrap xl:inline-flex"><i className="pi pi-desktop text-[11px] text-nav-muted" /> {terminal}</span>
      )}
      <div className="ml-auto flex items-center gap-2.5">
        <button type="button" onClick={onSettings}
          title={online ? `Servidor no ar${status.lastSync ? ` · sincronizado às ${hour(status.lastSync)}` : ""}` : "Servidor sem resposta: vendendo offline com o catálogo guardado"}
          className={cx("inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 font-semibold hover:bg-nav-hover", online ? "text-success-text" : "text-danger-text")}>
          <i className={status.syncing ? "pi pi-spin pi-sync" : online ? "pi pi-wifi" : "pi pi-exclamation-triangle"} /> {online ? "Online" : "Offline"}
          {status.pending > 0 && <span className="rounded-full bg-warning-subtle px-1.5 text-[11px] text-warning-text">{status.pending} na fila</span>}
          {status.failed > 0 && <span className="rounded-full bg-danger-subtle px-1.5 text-[11px] text-danger-text">{status.failed} com erro</span>}
        </button>
        {!seller && (
          <button type="button" title="Bloquear a tela (F12)" aria-label="Bloquear a tela" onClick={onLock}
            className="grid size-[30px] place-items-center rounded-md text-nav-muted hover:bg-nav-hover hover:text-nav-strong">
            <i className="pi pi-lock" />
          </button>
        )}
        <button type="button" title={config?.theme === "dark" ? "Tema claro" : "Tema escuro"} onClick={() => void toggleTheme()}
          className="grid size-[30px] place-items-center rounded-md text-nav-muted hover:bg-nav-hover hover:text-nav-strong">
          <i className={config?.theme === "dark" ? "pi pi-sun" : "pi pi-moon"} />
        </button>
        <button type="button" title="Alternar tela cheia (F11)" onClick={() => void window.starrp.app.toggleFullscreen()}
          className="grid size-[30px] place-items-center rounded-md text-nav-muted hover:bg-nav-hover hover:text-nav-strong">
          <i className="pi pi-window-maximize" />
        </button>
      </div>
    </header>
  );
}
