import { describe, expect, it } from "vitest";

import { ApiError } from "@/api/errors";
import { buildNavigation } from "@/components/layout/navigation";
import { ApprovalCancelled, useApprovalDialog, withApproval } from "@/composables/useApproval";
import { resources } from "@/resources";

const needsManager = () => new ApiError(403, "discount_approval_required", "Acima do limite");

describe("autorização de gerente", () => {
  it("repete a MESMA ação com a autorização informada", async () => {
    const calls: unknown[] = [];
    const action = async (approval?: unknown) => {
      calls.push(approval);
      if (!approval) throw needsManager();
      return "ok";
    };
    const result = withApproval(action);
    await Promise.resolve();
    useApprovalDialog().answer({ username: "gerente", password: "x" });

    expect(await result).toBe("ok");
    expect(calls).toEqual([undefined, { username: "gerente", password: "x" }]);
  });

  it("fechar o diálogo cancela a operação", async () => {
    const result = withApproval(async () => {
      throw needsManager();
    });
    await Promise.resolve();
    useApprovalDialog().answer(null);

    await expect(result).rejects.toBeInstanceOf(ApprovalCancelled);
  });

  it("erro comum não abre diálogo", async () => {
    await expect(withApproval(async () => {
      throw new ApiError(409, "conflict", "Venda fechada");
    })).rejects.toMatchObject({ code: "conflict" });
    expect(useApprovalDialog().pending.value).toBeNull();
  });
});

describe("menu", () => {
  it("só mostra o que o cargo pode ver e o que o plano tem", () => {
    const can = (code?: string) => !code || code.startsWith("catalog.") || code === "sales.manage";
    const groups = buildNavigation(can, (module) => module !== "finance");
    const labels = groups.flatMap((g) => g.items.map((i) => i.label));

    expect(labels).toContain("Produtos");
    expect(labels).toContain("PDV");
    expect(labels).not.toContain("Clientes");
    expect(labels).not.toContain("Contas financeiras");
  });

  it("todo cadastro tem nome de rota único", () => {
    const names = resources.map((r) => r.name);
    expect(new Set(names).size).toBe(names.length);
  });
});
