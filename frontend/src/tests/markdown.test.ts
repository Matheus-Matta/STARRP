import { describe, expect, it } from "vitest";

import { renderMarkdown } from "@/utils/markdown";

describe("renderMarkdown (respostas da Cosmos)", () => {
  it("escapa HTML vindo do texto", () => {
    const html = renderMarkdown('Produto <script>alert(1)</script> "x"');
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });

  it("formata negrito, listas e tabela", () => {
    const html = renderMarkdown("**Total:** R$ 10\n\n- um\n- dois\n\n| A | B |\n|---|---|\n| 1 | 2 |");
    expect(html).toContain("<strong>Total:</strong>");
    expect(html).toContain("<ul><li>um</li><li>dois</li></ul>");
    expect(html).toContain("<th>A</th>");
    expect(html).toContain("<td>2</td>");
  });

  it("só aceita links internos e https", () => {
    expect(renderMarkdown("[Abrir](/relatorios/vendas)")).toContain('data-internal="1"');
    expect(renderMarkdown("[x](javascript:alert(1))")).not.toContain("<a");
    expect(renderMarkdown("[Site](https://exemplo.com)")).toContain('target="_blank"');
  });
});
