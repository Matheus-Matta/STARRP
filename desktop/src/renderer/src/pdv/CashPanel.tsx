/**
 * Caixa DENTRO do PDV (só no modo caixa): o turno aberto, quanto deve haver na gaveta (só para
 * quem aprova — o operador fecha às cegas), as pendências de sangria/suprimento e as ações.
 * Embaixo, os últimos turnos deste caixa.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { cashApi, salesApi } from "@/api/pdv";
import type { CashMovement, CashSession } from "@/api/types";
import { dateTime, money } from "@/lib/format";
import { ApprovalCancelled, withApproval } from "@/state/approval";
import { net } from "@/state/net";
import { useStore } from "@/state/store";
import { notify } from "@/state/toast";
import { Button, cx, IconButton, Tag } from "@/ui";

import { drawerOf } from "./rules";

export type CashAction = "open" | "withdrawal" | "supply" | "close" | "lock" | "report";
const KIND: Record<string, string> = { withdrawal: "Sangria", supply: "Suprimento" };
const SESSION_STATUS: Record<string, [string, string]> = {
  open: ["Aberto", "success"], pending_opening: ["Abertura pendente", "warning"], pending_approval: ["Aguardando aprovação", "warning"],
  closed: ["Fechado", "neutral"],
};

export default function CashPanel({ session, operator, seesDrawer, version, register, onAction, onBack }: {
  session: CashSession | null; operator: string; seesDrawer: boolean; version: number; register: string | null;
  onAction: (action: CashAction) => void; onBack: () => void;
}) {
  const client = useQueryClient();
  // Turno aberto neste PC sem servidor (ou servidor fora agora): a gaveta é a deste PC.
  const online = useStore(net).online;
  const here = !online || Boolean(session?.id.startsWith("off:"));
  const drawer = useQuery({
    queryKey: ["pdv-cash-local", session?.id, version],
    queryFn: () => localDrawer(session!),
    enabled: Boolean(session) && here,
  });
  const detail = useQuery({
    queryKey: ["pdv-cash", session?.id, version],
    queryFn: () => cashApi.get(session!.id),
    enabled: Boolean(session) && !here,
    refetchInterval: 30_000,
  });
  const sales = useQuery({
    queryKey: ["pdv-cash-sales", session?.id, version],
    queryFn: () => salesApi.list({ cash_session: session!.id, status: "completed", page_size: 1 }),
    enabled: Boolean(session) && !here,
    refetchInterval: 30_000,
  });
  const movements = useQuery({
    queryKey: ["cash-pending", session?.id, version],
    queryFn: () => cashApi.movements(session!.id),
    enabled: Boolean(session) && !here,
    refetchInterval: 20_000,
  });
  const registerId = session?.register ?? register;
  const history = useQuery({
    queryKey: ["cash-history", registerId, version],
    queryFn: () => cashApi.history(registerId!),
    enabled: Boolean(registerId) && online,
  });

  const pending = here ? [] : (movements.data ?? []).filter((m) => m.status === "pending");
  const expected = here ? drawer.data?.expected ?? null : detail.data?.expected_now ?? detail.data?.expected_amount ?? null;
  const salesCount = here ? drawer.data?.sales : sales.data?.count;
  const [deciding, setDeciding] = useState<string | null>(null);

  async function decide(movement: CashMovement, approve: boolean) {
    setDeciding(movement.id);
    try {
      if (approve) {
        await withApproval((approval) => cashApi.approveMovement(movement.id, "", approval));
        notify.success(`${KIND[movement.kind] ?? "Movimento"} aprovado(a)`, money(movement.amount));
      } else {
        await cashApi.rejectMovement(movement.id);
        notify.success(`${KIND[movement.kind] ?? "Movimento"} recusado(a)`, "Não mexe na gaveta.");
      }
      await client.invalidateQueries({ queryKey: ["cash-pending", session?.id] });
      void detail.refetch();
    } catch (error) {
      if (!(error instanceof ApprovalCancelled)) notify.error(error, "Não foi possível concluir");
    } finally {
      setDeciding(null);
    }
  }

  return (
    <section className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
      <header className="flex items-center gap-2.5">
        <IconButton icon="pi pi-arrow-left" label="Voltar para a venda" onClick={onBack} />
        <div><h2 className="panel-title">Caixa</h2>
          <p className="text-[13px] text-muted">{session ? `Turno aberto por ${operator}` : "Nenhum turno aberto neste caixa."}</p></div>
      </header>

      {session && (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-2">
          <Stat label="Aberto em" value={dateTime(session.opened_at)} />
          <Stat label="Troco inicial" value={money(session.opening_amount)} />
          {seesDrawer && expected !== null ? (
            <Stat label="Em dinheiro na gaveta agora" value={money(expected)} brand />
          ) : (
            <div className="flex flex-col gap-1 rounded-[10px] border border-dashed border-line bg-sunken px-3.5 py-3">
              <span className="eyebrow">Dinheiro na gaveta</span>
              <strong className="flex items-center gap-1.5 text-[17px] text-strong"><i className="pi pi-eye-slash" /> Oculto</strong>
              <small className="text-[12px] text-muted">No fechamento você conta e informa; a conferência é do gerente.</small>
            </div>
          )}
          <Stat label={here ? "Vendas neste PC no turno" : "Vendas no turno"} value={String(salesCount ?? "—")} />
        </div>
      )}

      {session && here && (
        <p className="flex items-start gap-2 rounded-lg bg-warning-subtle px-3 py-2 text-[12.5px] text-warning-text">
          <i className="pi pi-cloud-upload mt-0.5" />
          <span>
            {online ? "Turno aberto neste PC sem o servidor." : "Sem servidor:"} o caixa funciona normalmente aqui — vender, sangria,
            suprimento e fechar. Tudo vai ao servidor, em ordem, quando ele responder; a conferência do gerente acontece lá.
          </span>
        </p>
      )}
      {session && here && Boolean(drawer.data?.movements.length) && (
        <div className="rounded-[10px] border border-line bg-card">
          <p className="eyebrow border-b border-line-subtle px-3.5 py-2.5">Sangrias e suprimentos deste turno</p>
          <ul className="flex flex-col text-[13px]">
            {drawer.data!.movements.map((m) => (
              <li key={m.id} className="flex items-center gap-3 border-b border-line-subtle px-3.5 py-2 last:border-0">
                <strong className="text-strong">{KIND[m.kind] ?? m.kind}</strong>
                <span className="text-muted">{dateTime(m.created_at)} · {m.reason || "Sem motivo"}</span>
                <span className="ml-auto font-semibold text-strong">{money(m.amount)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {pending.length > 0 && (
        <div className="rounded-[10px] border border-warning bg-warning-subtle p-3">
          <p className="flex flex-wrap items-center gap-2 font-bold text-warning-text">
            <i className="pi pi-clock" /> Aguardando aprovação ({pending.length})
            <small className="font-normal text-muted">O caixa só fecha depois que cada um for aprovado ou recusado.</small>
          </p>
          <ul className="mt-2 flex flex-col gap-1.5">
            {pending.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-2 rounded-lg bg-card px-3 py-2">
                <div className="min-w-0 flex-1">
                  <strong className="text-strong">{KIND[m.kind] ?? m.kind} · {money(m.amount)}</strong>
                  <small className="block text-[12px] text-muted">{m.reason || "Sem motivo"} · {m.operator_name} · {dateTime(m.created_at)}</small>
                </div>
                <Button size="sm" variant="secondary" icon="pi pi-times" disabled={deciding !== null} onClick={() => void decide(m, false)}>Recusar</Button>
                <Button size="sm" icon="pi pi-check" loading={deciding === m.id} disabled={deciding !== null && deciding !== m.id}
                  onClick={() => void decide(m, true)}>Aprovar</Button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {session ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-2">
          <Action icon="pi pi-arrow-up-right" title="Sangria" text="Retirar dinheiro da gaveta" onClick={() => onAction("withdrawal")} />
          <Action icon="pi pi-arrow-down-left" title="Suprimento" text="Colocar troco na gaveta" onClick={() => onAction("supply")} />
          <Action icon="pi pi-lock" title="Bloquear tela" text="Sair um instante sem fechar (F12)" onClick={() => onAction("lock")} />
          <Action icon="pi pi-print" title="Comprovante do turno" text="Imprime na bobina" onClick={() => onAction("report")} />
          <Action icon="pi pi-power-off" title="Fechar caixa" text="Contar a gaveta e encerrar o turno" danger onClick={() => onAction("close")} />
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2.5 px-3 py-10 text-center text-muted">
          <i className="pi pi-lock text-[2rem]" />
          <p>Abra o caixa com o troco inicial para começar a vender.</p>
          <Button icon="pi pi-lock-open" onClick={() => onAction("open")}>Abrir caixa</Button>
        </div>
      )}

      {Boolean(history.data?.results.length) && (
        <div className="rounded-[10px] border border-line bg-card">
          <p className="eyebrow border-b border-line-subtle px-3.5 py-2.5">Últimos turnos deste caixa</p>
          <table className="w-full text-[13px]">
            <tbody>
              {history.data!.results.map((s) => (
                <tr key={s.id} className={cx("border-b border-line-subtle last:border-0", s.id === session?.id && "bg-brand-subtle")}>
                  <td className="px-3.5 py-2">{dateTime(s.opened_at)}</td>
                  <td className="px-3.5 py-2">{s.closed_at ? `até ${dateTime(s.closed_at)}` : "em aberto"}</td>
                  <td className="px-3.5 py-2">{s.opened_by_name}</td>
                  <td className="px-3.5 py-2 text-right">{money(s.opening_amount)}</td>
                  <td className="px-3.5 py-2 text-right">
                    <Tag tone={SESSION_STATUS[s.status]?.[1]}>{SESSION_STATUS[s.status]?.[0] ?? s.status}</Tag>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** A gaveta pelo que ESTE PC registrou (a mesma conta da regra da sangria, `rules.drawerOf`). */
