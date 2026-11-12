/**
 * Markdown leve das respostas da Cosmos → HTML SEGURO.
 *
 * Tudo é escapado ANTES de virar marcação (o texto do modelo pode repetir dado digitado por
 * qualquer um: um `<script>` no nome do produto sai como texto). Cobre o que a Cosmos usa:
 * títulos, negrito, itálico, `código`, blocos de código, listas, tabelas e links internos
 * (`/rota`) ou https.
 */
const escape = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

function inline(text: string) {
  return escape(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\(((?:https:\/\/|\/)[^)\s]*)\)/g, (_m, label: string, href: string) => {
      const external = href.startsWith("https://");
      return `<a href="${href}" data-internal="${external ? "" : "1"}"${external ? ' target="_blank" rel="noopener"' : ""}>${label}</a>`;
    });
}

const isRow = (line: string) => /^\s*\|.*\|\s*$/.test(line);
const cells = (line: string) => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

export function renderMarkdown(source: string) {
  const lines = (source ?? "").replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i]!;
    if (line.startsWith("```")) {
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i]!.startsWith("```")) code.push(lines[i++]!);
      out.push(`<pre><code>${escape(code.join("\n"))}</code></pre>`);
      i += 1;
      continue;
    }
    if (isRow(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1]!)) {
      const head = cells(line);
      i += 2;
      const body: string[][] = [];
      while (i < lines.length && isRow(lines[i]!)) body.push(cells(lines[i++]!));
      out.push(`<div class="md-table"><table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead>`
        + `<tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      out.push(`<h${heading[1]!.length + 2}>${inline(heading[2]!)}</h${heading[1]!.length + 2}>`);
      i += 1;
      continue;
    }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i]!)) {
        items.push(`<li>${inline(lines[i]!.replace(/^\s*([-*•]|\d+[.)])\s+/, ""))}</li>`);
        i += 1;
      }
      out.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
      continue;
    }
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i]!.trim() && !/^(#{1,4}\s|```|\s*([-*•]|\d+[.)])\s)/.test(lines[i]!) && !isRow(lines[i]!)) {
      para.push(inline(lines[i++]!));
    }
    out.push(`<p>${para.join("<br>")}</p>`);
  }
  return out.join("");
}
