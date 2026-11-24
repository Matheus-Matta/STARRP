import { describe, expect, it } from "vitest";

import { resetTokenFrom } from "@/utils/resetToken";

describe("resetTokenFrom", () => {
  it("lê o token do fragmento do link", () => {
    expect(resetTokenFrom("#token=a-b_C1")).toBe("a-b_C1");
  });

  it("sem token, pede o e-mail", () => {
    expect(resetTokenFrom("")).toBe("");
    expect(resetTokenFrom("#outra=coisa")).toBe("");
  });
});
