/** Peças de interface do PDV (botão, diálogo, campos), no lugar do PrimeVue da versão web. */
import {
  type ButtonHTMLAttributes, type ComponentProps, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, useEffect,
  useRef,
} from "react";

import { useStore } from "@/state/store";
import { dismiss, toasts } from "@/state/toast";

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

/* ---------------------------------------------------------------- Botão */
type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand text-on-brand border-brand hover:enabled:bg-brand-hover",
  secondary: "bg-card text-body border-line-strong hover:enabled:border-brand-border hover:enabled:bg-hover",
  ghost: "bg-transparent text-muted border-transparent hover:enabled:bg-hover hover:enabled:text-strong",
  danger: "bg-danger text-white border-danger hover:enabled:opacity-90",
  success: "bg-success text-white border-success hover:enabled:opacity-90",
};
const SIZES = { sm: "h-8 px-3 text-[12.5px] gap-1.5", md: "h-10 px-4 text-[13.5px] gap-2", lg: "h-12 px-5 text-[15px] gap-2" };

export function Button({ variant = "primary", size = "md", icon, loading, children, className, ...rest }:
  ComponentProps<"button"> & { variant?: Variant; size?: keyof typeof SIZES; icon?: string; loading?: boolean }) {
  return (
    <button type="button" {...rest} disabled={rest.disabled || loading}
      className={cx("inline-flex shrink-0 items-center justify-center rounded-lg border font-semibold whitespace-nowrap transition-colors",
        "disabled:opacity-50", VARIANTS[variant], SIZES[size], className)}>
      {loading ? <i className="pi pi-spin pi-spinner" /> : icon ? <i className={icon} /> : null}
      {children}
    </button>
  );
}

