// Paketler (API'den, fiyat girilmeden "yakında"), satın alma sayfası (oturumsuz) ve iletişim formu.
import { expect, test } from "@playwright/test";

import { sql } from "./db";

test.describe.configure({ mode: "serial" });

test("fiyat girilmemişse paketler yakında olarak gösterilir", async ({ page }) => {
  await page.goto("/paketler");
  await expect(page.getByRole("status")).toContainText("Fiyatlar yakında açıklanacak");
  await expect(page.getByText("Paketler henüz satışa açılmadı.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Planlanan seçenekler" })).toBeVisible();
});

test("satıştaki paketler fiyatıyla listelenir; satın alma girişe yönlendirir", async ({ page }) => {
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
    await expect(page.getByRole("heading", { name: "Sipariş özeti" })).toBeVisible();
    await expect(page.getByText("30 Gün - 2 Cihaz")).toBeVisible();
    await expect(page.getByTestId("order-total")).toHaveText("₺2.499,00");
    // Oturum yoksa ödeme formu yerine giriş istenir; girişten sonra aynı pakete dönülür.
    await expect(page.getByRole("status")).toContainText("Satın almak için giriş yapın");
    await expect(page.getByRole("main").getByRole("link", { name: "Giriş yap" })).toHaveAttribute(
      "href",
      "/giris?sonra=%2Fsatin-al%3Fpaket%3Dd30_2dev",
    );

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
