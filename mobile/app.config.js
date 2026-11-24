/**
 * Configuração do Expo = app.json + o que vem do `.env` da raiz do monorepo.
 * `API_URL` (ex.: http://localhost:8001) vira o servidor PADRÃO do app (`extra.apiUrl`): é o que aparece já
 * preenchido em "Servidor" na tela de login. O usuário pode trocar ali (fica salvo no aparelho).
 */
const fs = require("fs");
const path = require("path");

function readEnv(file) {
  try {
    return Object.fromEntries(fs.readFileSync(file, "utf8").split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#") && line.includes("="))
      .map((line) => {
        const i = line.indexOf("=");
        return [line.slice(0, i).trim(), line.slice(i + 1).trim().replace(/^["']|["']$/g, "")];
      }));
  } catch {
    return {};
  }
}

module.exports = ({ config }) => {
  const env = { ...readEnv(path.join(__dirname, "../.env")), ...process.env };
  const apiUrl = env.EXPO_PUBLIC_API_URL || env.API_URL || "";
  // Build de produção (eas build --profile production): o servidor padrão é HTTPS ou nenhum. O app de produção
  // recusa http:// de qualquer jeito (src/api/client.ts); aqui o erro aparece já no build, não no celular.
  if (env.APP_VARIANT === "production" && /^http:\/\//i.test(apiUrl)) {
    throw new Error(`API_URL do build de produção precisa ser https:// (está ${apiUrl}).`);
  }
  return {
    ...config,
    extra: { ...config.extra, apiUrl },
  };
};
