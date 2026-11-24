/**
 * Clientes DENTRO do PDV: lista com busca; clicar vincula à venda e volta.
 * - "CPF na nota": só o documento, sem cadastrar;
 * - "Novo cliente": cadastro rápido (documento, nome, contato e endereço de entrega com CEP).
 */
import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";

import { customersApi } from "@/api/pdv";
import type { Address } from "@/api/types";
import { documentError, formatDocument, maskDocument, maskPhone, onlyDigits } from "@/lib/documents";
import { money } from "@/lib/format";
import { notify } from "@/state/toast";
import { Button, cx, Empty, Field, IconButton, Input, Segmented, Select, Spinner } from "@/ui";

import AddressFields from "./AddressFields";

type Pick = { customer?: string | null; customer_document?: string };
const blankAddress = (): Address => ({ label: "Casa", zip_code: "", street: "", number: "", complement: "", district: "",
  city: "", state: "", reference: "", is_default: true });
const blank = () => ({ person_type: "F" as "F" | "J", name: "", document: "", phone: "", email: "", notes: "" });

/** O cliente escolhido (a venda local guarda nome e documento sem perguntar ao servidor). */
export type Known = { id: string; name: string; document: string; credit_balance?: string };

/** Sem servidor: a lista guardada no PC (os clientes mais recentes), filtrada aqui. */
async function offlineList(term: string, page: number, pageSize: number, ordering: string) {
  const snap = await window.starrp.offline.snapshot();
  const words = term.toLowerCase().split(/\s+/).filter(Boolean);
  const field = ordering.replace(/^-/, "") as "name" | "document" | "phone" | "email";
  const direction = ordering.startsWith("-") ? -1 : 1;
  const rows = (snap?.customers ?? [])
    .filter((c) => words.every((w) => `${c.name} ${c.document} ${c.phone} ${c.email}`.toLowerCase().includes(w)))
    .sort((a, b) => String(a[field] ?? "").localeCompare(String(b[field] ?? ""), "pt-BR") * direction);
  const results = rows.slice((page - 1) * pageSize, page * pageSize) as unknown as Awaited<ReturnType<typeof customersApi.list>>["results"];
  return { count: rows.length, next: null, previous: null, results };
}

