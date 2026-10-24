import { describe, expect, it } from "vitest";
import { ref } from "vue";

import { useBulkSelection } from "@/composables/useBulkSelection";

const page = (...ids: string[]) => ids.map((id) => ({ id }));

describe("seleção para ações em massa", () => {
  it("cabeçalho: 1º clique marca a página, 2º marca todos, 3º limpa", () => {
    const rows = ref(page("a", "b"));
    const sel = useBulkSelection(rows, ref(57));

    sel.cycleHeader();
    expect(sel.header.value).toBe("page");
    expect(sel.target({})).toEqual({ ids: ["a", "b"] });

    sel.cycleHeader();
    expect(sel.header.value).toBe("all");
    expect(sel.count.value).toBe(57);
    expect(sel.target({ search: "x" })).toEqual({ all: true, filters: { search: "x" } });

    sel.cycleHeader();
    expect(sel.header.value).toBe("none");
    expect(sel.count.value).toBe(0);
  });

  it("lista de uma página só: 2º clique já desmarca", () => {
    const sel = useBulkSelection(ref(page("a", "b")), ref(2));
    sel.cycleHeader();
    sel.cycleHeader();
    expect(sel.header.value).toBe("none");
  });

  it("desmarcar uma linha com 'todos' volta para a página menos ela", () => {
    const sel = useBulkSelection(ref(page("a", "b", "c")), ref(90));
    sel.selectAll();
    sel.toggle("b");
    expect(sel.all.value).toBe(false);
    expect(sel.target({})).toEqual({ ids: ["a", "c"] });
    expect(sel.header.value).toBe("partial");
  });

  it("marcações sobrevivem à troca de página", () => {
    const rows = ref(page("a", "b"));
    const sel = useBulkSelection(rows, ref(4));
    sel.toggle("a");
    rows.value = page("c", "d");
    sel.toggle("d");
    expect(sel.count.value).toBe(2);
    expect(sel.isSelected("a")).toBe(true);
  });
});
