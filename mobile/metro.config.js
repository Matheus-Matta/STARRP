/**
 * Bundler do app. O app usa as MESMAS definições da retaguarda (cadastros, menu, relatórios,
 * validação, máscaras): os arquivos de `frontend/src` entram no bundle pelo apelido `@front/...`.
 *
 * Dentro desses arquivos:
 *  - `@/x` aponta para `frontend/src/x` (o apelido do próprio frontend);
 *  - o que só existe no navegador vira um substituto móvel (`src/shared/shims`): o cliente HTTP
 *    (vai pelo cliente do app, com token e filial), a impressão, as etiquetas, o roteador (vue-router → Expo Router) e o Vue
 *    (diálogos e telas próprias da retaguarda viram um marcador "só na retaguarda").
 */
const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");
const { withUniwindConfig } = require("uniwind/metro");

const config = getDefaultConfig(__dirname);

const FRONT = path.resolve(__dirname, "../frontend/src");
const SHIMS = path.resolve(__dirname, "src/shared/shims");
/** Por caminho dentro de frontend/src (vale para `@/api/http` e para `./http`). */
const SHIMMED = {
  "api/http": "http.ts",
  "utils/print": "print.ts",
  "utils/labels": "labels.ts",
  // O roteador da retaguarda (vue-router) vira a navegação do app (ações que abrem outra tela ao terminar).
  router: "router.ts",
  "router/index": "router.ts",
};

const lower = (p) => p.toLowerCase();
const inFront = (file) => lower(file).startsWith(lower(FRONT));

config.watchFolders = [...(config.watchFolders ?? []), FRONT];
// Pacotes que os arquivos da retaguarda importam (zod) vêm do node_modules do app.
config.resolver.nodeModulesPaths = [...(config.resolver.nodeModulesPaths ?? []), path.resolve(__dirname, "node_modules")];

config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (moduleName.startsWith("@front/")) {
    return context.resolveRequest(context, path.join(FRONT, moduleName.slice("@front/".length)), platform);
  }
  if (inFront(context.originModulePath)) {
    if (moduleName === "vue") return { type: "sourceFile", filePath: path.join(SHIMS, "vue.ts") };
    if (moduleName === "vue-router") return { type: "sourceFile", filePath: path.join(SHIMS, "router.ts") };
    if (moduleName.endsWith(".vue")) return { type: "sourceFile", filePath: path.join(SHIMS, "component.ts") };
    const target = moduleName.startsWith("@/") ? path.join(FRONT, moduleName.slice(2))
      : moduleName.startsWith(".") ? path.resolve(path.dirname(context.originModulePath), moduleName) : null;
    if (target) {
      const key = path.relative(FRONT, target).split(path.sep).join("/").replace(/\.ts$/, "");
      if (SHIMMED[key]) return { type: "sourceFile", filePath: path.join(SHIMS, SHIMMED[key]) };
      if (moduleName.startsWith("@/")) return context.resolveRequest(context, target, platform);
    }
  }
  return context.resolveRequest(context, moduleName, platform);
};

// Tailwind (Uniwind): className nos componentes, com o tema gerado do CSS da retaguarda (src/global.css).
// Precisa ser o último "wrapper"; o resolver acima continua valendo (o Uniwind o chama).
module.exports = withUniwindConfig(config, {
  cssEntryFile: "./src/global.css",
  dtsFile: "./src/uniwind-types.d.ts",
  polyfills: { rem: 16 },
});