export function IconButton({ icon, label, className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { icon: string; label: string }) {
  return (
    <button type="button" aria-label={label} title={label} {...rest}
      className={cx("grid size-9 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-hover hover:text-strong disabled:opacity-40", className)}>
      <i className={icon} />
    </button>
  );
}

export const Kbd = ({ children, className }: { children: ReactNode; className?: string }) => (
  <kbd className={cx("kbd", className)}>{children}</kbd>
);

export const Spinner = ({ label }: { label?: string }) => (
  <p className="flex items-center justify-center gap-2 p-6 text-[13px] text-muted"><i className="pi pi-spin pi-spinner" /> {label}</p>
);

/* ---------------------------------------------------------------- Diálogo */
/** Modal com fundo escuro. Esc fecha (se `onClose`). `data-dialog` deixa o PDV saber que há um aberto. */
export function Dialog({ open, title, onClose, children, footer, width = 420, bare = false }: {
  open: boolean; title?: ReactNode; onClose?: () => void; children: ReactNode; footer?: ReactNode; width?: number; bare?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && onClose) {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    // Foco dentro do diálogo: o leitor de código / Enter não vai para a busca atrás.
    const t = setTimeout(() => {
      if (!box.current?.contains(document.activeElement)) {
        box.current?.querySelector<HTMLElement>("[autofocus], input:not([disabled]), button:not([disabled])")?.focus();
      }
    });
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div data-dialog className="fixed inset-0 z-50 grid place-items-center bg-overlay p-3 animate-fade-up"
      onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div ref={box} role="dialog" aria-modal="true" style={{ width: `min(${width}px, 100%)` }}
        className="flex max-h-[calc(100vh-24px)] flex-col overflow-hidden rounded-2xl border border-line bg-card shadow-panel">
        {!bare && (
          <header className="flex items-center justify-between gap-3 px-5 pt-4 pb-2">
            <h2 className="text-[16px] font-bold text-strong">{title}</h2>
            {onClose && <IconButton icon="pi pi-times" label="Fechar (Esc)" onClick={onClose} className="-mr-2" />}
          </header>
        )}
        <div className={cx("min-h-0 overflow-y-auto", bare ? "" : "px-5 pb-4")}>{children}</div>
        {footer && <footer className="flex flex-wrap justify-end gap-2 border-t border-line-subtle px-5 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- Campos */
export function Field({ label, error, hint, children, className }: {
  label?: ReactNode; error?: string | null; hint?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <label className={cx("flex min-w-0 flex-col gap-1", className)}>
      {label && <span className="label">{label}</span>}
      {children}
      {error ? <small className="text-[12px] font-semibold text-danger-text">{error}</small>
        : hint ? <small className="text-[12px] text-muted">{hint}</small> : null}
    </label>
  );
}

export const Input = ({ className, invalid, ...rest }: ComponentProps<"input"> & { invalid?: boolean }) => (
  <input {...rest} aria-invalid={invalid || undefined} className={cx("input", className)} />
);

export function Select<T extends string | number>({ value, options, onChange, placeholder, className, ...rest }:
  Omit<SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange"> & {
    value: T | null; options: { value: T; label: string; disabled?: boolean }[]; onChange: (value: T | null) => void;
    placeholder?: string;
  }) {
  return (
    <select {...rest} value={value === null ? "" : String(value)} className={cx("input pr-8", className)}
      onChange={(e) => {
        const found = options.find((o) => String(o.value) === e.target.value);
        onChange(found ? found.value : null);
      }}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => <option key={String(o.value)} value={String(o.value)} disabled={o.disabled}>{o.label}</option>)}
    </select>
  );
}

export function Segmented<T extends string>({ value, options, onChange, className }: {
  value: T; options: { value: T; label: string }[]; onChange: (value: T) => void; className?: string;
}) {
  return (
    <div role="radiogroup" className={cx("inline-flex rounded-lg border border-line bg-sunken p-0.5", className)}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={cx("h-8 rounded-md px-3 text-[12.5px] font-semibold whitespace-nowrap transition-colors",
            value === o.value ? "bg-card text-brand-text shadow-sm" : "text-muted hover:text-strong")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Valor em R$ digitado como no caixa: dígitos entram pela direita (centavos). */
export function MoneyInput({ value, onChange, className, ...rest }:
  Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & { value: number | null; onChange: (v: number) => void }) {
  const cents = Math.round((value ?? 0) * 100);
  return (
    <div className={cx("input flex items-center gap-2", className)}>
      <span className="font-bold text-muted">R$</span>
      <input {...rest} inputMode="numeric" autoComplete="off" className="min-w-0 flex-1 bg-transparent text-right outline-0"
        value={(cents / 100).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
        onChange={(e) => onChange(Number(e.target.value.replace(/\D/g, "").slice(-11) || "0") / 100)} />
    </div>
  );
}

export function Empty({ icon, title, children }: { icon: string; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-12 text-center text-muted">
      <span className="grid size-13 place-items-center rounded-xl bg-sunken text-xl"><i className={icon} /></span>
      <strong className="text-[14px] text-strong">{title}</strong>
      {children && <small className="text-[12.5px]">{children}</small>}
    </div>
  );
}

const TONES: Record<string, string> = {
  success: "bg-success-subtle text-success-text", warning: "bg-warning-subtle text-warning-text",
  danger: "bg-danger-subtle text-danger-text", brand: "bg-brand-subtle text-brand-text", info: "bg-brand-subtle text-brand-text",
  neutral: "bg-sunken text-muted",
};
export const Tag = ({ tone = "neutral", children }: { tone?: string; children: ReactNode }) => (
  <span className={cx("inline-flex rounded-md px-2 py-0.5 text-[11.5px] font-bold whitespace-nowrap", TONES[tone] ?? TONES.neutral)}>{children}</span>
);

/* ---------------------------------------------------------------- Avisos */
const TOAST_STYLE = {
  success: ["pi pi-check-circle", "text-success-text"],
  warn: ["pi pi-exclamation-triangle", "text-warning-text"],
  error: ["pi pi-times-circle", "text-danger-text"],
} as const;

export function Toaster() {
  const list = useStore(toasts);
  return (
    <div className="pointer-events-none fixed top-14 right-4 z-[70] flex w-[min(380px,calc(100vw-32px))] flex-col gap-2">
      {list.map((t) => (
        <div key={t.id} role="status" className="pointer-events-auto flex gap-3 rounded-xl border border-line bg-card p-3 shadow-panel animate-fade-up">
          <i className={cx(TOAST_STYLE[t.severity][0], TOAST_STYLE[t.severity][1], "mt-0.5")} />
          <div className="min-w-0 flex-1">
            <strong className="block text-[13.5px] text-strong">{t.summary}</strong>
            {t.detail && <small className="text-[12.5px] text-muted">{t.detail}</small>}
          </div>
          <button type="button" aria-label="Fechar aviso" className="text-subtle hover:text-strong" onClick={() => dismiss(t.id)}>
            <i className="pi pi-times text-[11px]" />
          </button>
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- Liga/desliga */
export function Toggle({ checked, onChange, label, hint, disabled }: {
  checked: boolean; onChange: (value: boolean) => void; label: ReactNode; hint?: ReactNode; disabled?: boolean;
}) {
  return (
    <label className={cx("flex cursor-pointer items-start gap-3 py-1.5", disabled && "cursor-not-allowed opacity-50")}>
      <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
        className={cx("relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors", checked ? "bg-brand" : "bg-line-strong")}>
        <span className={cx("absolute top-0.5 size-4 rounded-full bg-white shadow transition-all", checked ? "left-[18px]" : "left-0.5")} />
      </button>
      <span className="flex flex-col">
        <span className="text-[13.5px] font-semibold text-strong">{label}</span>
        {hint && <small className="text-[12px] text-muted">{hint}</small>}
      </span>
    </label>
  );
}
