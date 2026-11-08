import { describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest, errorMessage, NETWORK_ERROR } from "@/lib/api";
import { runtimeConfig } from "@/lib/config";
import { findForbiddenClaims } from "@/lib/content-policy";
import { buildCsp, newNonce, originOf } from "@/lib/csp";
import { durationLabel, formatDate, formatPrice, licenseStatusLabel, safeNext } from "@/lib/format";
import { groupPlans, type Plan } from "@/lib/plans";

describe("safeNext (açık yönlendirme koruması)", () => {
  it.each([
    ["/panel", "/panel"],
    ["/paketler?x=1", "/paketler?x=1"],
    [undefined, "/panel"],
    ["", "/panel"],
    ["//kotu.example", "/panel"],
    ["/\\kotu.example", "/panel"],
    ["https://kotu.example", "/panel"],
    ["javascript:alert(1)", "/panel"],
    ["/a\u0000b", "/panel"],
    [["/sss", "/x"], "/sss"],
  ])("%j → %s", (input, expected) => {
    expect(safeNext(input as string | string[] | undefined)).toBe(expected);
  });
});

describe("biçimlendirme", () => {
  it("fiyatı para biriminin alt birimine göre yazar", () => {
    expect(formatPrice(149900, "TRY")).toBe("₺1.499,00");
    expect(formatPrice(2900, "USD")).toBe("$29,00");
    expect(formatPrice(5000, "JPY")).toBe("¥5.000");
    expect(formatPrice(0, "TRY")).toBe("Ücretsiz");
    expect(formatPrice(1234, "???")).toBe("12.34 ???");
  });

  it("süre, tarih ve lisans durumu", () => {
    expect(durationLabel(30)).toBe("30 gün");
    expect(durationLabel(null)).toBe("Süresiz");
    expect(formatDate("2026-11-08T21:30:00Z")).toBe("9 Kasım 2026"); // İstanbul saati
    expect(formatDate(null)).toBe("—");
    expect(formatDate("bozuk")).toBe("—");
    expect(licenseStatusLabel("active")).toBe("Etkin");
    expect(licenseStatusLabel("bilinmeyen")).toBe("bilinmeyen");
  });
});

describe("API istemcisi", () => {
  it("FastAPI hatalarını Türkçe mesaja çevirir", () => {
    expect(errorMessage(401, { detail: "E-posta veya parola hatalı" })).toBe("E-posta veya parola hatalı");
    expect(errorMessage(422, { detail: [{ loc: ["body", "email"], msg: "x" }] })).toBe("Geçerli bir e-posta adresi girin");
    expect(errorMessage(422, { detail: [{ loc: ["body", "baska"] }] })).toBe("Girdiğiniz bilgileri kontrol edin");
    expect(errorMessage(429, null)).toContain("Çok fazla deneme");
    expect(errorMessage(503, null)).toContain("geçici");
  });

  it("çerezle ve JSON gövdeyle istek atar", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
    await expect(apiRequest("https://api.example", "/v1/auth/login", { method: "POST", body: { a: 1 }, fetcher })).resolves.toEqual({ status: "ok" });
    expect(fetcher).toHaveBeenCalledWith("https://api.example/v1/auth/login", {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: '{"a":1}',
    });
  });

  it("hata durumunu ve ağ hatasını ApiError olarak verir", async () => {
    const denied = vi.fn(async () => new Response(JSON.stringify({ detail: "Oturum açmanız gerekiyor" }), { status: 401 }));
    await expect(apiRequest("x", "/v1/me", { fetcher: denied })).rejects.toEqual(new ApiError(401, "Oturum açmanız gerekiyor"));
    const offline = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(apiRequest("x", "/v1/me", { fetcher: offline })).rejects.toMatchObject({ status: 0, message: NETWORK_ERROR });
  });
});

describe("CSP", () => {
  it("üretimde nonce dışında satır içi betiğe izin vermez", () => {
    const csp = buildCsp({ nonce: "abc", apiOrigin: "https://api.example", dev: false, https: true });
    expect(csp).toContain("script-src 'self' 'nonce-abc' 'strict-dynamic'");
    expect(csp).not.toContain("unsafe-inline");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).toContain("connect-src 'self' https://api.example");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("form-action 'self'");
    expect(csp.endsWith("upgrade-insecure-requests")).toBe(true);
  });

  it("geliştirme modunda yalnızca gereken gevşetmeler", () => {
    const csp = buildCsp({ nonce: "n", apiOrigin: "http://localhost:8000", dev: true, https: false });
    expect(csp).toContain("'unsafe-eval'");
    expect(csp).not.toContain("upgrade-insecure-requests");
  });

  it("nonce her seferinde farklı, 128 bit", () => {
    const a = newNonce();
    expect(atob(a)).toHaveLength(16);
    expect(newNonce()).not.toBe(a);
    expect(originOf("https://api.example/v1/x")).toBe("https://api.example");
    expect(originOf("bozuk")).toBe("'self'");
  });
});

describe("içerik kuralı: kazanç vaadi yok", () => {
  it.each([
    "Garantili kazanç sağlayan bot",
    "Bu sistemle kesin kâr elde edin",
    "Risksiz getiri",
    "kazanç garantisi veriyoruz",
    "Asla kaybetmezsiniz",
    "Pasif gelir kapısı",
  ])("yakalar: %s", (text) => {
    expect(findForbiddenClaims(text)).not.toEqual([]);
  });

  it.each([
    "AI Trading Intelligence yatırım tavsiyesi vermez ve kazanç garantisi sunmaz.",
    "Kazanç garantisi yoktur.",
    "Korumalar kaybı sınırlamaya yardımcı olur, ancak kayıp olmayacağını garanti etmez.",
  ])("izin verir: %s", (text) => {
    expect(findForbiddenClaims(text)).toEqual([]);
  });
});

describe("paket gruplama", () => {
  const plan = (code: string, days: number | null, devices: number, trial = false): Plan => ({
    code,
    name: code,
    duration_days: days,
    device_limit: devices,
    companion_device_limit: 1,
    is_trial: trial,
    price_minor: 1000,
    currency: "TRY",
    features: {},
  });

  it("süreye göre sıralar, süresiz sonda, deneme ayrı", () => {
    const { trial, groups } = groupPlans([
      plan("life_1", null, 1),
      plan("d90_2", 90, 2),
      plan("trial", 7, 1, true),
      plan("d30_3", 30, 3),
      plan("d30_1", 30, 1),
    ]);
    expect(trial?.code).toBe("trial");
    expect(groups.map((g) => g.key)).toEqual(["30", "90", "lifetime"]);
    expect(groups[0]!.options.map((p) => p.code)).toEqual(["d30_1", "d30_3"]);
  });
});

describe("çalışma anı ayarları", () => {
  it("varsayılanlar ve sondaki eğik çizgi", () => {
    const cfg = runtimeConfig({ ATI_PUBLIC_API_URL: "https://api.example/", ATI_PLANS_REVALIDATE_S: "-5" });
    expect(cfg.publicApiUrl).toBe("https://api.example");
    expect(cfg.serverApiUrl).toBe("https://api.example");
    expect(cfg.plansRevalidateS).toBe(300);
    expect(cfg.production).toBe(false);
    expect(runtimeConfig({ ATI_API_URL: "http://cloud:8000", ATI_ENVIRONMENT: "production" })).toMatchObject({
      serverApiUrl: "http://cloud:8000",
      production: true,
    });
  });
});
