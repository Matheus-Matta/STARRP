/**
 * Copia o vocabulário dos cadastros da retaguarda (frontend/src/resources/types.ts) para o app,
 * só para o TypeScript do app conhecer o formato. Em execução, o app usa os arquivos da retaguarda.
 * Rode de novo quando o types.ts da retaguarda mudar: `npm run front:types`.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const source = readFileSync(resolve(root, "../frontend/src/resources/types.ts"), "utf8");
const out = source
  .replace(/import type \{ Component \} from "vue";\n/, "type Component = unknown;\n")
  .replace(/import type \{ FormatName \} from "@\/utils\/formats";\n/, "type FormatName = string;\n");
if (/^import /m.test(out)) throw new Error("types.ts da retaguarda ganhou um import novo: ajuste este script.");
writeFileSync(resolve(root, "src/shared/types.ts"),
  `/* Gerado por scripts/sync-front-types.mjs a partir de frontend/src/resources/types.ts. Não edite. */\n${out}`);
console.log("src/shared/types.ts atualizado");
