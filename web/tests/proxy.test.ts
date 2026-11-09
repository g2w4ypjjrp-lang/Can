import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { runtimeConfig } from "@/lib/config";
import { adminRouting } from "../proxy";

function request(url: string): NextRequest {
  const parsed = new URL(url);
  return new NextRequest(url, { headers: { host: parsed.host } });
}

describe("yönetim paneli alan adı ayrımı", () => {
  const ADMIN = "admin.canarslan.net.tr";

  it("alan adı tanımlı değilse (geliştirme/test) karışmaz", () => {
    expect(adminRouting(request("http://localhost:3000/yonetim"), null)).toBeNull();
  });

  it("herkese açık sitede /yonetim 404 olur", () => {
    const response = adminRouting(request("https://canarslan.net.tr/yonetim/giris"), ADMIN);
    expect(response?.status).toBe(404);
    expect(adminRouting(request("https://canarslan.net.tr/paketler"), ADMIN)).toBeNull();
  });

  it("yönetim alanında yalnızca /yonetim açılır", () => {
    expect(adminRouting(request(`https://${ADMIN}/yonetim/lisanslar`), ADMIN)).toBeNull();
    const redirect = adminRouting(request(`https://${ADMIN}/paketler`), ADMIN);
    expect(redirect?.status).toBe(307);
    expect(redirect?.headers.get("location")).toBe(`https://${ADMIN}/yonetim`);
  });

  it("ayar ortam değişkeninden okunur", () => {
    expect(runtimeConfig({ ATI_ADMIN_HOST: " Admin.Canarslan.net.tr " }).adminHost).toBe(ADMIN);
    expect(runtimeConfig({}).adminHost).toBeNull();
  });
});
