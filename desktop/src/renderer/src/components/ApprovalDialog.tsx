/** Pede a autorização de um superior (montado uma vez, na raiz). Ver `state/approval.ts`. */
import { type FormEvent, useEffect, useState } from "react";

import { answerApproval, approvalPending } from "@/state/approval";
import { useStore } from "@/state/store";
import { Button, Dialog, Input, Segmented } from "@/ui";

export default function ApprovalDialog() {
  const pending = useStore(approvalPending);
  const [mode, setMode] = useState<"manager" | "cash">("manager");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!pending) return;
    setUsername("");
    setPassword("");
    setReason("");
  }, [pending]);

  function confirm(event: FormEvent) {
    event.preventDefault();
    if (!password || (pending?.reasonLabel && !reason.trim())) return;
    answerApproval({
      approval: mode === "cash" ? { cash_password: password } : { username, password },
      reason: reason.trim(),
    });
  }

  return (
    <Dialog open={pending !== null} title="Autorização necessária" width={420}>
      <form className="flex flex-col gap-3" onSubmit={confirm}>
        <p className="text-[13.5px] text-muted">{pending?.message}</p>
        <Segmented value={mode} onChange={setMode} className="self-start"
          options={[{ value: "manager", label: "Gerente" }, { value: "cash", label: "Senha do caixa" }]} />
        {mode === "manager" && <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Usuário do gerente" autoFocus />}
        <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus={mode === "cash"}
          placeholder={mode === "cash" ? "Senha do caixa da filial" : "Senha"} />
        {pending?.reasonLabel && (
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500}
            placeholder={pending.reasonLabel} className="input h-auto py-2" />
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => answerApproval(null)}>Cancelar</Button>
          <Button type="submit" icon="pi pi-lock-open">Autorizar</Button>
        </div>
      </form>
    </Dialog>
  );
}
