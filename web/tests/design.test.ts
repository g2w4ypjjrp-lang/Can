import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_DESIGN, fetchDesign, isDesign } from "@/lib/design";

afterEach(() => vi.unstubAllEnvs());

describe("tasarım modu", () => {
  it("yalnızca bilinen tasarımları kabul eder", () => {
    expect(isDesign("zumrut")).toBe(true);
    expect(isDesign("bilinmeyen")).toBe(false);
    expect(isDesign(3)).toBe(false);
  });

  it("API'den okur; hata ya da bozuk yanıtta varsayılana döner", async () => {
    vi.stubEnv("ATI_API_URL", "http://api.test");
    const ok = vi.fn(async () => new Response(JSON.stringify({ design: "altin" })));
    expect(await fetchDesign(ok as unknown as typeof fetch)).toBe("altin");
    expect(ok).toHaveBeenCalledWith("http://api.test/v1/site/appearance", expect.anything());
    const bad = vi.fn(async () => new Response(JSON.stringify({ design: "<script>" })));
    expect(await fetchDesign(bad as unknown as typeof fetch)).toBe(DEFAULT_DESIGN);
    const down = vi.fn(async () => {
      throw new Error("bağlantı yok");
    });
    expect(await fetchDesign(down as unknown as typeof fetch)).toBe(DEFAULT_DESIGN);
    const error = vi.fn(async () => new Response("", { status: 500 }));
    expect(await fetchDesign(error as unknown as typeof fetch)).toBe(DEFAULT_DESIGN);
  });
});
