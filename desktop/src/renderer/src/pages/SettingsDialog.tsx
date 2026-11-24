/**
 * Configurações DESTE computador (ficam no PC, não no servidor):
 *
 * - Impressão: imprimir direto ou perguntar antes; a impressora dos recibos e a da nota
 *   (do Windows, pelo nome, ou térmica na rede por IP:porta); papel; cópias; gaveta; teste.
 * - Nota fiscal: liga a emissão por este PC, o endereço do Comunicador Fiscal desktop (modo
 *   local) e o token dele (guardado criptografado — a tela só sabe SE existe), o modelo (NFC-e/NF-e),
 *   emitir ao concluir, contingência offline, e o kit fiscal baixado do servidor.
 * - Offline: conexão, catálogo guardado e a fila de envio (tentar de novo / descartar).
 * - Terminal: o nome com que este PDV aparece na retaguarda.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { dateTime } from "@/lib/format";
import { net } from "@/state/net";
import { saveConfig, session } from "@/state/session";
import { useStore } from "@/state/store";
import { notify } from "@/state/toast";
import { Button, cx, Dialog, Field, Input, Segmented, Select, Tag, Toggle } from "@/ui";

import type { AppConfig, PrinterTarget } from "../../../shared/ipc";

type Tab = "printing" | "fiscal" | "offline" | "terminal";
const TABS: { value: Tab; label: string }[] = [
  { value: "printing", label: "Impressão" }, { value: "fiscal", label: "Nota fiscal" },
  { value: "offline", label: "Offline" }, { value: "terminal", label: "Terminal" },
];

export default function SettingsDialog({ open, onClose, initialTab = "printing" }: { open: boolean; onClose: () => void; initialTab?: Tab }) {
  const { config } = useStore(session);
  const [tab, setTab] = useState<Tab>(initialTab);
  const [draft, setDraft] = useState<AppConfig | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (open && config) setDraft(structuredClone(config));
    if (open) setTab(initialTab);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open || !draft) return null;
  const set = (patch: Partial<AppConfig>) => setDraft((d) => (d ? { ...d, ...patch } : d));

  async function save() {
    setSaving(true);
    try {
      await saveConfig({ printing: draft!.printing, fiscal: draft!.fiscal, terminalName: draft!.terminalName });
      notify.success("Configurações salvas", "Valem para este computador.");
      onClose();
    } catch (error) {
      notify.error(error, "Configurações não salvas");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} width={720} title="Configurações deste PDV"
      footer={<>
        <Button variant="ghost" onClick={onClose}>Fechar</Button>
        {tab !== "offline" && <Button icon="pi pi-check" loading={saving} onClick={() => void save()}>Salvar</Button>}
      </>}>
      <div className="flex flex-col gap-4">
        <Segmented value={tab} onChange={setTab} options={TABS} className="self-start" />
        {tab === "printing" && <PrintingTab draft={draft} set={set} />}
        {tab === "fiscal" && <FiscalTab draft={draft} set={set} />}
        {tab === "offline" && <OfflineTab />}
        {tab === "terminal" && (
          <Field label="Nome deste terminal" hint="Como ele aparece na retaguarda (Dispositivos). Vale no próximo início do PDV.">
            <Input value={draft.terminalName} onChange={(e) => set({ terminalName: e.target.value })} />
          </Field>
        )}
      </div>
    </Dialog>
  );
}

/* ── impressão ─────────────────────────────────────────────────────────────── */

function PrintingTab({ draft, set }: { draft: AppConfig; set: (p: Partial<AppConfig>) => void }) {
  const p = draft.printing;
  const update = (patch: Partial<AppConfig["printing"]>) => set({ printing: { ...p, ...patch } });
  return (
    <div className="flex flex-col gap-4">
      <Section title="Como imprimir">
        <Segmented value={p.mode} onChange={(mode) => update({ mode })}
          options={[{ value: "direct", label: "Imprimir direto" }, { value: "ask", label: "Perguntar antes de imprimir" }]} />
        <p className="text-[12.5px] text-muted">
          {p.mode === "direct" ? "Sai direto na impressora configurada, sem janela." : "Antes de cada impressão aparece a escolha da impressora e das cópias (impressora do Windows) ou uma confirmação (rede)."}
        </p>
        <div className="grid grid-cols-2 gap-x-6">
          <Toggle checked={p.autoReceipt} onChange={(autoReceipt) => update({ autoReceipt })} label="Recibo ao concluir a venda"
            hint="Quando a nota não sai (com a nota, o DANFE já é o comprovante)." />
          <Toggle checked={p.autoInvoice} onChange={(autoInvoice) => update({ autoInvoice })} label="DANFE ao autorizar a nota" />
          <Toggle checked={p.openDrawer} onChange={(openDrawer) => update({ openDrawer })} label="Abrir a gaveta no dinheiro"
            hint="Pulso pela impressora de recibos de rede (ESC/POS)." />
          <Field label="Cópias">
            <Input type="number" min={1} max={9} value={p.copies} onChange={(e) => update({ copies: Math.max(1, Math.min(9, Number(e.target.value) || 1)) })} className="w-24" />
          </Field>
        </div>
      </Section>
      <PrinterEditor title="Impressora dos recibos" hint="Recibo da venda, comprovantes de abertura e do turno." slot="receipt"
        value={p.receipt} onChange={(receipt) => update({ receipt })} />
      <PrinterEditor title="Impressora da nota fiscal" hint="DANFE da NFC-e (bobina) e da NF-e (A4)." slot="fiscal"
        value={p.fiscal} onChange={(fiscal) => update({ fiscal })} />
    </div>
  );
}

