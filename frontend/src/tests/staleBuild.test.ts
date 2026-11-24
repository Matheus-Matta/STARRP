import { describe, expect, it } from "vitest";

import { isStaleChunkError } from "@/utils/staleBuild";

describe("deploy novo com a aba aberta", () => {
  it("reconhece o erro de tela da versão anterior (Chrome, Firefox, Safari)", () => {
    expect(isStaleChunkError(new TypeError("Failed to fetch dynamically imported module: https://x/assets/A-1.js"))).toBe(true);
    expect(isStaleChunkError(new TypeError("error loading dynamically imported module"))).toBe(true);
    expect(isStaleChunkError(new TypeError("Importing a module script failed."))).toBe(true);
    expect(isStaleChunkError(new Error("Request failed with status code 500"))).toBe(false);
    expect(isStaleChunkError("texto")).toBe(false);
  });
});
