// Paketler (API'den, fiyat girilmeden "yakında"), satın alma (ödeme kapalı) ve iletişim formu.
import { expect, test } from "@playwright/test";

import { sql } from "./db";

test.describe.configure({ mode: "serial" });

test("fiyat girilmemişse paketler yakında olarak gösterilir", async ({ page }) => {
  await page.goto("/paketler");
  await expect(page.getByRole("status")).toContainText("Fiyatlar yakında açıklanacak");
  await expect(page.getByText("Paketler henüz satışa açılmadı.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Planlanan seçenekler" })).toBeVisible();
});

test("satıştaki paketler fiyatıyla listelenir, ödeme kapalıdır", async ({ page }) => {
  await sql("UPDATE license_plans SET price_minor = $1, currency = 'TRY', is_active = true WHERE code = $2", [149900, "d30_1dev"]);
  await sql("UPDATE license_plans SET price_minor = $1, currency = 'TRY', is_active = true WHERE code = $2", [249900, "d30_2dev"]);
  try {
    await page.goto("/paketler");
    const card = page.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "30 gün" }) });
    await expect(card).toContainText("1 bilgisayar");
    await expect(card).toContainText("₺1.499,00");
    await expect(card).toContainText("₺2.499,00");
    await card.getByRole("link", { name: "30 Gün - 2 Cihaz paketini seç" }).click();
    await expect(page).toHaveURL(/\/satin-al\?paket=d30_2dev$/);
    await expect(page.getByRole("heading", { name: "30 Gün - 2 Cihaz" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Ödemeye geç" })).toBeDisabled();
    await expect(page.getByRole("status")).toContainText("Çevrim içi ödeme henüz açılmadı");

    await page.goto("/satin-al?paket=yok_boyle");
    await expect(page.getByRole("status")).toContainText("Paket bulunamadı");
  } finally {
    await sql("UPDATE license_plans SET is_active = false WHERE code IN ('d30_1dev', 'd30_2dev')");
  }
});

test("iletişim formu mesajı kaydeder", async ({ page }) => {
  await page.goto("/iletisim");
  await page.getByLabel("Adınız").fill("Ayşe Yılmaz");
  await page.getByLabel("E-posta", { exact: true }).fill("ayse@example.com");
  await page.getByLabel("Konu").selectOption("license");
  await page.getByLabel("Mesajınız").fill("Lisansımı yeni bilgisayarıma nasıl taşırım?");
  await page.getByRole("button", { name: "Gönder" }).click();
  await expect(page.getByRole("status")).toContainText("Mesajınız alındı");
  const rows = await sql<{ name: string; topic: string }>("SELECT name, topic FROM contact_messages WHERE email = 'ayse@example.com'");
  expect(rows).toEqual([{ name: "Ayşe Yılmaz", topic: "license" }]);
});