export function PrinterEditor({ title, hint, slot, value, onChange }: {
  title: string; hint?: string; slot?: "receipt" | "fiscal"; value: PrinterTarget; onChange: (v: PrinterTarget) => void;
}) {
  const printers = useQuery({ queryKey: ["system-printers"], queryFn: () => window.starrp.printers.list(), staleTime: 60_000 });
  const [testing, setTesting] = useState(false);
  const update = (patch: Partial<PrinterTarget>) => onChange({ ...value, ...patch });
  async function test() {
    setTesting(true);
    const result = await window.starrp.printers.test(slot ?? "receipt", value);
    setTesting(false);
    if (result.ok) notify.success("Página de teste enviada", value.kind === "network" ? `${value.host}:${value.port}` : value.name || "Impressora padrão");
    else if (!result.cancelled) notify.warn("Teste não impresso", result.error);
  }
  return (
    <Section title={title} hint={hint}>
      <Segmented value={value.kind} onChange={(kind) => update({ kind, paper: kind === "network" && value.paper === 210 ? 80 : value.paper })}
        options={[{ value: "system", label: "Impressora do Windows" }, { value: "network", label: "Rede (IP / protocolo ESC/POS)" }]} />
      <div className="grid grid-cols-[1fr_180px] gap-3">
        {value.kind === "system" ? (
          <Field label="Impressora" hint={printers.data?.length ? undefined : "Nenhuma impressora instalada no Windows."}>
            <Select value={value.name} onChange={(name) => update({ name: name ?? "" })}
              options={[{ value: "", label: "Padrão do Windows" }, ...(printers.data ?? []).map((pr) => ({ value: pr.name, label: `${pr.displayName}${pr.isDefault ? " (padrão)" : ""}` }))]} />
          </Field>
        ) : (
          <div className="grid grid-cols-[1fr_110px] gap-3">
            <Field label="IP da impressora" hint="Térmica ESC/POS na rede (Epson, Elgin, Bematech, Daruma...).">
              <Input value={value.host} placeholder="192.168.0.50" onChange={(e) => update({ host: e.target.value.trim() })} />
            </Field>
            <Field label="Porta">
              <Input type="number" value={value.port} onChange={(e) => update({ port: Number(e.target.value) || 9100 })} />
            </Field>
          </div>
        )}
        <Field label="Papel">
          <Select value={value.paper} onChange={(paper) => update({ paper: (paper ?? 80) as PrinterTarget["paper"] })}
            options={[{ value: 80, label: "Bobina 80 mm" }, { value: 58, label: "Bobina 58 mm" },
              ...(value.kind === "system" ? [{ value: 210, label: "Folha A4" }] : [])]} />
        </Field>
      </div>
      {slot && <Button size="sm" variant="secondary" icon="pi pi-print" loading={testing} className="self-start" onClick={() => void test()}>Imprimir teste</Button>}
    </Section>
  );
}

/* ── nota fiscal ───────────────────────────────────────────────────────────── */