export default function CustomersPanel({ current, busy, offline = false, onPick, onBack }: {
  current: { name: string; document: string } | null; busy: boolean; offline?: boolean; onPick: (body: Pick, known?: Known) => void; onBack: () => void;
}) {
  const [mode, setMode] = useState<"list" | "document" | "new">("list");
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [ordering, setOrdering] = useState("name");
  useEffect(() => {
    const t = setTimeout(() => {
      setTerm(search.trim());
      setPage(1);
    }, 250);
    return () => clearTimeout(t);
  }, [search]);
  const list = useQuery({
    queryKey: ["pdv-customers", term, page, pageSize, ordering, offline],
    queryFn: () => (offline ? offlineList(term, page, pageSize, ordering) : customersApi.list(term, page, ordering, pageSize)),
    placeholderData: (p) => p,
  });

  const [doc, setDoc] = useState("");
  const docError = doc ? documentError(doc) : null;

  const [draft, setDraft] = useState(blank);
  const [address, setAddress] = useState<Address | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  function useDocument(event: FormEvent) {
    event.preventDefault();
    if (!doc || docError) return;
    onPick({ customer: null, customer_document: onlyDigits(doc) });
    setDoc("");
    setMode("list");
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (!draft.name.trim()) found.name = "Informe o nome.";
    const docMsg = draft.document ? documentError(draft.document) : null;
    if (docMsg) found.document = docMsg;
    if (draft.email && !/^\S+@\S+\.\S+$/.test(draft.email)) found.email = "E-mail inválido.";
    setErrors(found);
    if (Object.keys(found).length) return notify.warn("Confira os campos destacados.");
    if (address && (address.zip_code.length !== 8 || !address.street || !address.number)) {
      return notify.warn("Endereço incompleto: CEP, logradouro e número são obrigatórios para entregar.");
    }
    setSaving(true);
    try {
      const created = await customersApi.create({
        ...draft, document: onlyDigits(draft.document), phone: onlyDigits(draft.phone), addresses: address ? [address] : [],
      });
      notify.success("Cliente cadastrado e vinculado à venda", address ? "Para entregar, abra Entrega (Shift+F11) e escolha a cotação." : undefined);
      onPick({ customer: created.id }, {
        id: created.id, name: created.name, document: created.document ?? "", credit_balance: created.credit_balance,
      });
      setDraft(blank());
      setAddress(null);
      setMode("list");
    } catch (error) {
      const apiError = notify.error(error, "Não foi possível cadastrar o cliente");
      setErrors(apiError.fields);
    } finally {
      setSaving(false);
    }
  }

  const rows = list.data?.results ?? [];
  const total = list.data?.count ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total ? (page - 1) * pageSize + 1 : 0;
  const last = Math.min(page * pageSize, total);
  const sortBy = (field: string) => {
    const current = ordering.replace(/^-/, "");
    setOrdering(current !== field ? field : ordering.startsWith("-") ? "name" : `-${field}`);
    setPage(1);
  };

  return (
    <section className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
      <header className="flex items-center gap-2.5">
        <IconButton icon="pi pi-arrow-left" label="Voltar para a venda" onClick={onBack} />
        <div className="flex-1">
          <h2 className="panel-title">Cliente da venda</h2>
          <p className="text-[13px] text-muted">
            {current ? <>Vinculado: <b>{current.name || formatDocument(current.document)}</b></> : "Escolha na lista, informe só o CPF na nota ou cadastre na hora."}
          </p>
        </div>
        {current && <Button variant="ghost" icon="pi pi-user-minus" disabled={busy} onClick={() => onPick({ customer: null, customer_document: "" })}>Tirar cliente</Button>}
      </header>

      {mode === "document" && (
        <form className="flex flex-col gap-3 rounded-[10px] border border-line bg-card p-3.5" onSubmit={useDocument}>
          <Field label="CPF ou CNPJ na nota" error={docError}>
            <Input autoFocus value={doc} onChange={(e) => setDoc(maskDocument(e.target.value))} invalid={!!docError} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setMode("list")}>Voltar</Button>
            <Button type="submit" icon="pi pi-check" disabled={!doc || !!docError}>Usar na nota</Button>
          </div>
        </form>
      )}

      {mode === "new" && (
        <form className="flex flex-col gap-3 rounded-[10px] border border-line bg-card p-3.5" onSubmit={create}>
          <div className="grid grid-cols-6 gap-2">
            <Field label="Tipo" className="col-span-6">
              <Segmented value={draft.person_type} onChange={(v) => setDraft({ ...draft, person_type: v })} className="self-start"
                options={[{ value: "F", label: "Pessoa física" }, { value: "J", label: "Empresa" }]} />
            </Field>
            <Field label="CPF / CNPJ" error={errors.document} className="col-span-2">
              <Input autoFocus value={draft.document} onChange={(e) => setDraft({ ...draft, document: maskDocument(e.target.value) })} invalid={!!errors.document} />
            </Field>
            <Field label="Nome / razão social" error={errors.name} className="col-span-4">
              <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} invalid={!!errors.name} />
            </Field>
            <Field label="Telefone / WhatsApp" error={errors.phone} className="col-span-2">
              <Input value={draft.phone} onChange={(e) => setDraft({ ...draft, phone: maskPhone(e.target.value) })} />
            </Field>
            <Field label="E-mail" error={errors.email} className="col-span-4">
              <Input type="email" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} invalid={!!errors.email} />
            </Field>
            <Field label="Observações (aparecem no PDV)" className="col-span-6">
              <Input value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />
            </Field>
          </div>
          <div className="flex flex-col gap-2 border-t border-dashed border-line pt-3">
            <span className="flex items-center gap-1.5 text-[13px] font-bold text-strong">
              <i className="pi pi-map-marker" /> Endereço de entrega <small className="font-normal text-muted">(opcional; o CEP preenche o resto)</small>
            </span>
            {address ? (
              <>
                <AddressFields value={address} onChange={setAddress} />
                <Button variant="ghost" size="sm" icon="pi pi-times" className="self-start" onClick={() => setAddress(null)}>Sem endereço</Button>
              </>
            ) : (
              <Button variant="secondary" size="sm" icon="pi pi-plus" className="self-start" onClick={() => setAddress(blankAddress())}>Adicionar endereço</Button>
            )}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setMode("list")}>Voltar</Button>
            <Button type="submit" icon="pi pi-user-plus" loading={saving}>Cadastrar e vincular</Button>
          </div>
        </form>
      )}

      {mode === "list" && (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[10px] border border-line bg-card">
          <div className="flex flex-wrap items-center gap-2 border-b border-line-subtle p-2.5">
            <div className="relative min-w-[220px] flex-1">
              <i className="pi pi-search absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
              <Input autoFocus value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar por nome, CPF ou telefone…" className="pl-9" />
            </div>
            <Button variant="secondary" size="sm" icon="pi pi-id-card" onClick={() => setMode("document")}>CPF na nota</Button>
            <Button size="sm" icon="pi pi-user-plus" disabled={offline} title={offline ? "Cadastrar cliente precisa do servidor" : undefined} onClick={() => setMode("new")}>Novo cliente</Button>
            <span className="text-[12.5px] text-muted">{total.toLocaleString("pt-BR")} {total === 1 ? "registro" : "registros"}</span>
            <IconButton icon={list.isFetching ? "pi pi-spin pi-spinner" : "pi pi-refresh"} label="Atualizar"
              disabled={list.isFetching} onClick={() => void list.refetch()} />
          </div>
          {list.isPending ? <Spinner label="Carregando clientes…" /> : !rows.length ? (
            <Empty icon="pi pi-users" title="Nenhum cliente encontrado">Use "Novo cliente" para cadastrar agora.</Empty>
          ) : (
            <div className="min-h-0 flex-1 overflow-auto">
              <table className="min-w-[900px] w-full text-[13px]">
                <thead className="sticky top-0 z-[1] bg-card text-left text-[11.5px] tracking-wide text-muted uppercase shadow-[0_1px_0_var(--border-subtle)]">
                  <tr>
                    <CustomerSortHeader field="name" label="Cliente" ordering={ordering} onSort={sortBy} />
                    <CustomerSortHeader field="document" label="CPF/CNPJ" ordering={ordering} onSort={sortBy} />
                    <CustomerSortHeader field="phone" label="Telefone" ordering={ordering} onSort={sortBy} />
                    <CustomerSortHeader field="email" label="E-mail" ordering={ordering} onSort={sortBy} />
                    <th className="px-3 py-2 text-right font-bold">Vale-troca</th>
                    <th className="w-16 px-3 py-2 text-right font-bold">Ação</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.id} tabIndex={0} onClick={() => onPick({ customer: c.id }, {
                      id: c.id, name: c.name, document: c.document ?? "", credit_balance: c.credit_balance,
                    })}
                      onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget
                        && onPick({ customer: c.id }, {
                          id: c.id, name: c.name, document: c.document ?? "", credit_balance: c.credit_balance,
                        })}
                      className="cursor-pointer border-b border-line-subtle last:border-0 hover:bg-hover focus:bg-hover focus:outline-0">
                      <td className="px-3 py-2.5 font-semibold text-strong">{c.name}</td>
                      <td className="px-3 py-2.5">{c.document ? formatDocument(c.document) : "—"}</td>
                      <td className="px-3 py-2.5">{c.phone ? maskPhone(c.phone) : "—"}</td>
                      <td className="px-3 py-2.5">{c.email || "—"}</td>
                      <td className="px-3 py-2.5 text-right">{money(c.credit_balance ?? 0)}</td>
                      <td className="px-2 py-1.5 text-right"><IconButton icon="pi pi-check" label={`Selecionar ${c.name}`} className="ml-auto size-8" /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {total > 0 && (
            <div className="relative mt-auto flex min-h-12 items-center justify-center gap-2 border-t border-line-subtle p-2 text-[12.5px] text-muted">
              <label className="absolute left-3 flex items-center gap-2">Linhas
                <Select value={pageSize} options={[{ value: 10, label: "10" }, { value: 20, label: "20" }, { value: 50, label: "50" }]}
                  onChange={(value) => { if (value) { setPageSize(value); setPage(1); } }} className="h-8 w-18 py-0" />
              </label>
              <IconButton icon="pi pi-chevron-left" label="Anterior" disabled={page <= 1} onClick={() => setPage(page - 1)} />
              Página {page} de {pages}
              <IconButton icon="pi pi-chevron-right" label="Próxima" disabled={page >= pages} onClick={() => setPage(page + 1)} />
              <span className="absolute right-3">{first}–{last} de {total}</span>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function CustomerSortHeader({ field, label, ordering, onSort }: {
  field: string; label: string; ordering: string; onSort: (field: string) => void;
}) {
  const active = ordering.replace(/^-/, "") === field;
  const icon = !active ? "pi pi-sort-alt" : ordering.startsWith("-") ? "pi pi-sort-amount-down" : "pi pi-sort-amount-up";
  return (
    <th className="px-3 py-2" aria-sort={active ? (ordering.startsWith("-") ? "descending" : "ascending") : "none"}>
      <button type="button" onClick={() => onSort(field)} className="inline-flex items-center gap-1 font-bold hover:text-brand-text">
        {label}<i className={cx(icon, "text-[10px]", active ? "text-brand-text" : "text-subtle")} />
      </button>
    </th>
  );
}
