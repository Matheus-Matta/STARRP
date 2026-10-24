import { nextTick } from "vue";
import { describe, expect, it } from "vitest";

import { useTheme } from "@/composables/useTheme";

describe("tema claro/escuro", () => {
  it("marca o <html> para os nossos tokens E para o PrimeVue, e lembra a escolha", async () => {
    const theme = useTheme();

    theme.setMode("dark");
    await nextTick();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("starrp.theme")).toBe("dark");

    theme.toggle();
    await nextTick();
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("no automático não grava escolha (segue o sistema)", () => {
    useTheme().setMode("system");
    expect(localStorage.getItem("starrp.theme")).toBeNull();
  });
});