function FiscalTab({ draft, set }: { draft: AppConfig; set: (p: Partial<AppConfig>) => void }) {
  const f = draft.fiscal;
  const update = (patch: Partial<AppConfig["fiscal"]>) => set({ fiscal: { ...f, ...patch } });
  const client = useQueryClient();
  const secrets = useQuery({ queryKey: ["fiscal-secrets"], queryFn: () => window.starrp.fiscal.secrets() });
  const kit = useQuery({ queryKey: ["fiscal-kit"], queryFn: () => window.starrp.fiscal.kit() });
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [health, setHealth] = useState<{ ok: boolean; message: string } | null>(null);

  async function saveSecrets() {
    setBusy("secrets");
    await window.starrp.fiscal.setSecrets({ token });
    setToken("");
    await client.invalidateQueries({ queryKey: ["fiscal-secrets"] });
    setBusy(null);
    notify.success("Token do comunicador guardado", "Criptografado neste computador.");
  }
  async function test() {
    setBusy("health");
    await saveConfig({ fiscal: f }); // testa com o endereço digitado
    setHealth(await window.starrp.fiscal.health());
    setBusy(null);
  }
  /** Quem administra o fiscal grava o A1 e o CSC NO comunicador (uma vez por comunicador). */
  async function storeEmitter() {
    setBusy("emitter");
    await saveConfig({ fiscal: f });
    const result = await window.starrp.fiscal.storeEmitter();
    setBusy(null);
    if (result.ok) notify.success("Certificado no comunicador", result.message);
    else notify.warn("Certificado não gravado", result.message);
  }
  async function refreshKit() {
    setBusy("kit");
    const info = await window.starrp.fiscal.refreshKit();
    client.setQueryData(["fiscal-kit"], info);
    setBusy(null);
    if (info.error) notify.warn("Kit fiscal", info.error);
    else notify.success("Kit fiscal atualizado");
  }

  return (
    <div className="flex flex-col gap-4">
      <Toggle checked={f.enabled} onChange={(enabled) => update({ enabled })} label="Emitir nota fiscal por este computador"
        hint="Pelo Comunicador Fiscal desktop instalado aqui (modo local). Os dados fiscais da filial precisam do provedor ACBrLib e da emissão no terminal ligada." />
      <Section title="Comunicador Fiscal (desktop)">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Endereço" hint="O do Comunicador Fiscal: http://127.0.0.1:8030 (ou o IP do PC da loja).">
            <Input value={f.acbrUrl} onChange={(e) => update({ acbrUrl: e.target.value })} placeholder="http://127.0.0.1:8030" />
          </Field>
          <Field label={<>Token de acesso {secrets.data?.token && <Tag tone="success">guardado</Tag>}</>} hint="Tela Acesso do Comunicador Fiscal.">
            <Input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder={secrets.data?.token ? "•••••• (digite para trocar)" : "Cole o token"} autoComplete="off" />
          </Field>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" icon="pi pi-key" disabled={!token} loading={busy === "secrets"} onClick={() => void saveSecrets()}>Guardar token</Button>
          <Button size="sm" variant="secondary" icon="pi pi-bolt" loading={busy === "health"} onClick={() => void test()}>Testar comunicador e SEFAZ</Button>
          <Button size="sm" variant="secondary" icon="pi pi-shield" loading={busy === "emitter"} onClick={() => void storeEmitter()}
            title="Só quem administra o fiscal. O certificado fica cifrado no comunicador; este PDV não guarda.">Gravar certificado no comunicador</Button>
        </div>
        <p className="text-[12px] text-muted">
          O certificado A1 e o CSC ficam guardados no Comunicador Fiscal (tela Emitente dele). O botão acima grava os dados
          fiscais da filial nele — só funciona neste mesmo PC e com um usuário que administra o fiscal.
        </p>
        {health && (
          <p className={cx("rounded-lg px-3 py-2 text-[12.5px]", health.ok ? "bg-success-subtle text-success-text" : "bg-danger-subtle text-danger-text")}>
            <i className={health.ok ? "pi pi-check-circle" : "pi pi-times-circle"} /> {health.message}
          </p>
        )}
      </Section>
      <Section title="Emissão">
        <Segmented value={f.model} onChange={(model) => update({ model })}
          options={[{ value: "65", label: "NFC-e (cupom, modelo 65)" }, { value: "55", label: "NF-e (modelo 55)" }]} />
        <div className="grid grid-cols-2 gap-x-6">
          <Toggle checked={f.autoEmit} onChange={(autoEmit) => update({ autoEmit })} label="Emitir ao concluir a venda"
            hint="Desligado: emita pelo botão no pedido (F2)." />
          <Toggle checked={f.contingency} onChange={(contingency) => update({ contingency })} label="Contingência offline (NFC-e)"
            hint="SEFAZ fora: assina aqui, imprime e transmite depois." />
        </div>
      </Section>
      <Section title="Kit fiscal (do servidor)" hint="Emitente, perfis fiscais e a série deste terminal (sem certificado). Fica guardado criptografado para emitir sem o servidor.">
        {kit.data?.ready ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
            <dt className="text-muted">Emitente</dt><dd className="text-strong">{kit.data.issuer?.legal_name} · {kit.data.issuer?.state}</dd>
            <dt className="text-muted">Ambiente</dt><dd>{kit.data.environment === "1" ? <Tag tone="success">Produção</Tag> : <Tag tone="warning">Homologação</Tag>}</dd>
            <dt className="text-muted">Série deste PDV</dt>
            <dd>{Object.entries(kit.data.series ?? {}).map(([m, s]) => `${m === "65" ? "NFC-e" : "NF-e"} série ${s.series} (próx. ${s.next_number})`).join(" · ")}</dd>
            <dt className="text-muted">Certificado vence</dt><dd>{kit.data.certificateValidUntil ? dateTime(kit.data.certificateValidUntil) : "—"}</dd>
            <dt className="text-muted">Baixado em</dt><dd>{kit.data.generatedAt ? dateTime(kit.data.generatedAt) : "—"}</dd>
          </dl>
        ) : <p className="text-[13px] text-muted">{kit.data?.error ?? "Carregando…"}</p>}
        <Button size="sm" variant="secondary" icon="pi pi-download" className="self-start" loading={busy === "kit"} onClick={() => void refreshKit()}>Baixar kit agora</Button>
      </Section>
    </div>
  );
}

