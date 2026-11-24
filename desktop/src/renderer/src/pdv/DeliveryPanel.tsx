/**
 * Entrega DENTRO do PDV: o endereço do cliente da venda (ou um novo, guardado no cliente) e a
 * cotação de TODAS as tabelas de frete para o CEP — cada uma com valor e prazo; as que não atendem
 * dizem por quê. Escolher uma lança o frete no total. "Retirar na loja" marca a retirada.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { customersApi, logisticsApi } from "@/api/pdv";
import { type Address, deliveryOf, type Sale } from "@/api/types";
import { cep, money } from "@/lib/format";
import { notify } from "@/state/toast";
import { Button, cx, IconButton } from "@/ui";

import AddressFields from "./AddressFields";

export default function DeliveryPanel({ sale, busy, onApply, onPickup, onCustomer, onBack }: {
  sale: Sale | null; busy: boolean; onApply: (address: string, table: string) => void; onPickup: () => void;
  onCustomer: () => void; onBack: () => void;
}) {
  const client = useQueryClient();
  const customerId = sale?.customer ?? null;
  const customer = useQuery({
    queryKey: ["pdv-delivery-customer", customerId],
    queryFn: () => customersApi.get(customerId!),
    enabled: Boolean(customerId),
  });
  const addresses = customer.data?.addresses ?? [];
  const [chosen, setChosen] = useState<string | null>(null);

  useEffect(() => {
    const current = sale?.shipping_address;
    if (current && addresses.some((a) => a.id === current)) setChosen(current);
    else if (!addresses.some((a) => a.id === chosen)) setChosen((addresses.find((a) => a.is_default) ?? addresses[0])?.id ?? null);
  }, [addresses, sale?.shipping_address]); // eslint-disable-line react-hooks/exhaustive-deps

  const address = addresses.find((a) => a.id === chosen) ?? null;
  const quotes = useQuery({
    queryKey: ["pdv-freight", address?.zip_code],
    queryFn: () => logisticsApi.quote(address!.zip_code),
    enabled: (address?.zip_code ?? "").length === 8,
    staleTime: 60_000,
  });
  const { delivery, pickup } = deliveryOf(sale);

  const [adding, setAdding] = useState<Address | null>(null);
  const [saving, setSaving] = useState(false);
  const startNew = () => setAdding({ label: addresses.length ? "" : "Casa", zip_code: "", street: "", number: "", complement: "",
    district: "", city: "", state: "", reference: "", is_default: !addresses.length });

  async function saveNew() {
    if (!adding || adding.zip_code.length !== 8 || !adding.street || !adding.number) {
      return notify.error(new Error("Preencha CEP, logradouro e número."), "Endereço incompleto");
    }
    setSaving(true);
    try {
      const saved = await customersApi.update(customerId!, {
        addresses: [...addresses.map((a) => ({ ...a, is_default: adding.is_default ? false : a.is_default })), adding],
      });
      client.setQueryData(["pdv-delivery-customer", customerId], saved);
      const fresh = saved.addresses?.find((a) => a.zip_code === adding.zip_code && a.street === adding.street && a.number === adding.number);
      if (fresh?.id) setChosen(fresh.id);
      setAdding(null);
    } catch (error) {
      notify.error(error, "Endereço não salvo");
    } finally {
      setSaving(false);
    }
  }

  const line = (a: Address) => [[a.street, a.number].filter(Boolean).join(", "), a.complement].filter(Boolean).join(" · ");
  const place = (a: Address) => [a.district, [a.city, a.state].filter(Boolean).join(" - ")].filter(Boolean).join(" · ");

  return (
    <section className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
      <header className="flex items-center gap-2.5">
        <IconButton icon="pi pi-arrow-left" label="Voltar para a venda" onClick={onBack} />
        <div className="flex-1">
          <h2 className="panel-title">Entrega</h2>
          <p className="text-[13px] text-muted">{sale?.customer_name ? `Para ${sale.customer_name}` : "Escolha o endereço e a forma de entrega."}</p>
        </div>
        <Button variant={pickup ? "primary" : "secondary"} icon={pickup ? "pi pi-check" : "pi pi-shop"} disabled={busy || !sale || pickup} onClick={onPickup}>
          {pickup ? "Retirada na loja" : "Retirar na loja"}
        </Button>
      </header>

      {!customerId ? (
        <div className="flex flex-col items-center gap-2.5 px-3 py-10 text-center text-muted">
          <i className="pi pi-user text-[2rem]" />
          <p>Para entregar, identifique o cliente da venda (o endereço fica no cadastro dele).</p>
          <Button icon="pi pi-user-plus" onClick={onCustomer}>Escolher cliente (F3)</Button>
        </div>
      ) : (
        <>
          <Step n={1}>Endereço</Step>
          {customer.isPending ? <p className="text-[13px] text-muted"><i className="pi pi-spin pi-spinner" /> Carregando os endereços…</p> : (
            <div role="radiogroup" aria-label="Endereço de entrega" className="grid grid-cols-[repeat(auto-fill,minmax(min(240px,100%),1fr))] gap-2">
              {addresses.map((a) => (
                <button key={a.id} type="button" role="radio" aria-checked={chosen === a.id} onClick={() => setChosen(a.id ?? null)}
                  className={cx("flex min-w-0 flex-col gap-1 rounded-[10px] border px-3.5 py-3 text-left",
                    chosen === a.id ? "border-brand bg-brand-subtle" : "border-line bg-card hover:border-brand-border")}>
                  <span className="flex items-center gap-1.5 text-strong">
                    <i className={cx(chosen === a.id ? "pi pi-check-circle" : "pi pi-map-marker", "text-brand")} />
                    <strong>{a.label}</strong>{a.is_default && <small className="ml-auto font-semibold text-warning-text">★ padrão</small>}
                  </span>
                  <span className="truncate text-[12.5px] text-body">{line(a) || "Sem logradouro"}</span>
                  <span className="truncate text-[12.5px] text-muted">{place(a)} · {cep(a.zip_code)}</span>
                  {a.reference && <small className="text-[12px] text-muted">Ref.: {a.reference}</small>}
                </button>
              ))}
              {!adding && (
                <button type="button" onClick={startNew}
                  className="flex flex-col items-center justify-center gap-1 rounded-[10px] border border-dashed border-line px-3.5 py-3 text-center text-brand-text hover:border-brand-border">
                  <i className="pi pi-plus" /><strong>Novo endereço</strong><small className="text-muted">Fica guardado no cadastro do cliente</small>
                </button>
              )}
            </div>
          )}
          {adding && (
            <div className="flex flex-col gap-2 rounded-xl border border-line bg-sunken p-3">
              <AddressFields value={adding} onChange={setAdding} />
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setAdding(null)}>Cancelar</Button>
                <Button icon="pi pi-check" loading={saving} onClick={() => void saveNew()}>Salvar endereço</Button>
              </div>
            </div>
          )}

          {address && (
            <>
              <Step n={2}>Frete para {cep(address.zip_code)}</Step>
              {quotes.isPending ? <p className="text-[13px] text-muted"><i className="pi pi-spin pi-spinner" /> Cotando as tabelas de frete…</p>
                : !quotes.data?.length ? <p className="text-[13px] text-muted">Nenhuma tabela de frete ativa. Cadastre em <b>Configurações → Tabelas de frete</b>.</p>
                  : (
                    <div className="grid grid-cols-[repeat(auto-fill,minmax(min(240px,100%),1fr))] gap-2">
                      {quotes.data.map((q) => {
                        const active = delivery?.table === q.table && sale?.shipping_address === address.id;
                        return (
                          <button key={q.table} type="button" disabled={q.value === null || busy} onClick={() => onApply(address.id!, q.table)}
                            className={cx("flex min-w-0 flex-col gap-1 rounded-[10px] border px-3.5 py-3 text-left",
                              q.value === null ? "cursor-not-allowed border-dashed border-line opacity-60"
                                : active ? "border-brand bg-brand-subtle" : "border-line bg-card hover:border-brand-border")}>
                            <span className="flex items-center gap-1.5 text-[13.5px] font-bold text-strong"><i className="pi pi-truck text-brand" /> {q.table_name}</span>
                            {q.value !== null ? (
                              <>
                                <strong className="text-[20px] leading-tight font-extrabold text-strong">{Number(q.value) ? money(q.value) : "Grátis"}</strong>
                                <span className="text-[12px] text-muted">
                                  {q.lead_days === 0 ? "No mesmo dia" : `${q.lead_days} dia(s) útil(eis)`}{q.detail && ` · ${q.detail}`}
                                </span>
                              </>
                            ) : <span className="flex gap-1.5 text-[12px] text-muted"><i className="pi pi-ban" /> {q.error}</span>}
                          </button>
                        );
                      })}
                    </div>
                  )}
            </>
          )}
        </>
      )}
    </section>
  );
}

const Step = ({ n, children }: { n: number; children: React.ReactNode }) => (
  <h3 className="mt-1.5 flex items-center gap-2 text-[14px] font-bold text-strong">
    <span className="grid size-[22px] place-items-center rounded-full bg-brand-subtle text-[12px] text-brand-text">{n}</span> {children}
  </h3>
);
