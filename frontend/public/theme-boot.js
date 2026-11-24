// Aplica o tema ANTES de pintar (sem isto a tela pisca clara no modo escuro). Arquivo, não script inline:
// o CSP do app (frontend/Caddyfile) só deixa rodar script do próprio site (S-23).
try {
  var t = localStorage.getItem("starrp.theme");
  var dark = t === "dark" || (!t && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  if (dark) document.documentElement.classList.add("dark");
  var b = localStorage.getItem("starrp.brand");
  if (b) document.documentElement.dataset.brand = b;
} catch (e) {}
