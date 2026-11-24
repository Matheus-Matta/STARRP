/**
 * Exportar e compartilhar: o arquivo vai para a folha de compartilhamento do celular (WhatsApp, e-mail, Drive...).
 *  - `shareDownload`: arquivo que o backend gera (Excel e CSV dos relatórios, CSV das listas);
 *  - `sharePdf`: PDF montado no aparelho a partir dos modelos de impressão da retaguarda (`src/print`);
 *  - `printDocument`: abre a impressão do sistema (impressora ou "Salvar como PDF").
 * No navegador (Expo web, para desenvolvimento) baixa o arquivo / abre a impressão.
 */
import { File, Paths } from "expo-file-system";
import * as Print from "expo-print";
import * as Sharing from "expo-sharing";
import { Platform } from "react-native";

import { download, type Params } from "@/api/client";

const web = Platform.OS === "web";

/** Nome de arquivo seguro: "Vendas no período 01-11.pdf" → "Vendas-no-periodo-01-11.pdf". */
export function fileName(base: string, ext: string) {
  const clean = base.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^\w.-]+/g, "-").replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  return `${clean || "documento"}.${ext}`;
}

function webSave(bytes: Uint8Array, name: string, type: string) {
  const blob = new Blob([bytes as BlobPart], { type });
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

async function shareBytes(bytes: Uint8Array, name: string, type: string, title: string) {
  if (web) return webSave(bytes, name, type);
  const file = new File(Paths.cache, name);
  if (file.exists) file.delete();
  file.create();
  await file.write(bytes);
  await shareUri(file.uri, type, title);
}

async function shareUri(uri: string, type: string, title: string) {
  if (!(await Sharing.isAvailableAsync())) throw new Error("Este aparelho não permite compartilhar arquivos.");
  await Sharing.shareAsync(uri, { mimeType: type, dialogTitle: title, UTI: type === "application/pdf" ? "com.adobe.pdf" : undefined });
}

/** Arquivo gerado pelo backend (GET ou POST), com o nome que ele mandou. */
export async function shareDownload(method: "GET" | "POST", path: string, options: { params?: Params; body?: unknown },
                                    fallbackName: string, title: string) {
  const { bytes, filename, type } = await download(method, path, options);
  await shareBytes(bytes, filename ?? fallbackName, type, title);
}

/** PDF do documento HTML (A4), compartilhado. */
export async function sharePdf(html: string, name: string, title: string) {
  if (web) return Print.printAsync({ html });
  const { uri } = await Print.printToFileAsync({ html, base64: false });
  const target = new File(Paths.cache, name);
  if (target.exists) target.delete();
  await new File(uri).move(target);
  await shareUri(target.uri, "application/pdf", title);
}

/** Impressão do sistema (escolher impressora ou salvar como PDF). */
export async function printDocument(html: string) {
  await Print.printAsync({ html });
}
