/**
 * Tela bloqueada do caixa: cobre o PDV inteiro. Volta com a senha do próprio operador ou a senha
 * de ações do caixa (o gerente que veio liberar). Fechar e abrir o app NÃO desbloqueia.
 */
import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button, Input } from "@/ui";

export default function Lock({ operator, managerPassword, unlock, onLogout }: {
  operator: string; managerPassword: boolean; unlock: (password: string) => Promise<void>; onLogout: () => void;
}) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError("");
    try {
      await unlock(password);
    } catch {
      setError("Senha incorreta.");
      setPassword("");
      input.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="dialog" aria-modal="true" aria-label="Caixa bloqueado" data-dialog
      className="fixed inset-0 z-[60] grid place-items-center p-4 backdrop-blur-xl"
      style={{ background: "color-mix(in srgb, var(--surface-ground) 70%, transparent)" }}>
      <form onSubmit={submit}
        className="flex w-[min(380px,100%)] flex-col items-center gap-3 rounded-2xl border border-line bg-card px-6 py-7 text-center shadow-panel">
        <span className="grid size-14 place-items-center rounded-full bg-brand-subtle text-[22px] text-brand"><i className="pi pi-lock" /></span>
        <h2 className="text-[20px] font-extrabold text-strong">Caixa bloqueado</h2>
        <p className="text-[13.5px] text-muted">
          Operador: <b>{operator}</b>. Digite a sua senha{managerPassword ? " ou a senha de ações do caixa" : ""} para voltar.
        </p>
        <Input ref={input} type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Senha"
          className="h-12" invalid={!!error} />
        {error && <small className="flex items-center gap-1.5 self-start font-semibold text-danger-text"><i className="pi pi-exclamation-circle" /> {error}</small>}
        <Button type="submit" size="lg" icon="pi pi-lock-open" loading={busy} className="w-full">Desbloquear</Button>
        <Button variant="ghost" size="sm" icon="pi pi-sign-out" onClick={onLogout}>Trocar de operador (sair)</Button>
      </form>
    </div>
  );
}