async function localDrawer(session: CashSession) {
  const [state, history] = await Promise.all([window.starrp.local.cash(), window.starrp.local.history()]);
  const drawer = drawerOf(session, state, history);
  return { ...drawer, expected: drawer.expected.toFixed(2) };
}

const Stat = ({ label, value, brand }: { label: string; value: string; brand?: boolean }) => (
  <div className={cx("flex flex-col gap-1 rounded-[10px] border px-3.5 py-3", brand ? "border-brand-border bg-brand-subtle" : "border-line bg-card")}>
    <span className="eyebrow">{label}</span>
    <strong className={cx("text-[17px]", brand ? "text-brand-text" : "text-strong")}>{value}</strong>
  </div>
);

const Action = ({ icon, title, text, danger, onClick }: { icon: string; title: string; text: string; danger?: boolean; onClick: () => void }) => (
  <button type="button" onClick={onClick}
    className={cx("flex flex-col items-start gap-1 rounded-[10px] border bg-card px-3.5 py-3 text-left transition-colors",
      danger ? "border-line hover:border-danger hover:bg-danger-subtle" : "border-line hover:border-brand-border hover:bg-hover")}>
    <i className={cx(icon, "text-[18px]", danger ? "text-danger-text" : "text-brand")} />
    <strong className="text-[14px] text-strong">{title}</strong>
    <small className="text-[12px] text-muted">{text}</small>
  </button>
);