/* ── offline ───────────────────────────────────────────────────────────────── */

function OfflineTab() {
  const status = useStore(net);
  const outbox = useQuery({ queryKey: ["outbox", status.pending, status.failed, status.lastSync], queryFn: () => window.starrp.offline.outbox() });
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    try {
      await fn();
      await outbox.refetch();
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="flex flex-col gap-4">
      <Section title="Conexão">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
          <dt className="text-muted">Servidor</dt><dd>{status.online ? <Tag tone="success">Respondendo</Tag> : <Tag tone="danger">Sem resposta: vendendo offline</Tag>}</dd>
          <dt className="text-muted">Última sincronização</dt><dd>{status.lastSync ? dateTime(status.lastSync) : "—"}</dd>
          <dt className="text-muted">Catálogo guardado</dt><dd>{status.snapshotAt ? dateTime(status.snapshotAt) : "Ainda não baixado"}</dd>
          <dt className="text-muted">Na fila</dt><dd>{status.pending} · com erro: {status.failed}</dd>
        </dl>
        <div className="flex gap-2">
          <Button size="sm" icon="pi pi-sync" loading={busy === "sync"} onClick={() => void act("sync", () => window.starrp.offline.syncNow())}>Sincronizar agora</Button>
          <Button size="sm" variant="secondary" icon="pi pi-database" loading={busy === "snap"} disabled={!status.online}
            onClick={() => void act("snap", () => window.starrp.offline.refreshSnapshot())}>Baixar catálogo agora</Button>
        </div>
      </Section>
      <Section title="Fila de envio" hint="Vendas feitas sem o servidor. Saem sozinhas, em ordem, quando ele volta.">
        {!outbox.data?.length ? <p className="text-[13px] text-muted">Nada esperando o servidor.</p> : (
          <ul className="flex flex-col divide-y divide-line-subtle">
            {outbox.data.map((e) => (
              <li key={e.id} className="flex items-center gap-3 py-2 text-[13px]">
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-strong">{e.label}</p>
                  <p className="text-[12px] text-muted">{dateTime(e.createdAt)} · {e.attempts} tentativa(s){e.lastError && ` · ${e.lastError}`}</p>
                </div>
                <Tag tone={e.status === "failed" ? "danger" : "warning"}>{e.status === "failed" ? "Recusada" : "Aguardando"}</Tag>
                {e.status === "failed" && <>
                  <Button size="sm" variant="secondary" icon="pi pi-replay" onClick={() => void act(e.id, () => window.starrp.offline.retry(e.id))}>Tentar</Button>
                  <Button size="sm" variant="ghost" icon="pi pi-trash" onClick={() => {
                    if (window.confirm(`Descartar "${e.label}"? Ela não vai para o servidor (estoque e caixa não registram).`)) void act(e.id, () => window.starrp.offline.discard(e.id));
                  }}>Descartar</Button>
                </>}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5 rounded-xl border border-line p-3.5">
      <header>
        <h3 className="text-[14px] font-bold text-strong">{title}</h3>
        {hint && <p className="text-[12.5px] text-muted">{hint}</p>}
      </header>
      {children}
    </section>
  );
}
