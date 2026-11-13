import { describe, expect, it } from "vitest";

import { isCategory, paragraphs, timeAgo } from "@/lib/forum";
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
});
