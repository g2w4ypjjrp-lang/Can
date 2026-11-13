import { describe, expect, it } from "vitest";

import { bodyBlocks, isCategory, paragraphs, timeAgo } from "@/lib/forum";
import { nextRank, rankFor } from "@/lib/ranks";
import { findForbiddenClaims } from "@/lib/content-policy";

describe("forum yardımcıları", () => {
  const now = Date.parse("2026-11-13T12:00:00Z");

  it("göreli zaman", () => {
    expect(timeAgo("2026-11-13T11:59:30Z", now)).toBe("az önce");
    expect(timeAgo("2026-11-13T11:45:00Z", now)).toBe("15 dk önce");
    expect(timeAgo("2026-11-13T09:00:00Z", now)).toBe("3 sa önce");
    expect(timeAgo("2026-11-11T12:00:00Z", now)).toBe("2 gün önce");
    expect(timeAgo("2026-10-01T12:00:00Z", now)).toMatch(/2026/);
    expect(timeAgo(null, now)).toBe("");
    expect(timeAgo("bozuk", now)).toBe("");
  });

  it("paragraflar boş satırla ayrılır, tek satır sonu korunur", () => {
    expect(paragraphs("a\nb\n\n\n c \n\n")).toEqual(["a\nb", "c"]);
  });

  it("kategori denetimi", () => {
    expect(isCategory("yeni-coin")).toBe(true);
    expect(isCategory("reklam")).toBe(false);
  });

  it("forum kuralları metni kazanç vaadi denetiminden geçer", () => {
    expect(
      findForbiddenClaims(
        "Kazanç vaat eden, reklam, yönlendirme bağlantısı ya da kişisel iletişim bilgisi içeren gönderiler yayımlanmaz.",
      ),
    ).toEqual([]);
  });

  it("alıntı blokları ayrılır", () => {
    expect(bodyBlocks("> Ayşe yazdı:\n> destek 170\n\nKatılıyorum.\nStop 165.")).toEqual([
      { kind: "quote", text: "Ayşe yazdı:\ndestek 170" },
      { kind: "text", text: "Katılıyorum.\nStop 165." },
    ]);
    expect(bodyBlocks("Önce metin\n> sonra alıntı")).toEqual([
      { kind: "text", text: "Önce metin" },
      { kind: "quote", text: "sonra alıntı" },
    ]);
  });

  it("rütbe eşikleri", () => {
    expect(rankFor(0, false).name).toBe("Sui");
    expect(rankFor(3, false).name).toBe("Avalanche");
    expect(rankFor(199, false).name).toBe("Ethereum");
    expect(rankFor(200, false).name).toBe("Bitcoin");
    expect(rankFor(5, true).name).toBe("Ekip");
    expect(nextRank(5, false)).toMatchObject({ rank: { name: "Toncoin" }, remaining: 2 });
    expect(nextRank(250, false)).toBeNull();
  });
});
