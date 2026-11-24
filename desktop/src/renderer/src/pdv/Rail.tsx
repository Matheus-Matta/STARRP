/**
 * Trilho de atalhos (esquerda), cada um com a sua tecla:
 * F1 venda · F2 pedidos · F3 cliente · F4 caixa (só no modo caixa) · F5 preço · Shift+F5 frete · F8 sair.
 */
import { cx } from "@/ui";

export type RailAction = "sale" | "orders" | "customer" | "cash" | "price" | "freight" | "settings" | "exit";

export default function Rail({ active, seller, onSelect }: { active: RailAction; seller: boolean; onSelect: (a: RailAction) => void }) {
  const items: { action: RailAction; label: string; icon: string; key: string }[] = [
    { action: "sale", label: "Venda", icon: "pi pi-th-large", key: "F1" },
    { action: "orders", label: "Pedidos", icon: "pi pi-inbox", key: "F2" },
    { action: "customer", label: "Cliente", icon: "pi pi-user", key: "F3" },
    ...(seller ? [] : [{ action: "cash" as const, label: "Caixa", icon: "pi pi-wallet", key: "F4" }]),
    { action: "price", label: "Preço", icon: "pi pi-tag", key: "F5" },
    { action: "freight", label: "Frete", icon: "pi pi-truck", key: "⇧F5" },
    { action: "settings", label: "Config.", icon: "pi pi-cog", key: "" },
    { action: "exit", label: "Sair", icon: "pi pi-sign-out", key: "F8" },
  ];
  return (
    <nav aria-label="Atalhos do PDV" className="flex w-[72px] shrink-0 flex-col gap-1 border-r border-nav-line bg-nav px-1.5 py-2">
      {items.map((item) => (
        <button key={item.action} type="button" title={item.key ? `${item.label} (${item.key})` : item.label} onClick={() => onSelect(item.action)}
          className={cx("relative flex flex-col items-center gap-1 rounded-lg px-0.5 pt-2.5 pb-2 text-[11px] font-semibold transition-colors",
            item.action === "settings" && "mt-auto",
            active === item.action ? "bg-nav-active text-nav-active-text" : "text-nav-muted hover:bg-nav-hover hover:text-nav-strong")}>
          {active === item.action && <span className="absolute top-2.5 bottom-2.5 -left-1.5 w-[3px] rounded-r bg-brand" />}
          <kbd className="absolute top-[3px] right-1 font-mono text-[8.5px] opacity-80">{item.key}</kbd>
          <i className={cx(item.icon, "text-[18px]")} />
          <span>{item.label}</span>
        </button>
      ))}
    </nav>
  );
}
