/** Campos de endereço: o CEP completo preenche logradouro, bairro, cidade, UF e IBGE. */
import { useState } from "react";

import { lookupCep } from "@/lib/cep";
import { maskCep } from "@/lib/documents";
import { Field, Input } from "@/ui";

export type AddressLike = {
  zip_code: string; street: string; number: string; complement: string; district: string; city: string; state: string;
  city_ibge?: string; reference: string;
};

export default function AddressFields<T extends AddressLike>({ value, onChange, disabled, extra }: {
  value: T; onChange: (next: T) => void; disabled?: boolean; extra?: React.ReactNode;
}) {
  const [looking, setLooking] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const set = (key: keyof AddressLike) => (e: React.ChangeEvent<HTMLInputElement>) =>
    onChange({ ...value, [key]: key === "state" ? e.target.value.toUpperCase().slice(0, 2) : e.target.value });

  async function zipChanged(raw: string) {
    const digits = raw.replace(/\D/g, "").slice(0, 8);
    const next = { ...value, zip_code: digits };
    onChange(next);
    setNotFound(false);
    if (digits.length !== 8) return;
    setLooking(true);
    const found = await lookupCep(digits);
    setLooking(false);
    if (!found) return setNotFound(true);
    onChange({ ...next, street: found.street || next.street, district: found.district || next.district, city: found.city,
      state: found.state, city_ibge: found.city_ibge, complement: next.complement || found.complement });
  }

  return (
    <div className="grid grid-cols-12 gap-2">
      <Field label="CEP" className="col-span-3" error={notFound ? "CEP não encontrado: preencha à mão." : null}
        hint={looking ? <><i className="pi pi-spin pi-spinner text-[10px]" /> Buscando…</> : undefined}>
        <Input value={maskCep(value.zip_code)} disabled={disabled} placeholder="00000-000" onChange={(e) => void zipChanged(e.target.value)} />
      </Field>
      <Field label="Logradouro" className="col-span-7"><Input value={value.street} disabled={disabled} onChange={set("street")} /></Field>
      <Field label="Número" className="col-span-2"><Input value={value.number} disabled={disabled} onChange={set("number")} /></Field>
      <Field label="Complemento" className="col-span-4"><Input value={value.complement} disabled={disabled} onChange={set("complement")} /></Field>
      <Field label="Bairro" className="col-span-3"><Input value={value.district} disabled={disabled} onChange={set("district")} /></Field>
      <Field label="Cidade" className="col-span-3"><Input value={value.city} disabled={disabled} onChange={set("city")} /></Field>
      <Field label="UF" className="col-span-2"><Input value={value.state} disabled={disabled} onChange={set("state")} /></Field>
      <Field label="Ponto de referência" className="col-span-12"><Input value={value.reference} disabled={disabled} onChange={set("reference")} /></Field>
      {extra}
    </div>
  );
}
