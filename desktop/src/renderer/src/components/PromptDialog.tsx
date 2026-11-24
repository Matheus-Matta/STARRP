/**
 * Pergunta rápida com um campo (motivo, código de cupom, valor de desconto). Com `options`, o
 * motivo é um toque num dos botões fixos; "Outro motivo" abre o campo para escrever.
 */
import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button, cx, Dialog, Input, MoneyInput, Segmented } from "@/ui";

export type PromptSpec = {
  title: string;
  label: string;
  kind: "text" | "discount";
  confirmLabel?: string;
  required?: boolean;
  options?: string[];
  danger?: boolean;
};
export type PromptAnswer = { text?: string; amount?: string; percent?: string };

const OTHER = "__other__";

export default function PromptDialog({ spec, onAnswer }: { spec: PromptSpec | null; onAnswer: (value: PromptAnswer | null) => void }) {
  const [text, setText] = useState("");
  const [choice, setChoice] = useState<string | null>(null);
  const [number, setNumber] = useState<number | null>(null);
  const [percentText, setPercentText] = useState("");
  const [unit, setUnit] = useState<"percent" | "amount">("percent");
  const [error, setError] = useState("");
  const textRef = useRef<HTMLInputElement>(null);

  const presets = spec?.options ?? [];
  const typing = !presets.length || choice === OTHER;

  useEffect(() => {
    setText("");
    setChoice(null);
    setNumber(null);
    setPercentText("");
    setError("");
  }, [spec]);

  function pick(option: string) {
    setChoice(option);
    setError("");
    if (option === OTHER) setTimeout(() => textRef.current?.focus());
  }

  function confirm(event: FormEvent) {
    event.preventDefault();
    if (spec?.kind === "discount") {
      if (unit === "percent") {
        const pct = Number(percentText.replace(",", "."));
        if (!percentText || Number.isNaN(pct)) return;
        onAnswer({ percent: pct.toFixed(2) });
      } else {
        if (number === null) return;
        onAnswer({ amount: number.toFixed(2) });
      }
      return;
    }
    const value = typing ? text.trim() : (choice ?? "");
    if (presets.length && !choice) return setError("Escolha um motivo.");
    if ((spec?.required || choice === OTHER) && !value) return setError("Escreva o motivo.");
    onAnswer({ text: value });
  }

  return (
    <Dialog open={spec !== null} title={spec?.title} onClose={() => onAnswer(null)} width={presets.length ? 500 : 400}>
      <form className="flex flex-col gap-3" onSubmit={confirm}>
        <span className="text-[13.5px] text-body">{spec?.label}</span>
        {spec?.kind === "discount" ? (
          <>
            <Segmented value={unit} onChange={setUnit} className="self-start"
              options={[{ value: "percent", label: "%" }, { value: "amount", label: "R$" }]} />
            {unit === "percent" ? (
              <div className="input flex items-center gap-2">
                <input autoFocus inputMode="decimal" value={percentText} placeholder="0,00"
                  onChange={(e) => setPercentText(e.target.value.replace(/[^\d,.]/g, ""))}
                  className="min-w-0 flex-1 bg-transparent text-right outline-0" />
                <span className="font-bold text-muted">%</span>
              </div>
            ) : (
              <MoneyInput autoFocus value={number} onChange={setNumber} />
            )}
          </>
        ) : (
          <>
            {presets.length > 0 && (
              <div role="radiogroup" className="grid grid-cols-2 gap-1.5">
                {[...presets, OTHER].map((option) => (
                  <button key={option} type="button" role="radio" aria-checked={choice === option} onClick={() => pick(option)}
                    className={cx("flex items-center gap-2 rounded-lg border px-3 py-2.5 text-left text-[13px] font-semibold transition-colors",
                      choice === option ? "border-brand bg-brand-subtle text-brand-text" : "border-line bg-card text-body hover:border-brand-border hover:bg-hover")}>
                    <i className={cx(option === OTHER ? "pi pi-pencil" : choice === option ? "pi pi-check-circle" : "pi pi-circle",
                      choice === option ? "text-brand" : "text-muted")} />
                    {option === OTHER ? "Outro motivo" : option}
                  </button>
                ))}
              </div>
            )}
            {typing && (
              <Input ref={textRef} value={text} onChange={(e) => setText(e.target.value)} autoFocus={!presets.length}
                placeholder={presets.length ? "Escreva o motivo" : undefined} invalid={!!error} />
            )}
          </>
        )}
        {error && <small className="flex items-center gap-1.5 font-semibold text-danger-text"><i className="pi pi-exclamation-circle" /> {error}</small>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => onAnswer(null)}>Voltar</Button>
          <Button type="submit" variant={spec?.danger ? "danger" : "primary"}>{spec?.confirmLabel ?? "Confirmar"}</Button>
        </div>
      </form>
    </Dialog>
  );
}
