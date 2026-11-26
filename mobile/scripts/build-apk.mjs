// Gera o APK do Android SEM o EAS (sem conta Expo): `expo prebuild` + Gradle, no PC ou no GitHub Actions.
//
// Uso: npm run build:apk                 → dist/Starrp-<versão do app.json>.apk
//      npm run build:apk -- 1.2.3        → grava a versão 1.2.3 (e o versionCode dela) antes de gerar
//
// Precisa do Java 17 e do SDK do Android (ANDROID_HOME; no Windows o padrão do Android Studio é achado sozinho).
// No Windows o C++ do React Native estoura o limite de 260 caracteres de caminho: lá, gere pelo GitHub (tag
// mobile-v...) ou com o repositório num caminho bem curto (ex.: C:\s).
// Servidor padrão do app: API_URL (do ambiente ou do .env da raiz), sempre https:// no build de produção.
//
// Assinatura: sem nada, o APK sai com a chave de DEBUG do modelo do React Native (pública: serve para testar e
// instalar na loja, mas qualquer um assina um APK "igual"). Para a chave da empresa, defina ANDROID_KEYSTORE
// (caminho do .jks), ANDROID_KEYSTORE_PASSWORD, ANDROID_KEY_ALIAS e ANDROID_KEY_PASSWORD (opcional = a do keystore).
// Troca de chave = o Android pede para desinstalar o app antigo antes; escolha a definitiva cedo.
import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const win = process.platform === "win32";
const env = { ...process.env, CI: "1", APP_VARIANT: "production" };

if (!env.ANDROID_HOME && !env.ANDROID_SDK_ROOT) {
  const guess = win ? join(env.LOCALAPPDATA ?? "", "Android", "Sdk") : join(homedir(), "Android", "Sdk");
  if (!existsSync(guess)) throw new Error("SDK do Android não encontrado: defina ANDROID_HOME.");
  env.ANDROID_HOME = guess;
}

function run(cmd, args, cwd = root) {
  console.log(`\n> ${cmd} ${args.join(" ")}`);
  execFileSync(cmd, args, { cwd, env, stdio: "inherit", shell: win });
}

// Versão: a do argumento (tag mobile-vX.Y.Z) vai para o app.json; versionCode = X·10000 + Y·100 + Z.
const appFile = join(root, "app.json");
const app = JSON.parse(readFileSync(appFile, "utf8"));
const wanted = process.argv[2]?.replace(/^v/, "").replace(/-.*/, "");
if (wanted) {  // sem argumento (build no PC), o app.json fica como está
  if (!/^\d+\.\d+\.\d+$/.test(wanted)) throw new Error(`Versão inválida: ${process.argv[2]}`);
  const [x, y, z] = wanted.split(".").map(Number);
  if (y > 99 || z > 99) throw new Error("Versão com menor/correção acima de 99 não cabe no versionCode.");
  app.expo.version = wanted;
  app.expo.android.versionCode = Math.max(1, x * 10000 + y * 100 + z);
  writeFileSync(appFile, JSON.stringify(app, null, 2) + "\n");
}
const version = app.expo.version;
console.log(`Starrp ${version} (versionCode ${app.expo.android.versionCode ?? 1})`);

// O prebuild troca o script "android" do package.json (expo run:android): volta como estava.
const pkgFile = join(root, "package.json");
const pkg = readFileSync(pkgFile, "utf8");
run("npx", ["expo", "prebuild", "--platform", "android", "--clean", "--no-install"]);
writeFileSync(pkgFile, pkg);
const android = join(root, "android");
// Só os processadores dos celulares de verdade (sem x86 de emulador): APK menor e build mais rápido.
run(win ? "gradlew.bat" : "./gradlew",
    ["assembleRelease", "--no-daemon", "-PreactNativeArchitectures=armeabi-v7a,arm64-v8a"], android);

const built = join(android, "app", "build", "outputs", "apk", "release", "app-release.apk");
mkdirSync(join(root, "dist"), { recursive: true });
const out = join(root, "dist", `Starrp-${version}.apk`);

if (env.ANDROID_KEYSTORE) {
  // Reassina com a chave da empresa (o apksigner troca a assinatura de debug).
  const tools = join(env.ANDROID_HOME ?? env.ANDROID_SDK_ROOT, "build-tools");
  const latest = readdirSync(tools).sort((a, b) => a.localeCompare(b, undefined, { numeric: true })).pop();
  const apksigner = join(tools, latest, win ? "apksigner.bat" : "apksigner");
  if (!env.ANDROID_KEYSTORE_PASSWORD || !env.ANDROID_KEY_ALIAS) {
    throw new Error("Com ANDROID_KEYSTORE, defina também ANDROID_KEYSTORE_PASSWORD e ANDROID_KEY_ALIAS.");
  }
  env.ANDROID_KEY_PASSWORD ||= env.ANDROID_KEYSTORE_PASSWORD;
  run(apksigner, ["sign", "--ks", env.ANDROID_KEYSTORE, "--ks-key-alias", env.ANDROID_KEY_ALIAS,
                  "--ks-pass", "env:ANDROID_KEYSTORE_PASSWORD", "--key-pass", "env:ANDROID_KEY_PASSWORD",
                  "--out", out, built]);
  run(apksigner, ["verify", out]);
  console.log("\nAssinado com a chave da empresa.");
} else {
  copyFileSync(built, out);
  console.log("\nAVISO: assinado com a chave de DEBUG (ANDROID_KEYSTORE não definido).");
}
console.log(`APK: ${out}`);
