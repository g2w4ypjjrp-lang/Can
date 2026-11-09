import { describe, expect, it } from "vitest";
import { formatKeyInput } from "./License";

describe("lisans anahtarı girişi", () => {
  it("yazarken ATI-XXXX-XXXX-XXXX-XXXX biçimine getirir", () => {
    expect(formatKeyInput("ati7xk9")).toBe("ATI-7XK9");
    expect(formatKeyInput("7xk9 pq82 mn45 zr61")).toBe("ATI-7XK9-PQ82-MN45-ZR61");
    expect(formatKeyInput("ATI-7XK9-PQ82-MN45-ZR61-FAZLA")).toBe("ATI-7XK9-PQ82-MN45-ZR61");
    expect(formatKeyInput("")).toBe("");
    expect(formatKeyInput("!!")).toBe("");
  });
});
