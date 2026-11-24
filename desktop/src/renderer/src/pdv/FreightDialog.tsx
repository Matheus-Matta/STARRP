/**
 * Conferir frete (Shift+F5): "quanto fica para entregar?" antes de comprar. Por CEP ou pelo
 * endereço completo. Só consulta: lançar a entrega na venda é em Entrega (Shift+F11).
 */
import { type FormEvent, useEffect, useState } from "react";

import { toApiError } from "@/api/errors";
import { logisticsApi } from "@/api/pdv";
import type { FreightQuote } from "@/api/types";
import { maskCep } from "@/lib/documents";
import { cep, money } from "@/lib/format";
import { Button, cx, Dialog, Field, Input, Segmented } from "@/ui";

type Estimate = { zip_code: string | null; address: Record<string, string> | null; point: [string, string] | null; quotes: FreightQuote[] };
const blank = { street: "", number: "", district: "", city: "", state: "" };

export default function FreightDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [mode, setMode] = useState<"zip" | "address">("zip");
  const [zip, setZip] = useState("");
  const [address, setAddress] = useState(blank);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Estimate | null>(null);

  useEffect(() => {
    if (!open) return;
    setResult(null);
    setError("");
  }, [open]);

  async function check(event: FormEvent) {
    event.preventDefault();
    setError("");
    const digits = zip.replace(/\D/g, "");
    if (mode === "zip" && digits.length !== 8) return setError("Digite o CEP com 8 dígitos.");
    if (mode === "address" && (!address.street || !address.city || address.state.length !== 2)) {
      return setError("Informe logradouro, cidade e UF (o número ajuda a medir a distância exata).");
    }
    setLoading(true);
    try {
      setResult(await logisticsApi.estimate(mode === "zip" ? { zip: digits } : address));
    } catch (failure) {
      setResult(null);
      setError(toApiError(failure).message);
    } finally {
      setLoading(false);
    }
  }

  const set = (key: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setAddress({ ...address, [key]: key === "state" ? e.target.value.toUpperCase().slice(0, 2) : e.target.value });
  const place = (a: Record<string, string>) => [a.street, a.district, [a.city, a.state].filter(Boolean).join(" - ")].filter(Boolean).join(" · ");

  return (
    <Dialog open={open} title="Conferir frete" onClose={onClose} width={640}>
      <form className="flex flex-col gap-3" onSubmit={check}>
        <Segmented value={mode} onChange={setMode} className="self-start"
          options={[{ value: "zip", label: "Por CEP" }, { value: "address", label: "Endereço completo" }]} />
        {mode === "zip" ? (
          <div className="flex gap-2">
            <Input autoFocus value={zip} onChange={(e) => setZip(maskCep(e.target.value))} placeholder="00000-000" className="w-40" />
            <Button type="submit" icon="pi pi-calculator" loading={loading}>Calcular</Button>
          </div>
        ) : (
          <div className="grid grid-cols-12 gap-2">
            <Field label="Logradouro" className="col-span-8"><Input autoFocus value={address.street} onChange={set("street")} placeholder="Av. Paulista" /></Field>
            <Field label="Número" className="col-span-4"><Input value={address.number} onChange={set("number")} /></Field>
            <Field label="Bairro" className="col-span-5"><Input value={address.district} onChange={set("district")} /></Field>
            <Field label="Cidade" className="col-span-5"><Input value={address.city} onChange={set("city")} /></Field>
            <Field label="UF" className="col-span-2"><Input value={address.state} onChange={set("state")} /></Field>
            <Button type="submit" icon="pi pi-calculator" loading={loading} className="col-span-12">Calcular</Button>
          </div>
        )}
        {error && <p className="flex items-center gap-1.5 text-[13px] font-semibold text-danger-text"><i className="pi pi-exclamation-circle" /> {error}</p>}
        {result && (
          <div className="flex flex-col gap-2">
            <p className="flex flex-wrap items-center gap-1.5 text-[13px] text-body">
              <i className="pi pi-map-marker text-brand" />
              {result.address ? `${place(result.address)} · CEP ${cep(result.zip_code)}`
                : result.zip_code ? `CEP ${cep(result.zip_code)}` : "CEP não encontrado (as tabelas por faixa não atendem)"}
              {result.point && <small className="text-muted">· distância até o endereço exato</small>}
            </p>
            <ul className="flex flex-col gap-1.5">
              {result.quotes.map((q) => (
                <li key={q.table} className={cx("flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-[10px] border border-line px-3 py-2.5",
                  q.value === null && "border-dashed opacity-60")}>
                  <span className="flex items-center gap-1.5 text-[13.5px] font-bold text-strong"><i className="pi pi-truck text-brand" /> {q.table_name}</span>
                  {q.value !== null ? (
                    <>
                      <strong className="ml-auto text-[17px] text-strong">{Number(q.value) ? money(q.value) : "Grátis"}</strong>
                      <small className="w-full text-[12px] text-muted">
                        {q.lead_days === 0 ? "no mesmo dia" : `${q.lead_days} dia(s) útil(eis)`}{q.detail && ` · ${q.detail}`}
                      </small>
                    </>
                  ) : <small className="w-full text-[12px] text-muted"><i className="pi pi-ban" /> {q.error}</small>}
                </li>
              ))}
              {!result.quotes.length && <li className="text-[13px] text-muted">Nenhuma tabela de frete ativa.</li>}
            </ul>
          </div>
        )}
      </form>
    </Dialog>
  );
}
