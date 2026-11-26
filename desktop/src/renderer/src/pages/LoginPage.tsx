/**
 * Login do PDV pela API (`POST /auth/login/`). O processo principal guarda o access e o refresh
 * token (criptografados); a tela só recebe "deu certo" e carrega o usuário.
 * A engrenagem troca o endereço do servidor (fica salvo neste computador).
 */
import { type FormEvent, useState } from "react";

import { serverUrlProblem } from "../../../shared/serverUrl";
import { toApiError } from "@/api/errors";
import { login, saveConfig, session, toggleTheme } from "@/state/session";
import { useStore } from "@/state/store";
import { Button, Field, IconButton, Input } from "@/ui";

const FEATURES = [
  { icon: "pi pi-shopping-cart", title: "PDV rápido", text: "Leitor de código, balança, vários pagamentos e troco." },
  { icon: "pi pi-wallet", title: "Caixa na mão", text: "Abertura cega, sangria, suprimento e fechamento conferido." },
  { icon: "pi pi-truck", title: "Entrega no balcão", text: "Cotação de frete por CEP e endereço do cliente." },
];

export default function LoginPage() {
  const { config } = useStore(session);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [editingServer, setEditingServer] = useState(false);
  const [server, setServer] = useState(config?.serverUrl ?? "");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!username || !password) return;
    setError("");
    setLoading(true);
    try {
      const me = await login(username.trim(), password);
      if (!me) throw new Error("Seu usuário não está vinculado a nenhuma conta.");
      if (!me.stores.length) throw new Error("Seu usuário não tem acesso a nenhuma filial.");
    } catch (e) {
      const apiError = toApiError(e);
      setError(apiError.status === 401 ? "Usuário ou senha incorretos." : apiError.message);
      setPassword("");
    } finally {
      setLoading(false);
    }
  }

  async function saveServer() {
    const problem = serverUrlProblem(server, import.meta.env.PROD);
    if (problem) {
      setError(problem);
      return;
    }
    try {
      await saveConfig({ serverUrl: server });
    } catch (e) {
      setError(e instanceof Error ? e.message.replace(/^Error invoking remote method '[^']+': Error: /, "") : String(e));
      return;
    }
    setEditingServer(false);
    setError("");
  }

  return (
    <div className="grid h-full grid-cols-1 bg-ground lg:grid-cols-[minmax(380px,1fr)_minmax(420px,1.1fr)]">
      <aside className="relative hidden flex-col gap-10 overflow-hidden p-12 text-[#e6fffb] lg:flex"
        style={{ background: "radial-gradient(120% 90% at 0% 0%, var(--brand-400) 0%, var(--brand-700) 45%, var(--brand-950) 100%)" }}>
        <img src="./logo-white.png" alt="Starrp" className="relative z-10 h-[38px] w-auto self-start" />
        <div className="mt-auto">
          <h1 className="max-w-[440px] text-[34px] leading-[1.15] font-extrabold tracking-tight text-white">PDV de balcão, rápido e no seu computador.</h1>
          <p className="mt-3 text-[15px] text-white/80">Venda, caixa e entrega conectados à retaguarda do Starrp.</p>
        </div>
        <ul className="flex flex-col gap-3.5">
          {FEATURES.map((f) => (
            <li key={f.title} className="flex items-start gap-3 rounded-xl border border-white/10 bg-white/5 p-3">
              <span className="grid size-[34px] shrink-0 place-items-center rounded-lg bg-white/15 text-white"><i className={f.icon} /></span>
              <div><strong className="block text-[14px] text-white">{f.title}</strong><small className="text-[12.5px] text-white/75">{f.text}</small></div>
            </li>
          ))}
        </ul>
        <small className="text-white/55">© {new Date().getFullYear()} Starrp</small>
        <span className="pointer-events-none absolute -right-36 -bottom-40 size-[420px] rounded-full bg-white/5" />
      </aside>

      <main className="relative grid place-items-center p-8">
        <div className="absolute top-5 right-5 flex gap-2">
          <IconButton icon="pi pi-cog" label="Servidor" className="rounded-lg border border-line bg-card" onClick={() => setEditingServer((v) => !v)} />
          <IconButton icon={config?.theme === "dark" ? "pi pi-sun" : "pi pi-moon"} label="Tema"
            className="rounded-lg border border-line bg-card" onClick={() => void toggleTheme()} />
        </div>
        <form className="flex w-[min(400px,100%)] flex-col gap-4 animate-fade-up" onSubmit={submit}>
          <img src={config?.theme === "dark" ? "./logo-light.png" : "./logo.png"} alt="Starrp" className="mb-2 h-[34px] w-auto self-start object-contain lg:hidden" />
          <h2 className="text-[28px] leading-none font-extrabold tracking-tight text-strong">Entrar no PDV</h2>
          <p className="-mt-2 text-[13.5px] text-muted">Use o usuário e a senha fornecidos pelo administrador da sua filial.</p>

          {editingServer && (
            <div className="flex flex-col gap-2 rounded-xl border border-line bg-card p-3">
              <Field label="Endereço do servidor" hint="Onde o Starrp está rodando (sem /api/v1).">
                <Input value={server} onChange={(e) => setServer(e.target.value)} placeholder="http://localhost:8001" />
              </Field>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => setEditingServer(false)}>Cancelar</Button>
                <Button size="sm" icon="pi pi-check" onClick={() => void saveServer()}>Salvar</Button>
              </div>
            </div>
          )}

          {error && (
            <p role="alert" className="flex items-center gap-2 rounded-lg bg-danger-subtle px-3 py-2.5 text-[13px] font-semibold text-danger-text">
              <i className="pi pi-exclamation-circle" /> {error}
            </p>
          )}
          <Field label="Usuário">
            <div className="relative">
              <i className="pi pi-user absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
              <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus className="h-12 pl-9" />
            </div>
          </Field>
          <Field label="Senha">
            <div className="relative">
              <Input type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password" className="h-12 pr-10" />
              <button type="button" tabIndex={-1} aria-label={showPassword ? "Esconder senha" : "Mostrar senha"}
                className="absolute top-1/2 right-3 -translate-y-1/2 text-muted hover:text-strong" onClick={() => setShowPassword((v) => !v)}>
                <i className={showPassword ? "pi pi-eye-slash" : "pi pi-eye"} />
              </button>
            </div>
          </Field>
          <Button type="submit" size="lg" loading={loading} disabled={!username || !password}>
            Entrar <i className="pi pi-arrow-right" />
          </Button>
          <small className="text-center text-[12px] text-subtle">Servidor: {config?.serverUrl}</small>
        </form>
      </main>
    </div>
  );
}
