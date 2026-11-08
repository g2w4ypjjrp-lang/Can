// Hesap akışları gerçek API ve veritabanıyla: kayıt → doğrulama → giriş → panel → çıkış,
// doğrulanmamış hesapla giriş ve bağlantıyı yeniden gönderme, parola sıfırlama, güvenli yönlendirme.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { grantLicense, latestLink, sql, uniqueEmail } from "./db";

const PASSWORD = "Uzun-Bir-Parola-2026";

async function register(page: Page, email: string, password = PASSWORD) {
  await page.goto("/kayit");
  await page.getByLabel("Ad soyad").fill("Deneme Kullanıcı");
  await page.getByLabel("E-posta", { exact: true }).fill(email);
  await page.getByLabel("Parola", { exact: true }).fill(password);
  await page.getByLabel(/Kullanım koşullarını/).check();
  await page.getByRole("button", { name: "Hesap oluştur" }).click();
  await expect(page.getByRole("status")).toContainText("E-postanızı kontrol edin");
}

async function verify(page: Page, email: string) {
  const link = await latestLink(email, "verify_email");
  expect(link.startsWith("http://127.0.0.1:3100/eposta-dogrula?token=")).toBe(true);
  await page.goto(link.replace("http://127.0.0.1:3100", ""));
  // Belirteç adres çubuğundan silinir (geçmişte ve ekran görüntülerinde kalmaz).
  await expect(page).toHaveURL(/\/eposta-dogrula$/);
  await page.getByRole("button", { name: "E-postamı doğrula" }).click();
  await expect(page.getByRole("status")).toContainText("doğrulandı");
}

async function login(page: Page, email: string, password = PASSWORD, path = "/giris") {
  await page.goto(path);
  await page.getByLabel("E-posta", { exact: true }).fill(email);
  await page.getByLabel("Parola", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Giriş yap" }).click();
}

test("kayıt, doğrulama, giriş, panel ve çıkış", async ({ page, context }) => {
  const email = uniqueEmail("akis");
  await register(page, email);

  // Doğrulamadan giriş yapılamaz; bağlantı yeniden istenebilir ve eskisi geçersizleşir.
  await login(page, email);
  await expect(page.getByRole("alert").filter({ hasText: "doğrulayın" })).toBeVisible();
  const first = await latestLink(email, "verify_email");
  await page.getByRole("button", { name: "Doğrulama e-postasını yeniden gönder" }).click();
  await expect(page.getByRole("status")).toContainText("yeni bir doğrulama bağlantısı");
  expect(await latestLink(email, "verify_email")).not.toBe(first);

  await verify(page, email);
  await page.getByRole("link", { name: "Giriş yap" }).last().click();
  await expect(page).toHaveURL(/\/giris$/);
  await login(page, email);
  await expect(page).toHaveURL(/\/panel$/);
  await expect(page.getByTestId("panel-email")).toHaveText(email);
  await expect(page.getByText("Henüz bir lisansınız yok.")).toBeVisible();
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(axe.violations).toEqual([]);

  // Oturum çerezi JavaScript'e kapalıdır ve SameSite=Strict'tir.
  const cookie = (await context.cookies("http://127.0.0.1:8100")).find((c) => c.name === "ati_session");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Strict");
  expect(await page.evaluate(() => document.cookie)).not.toContain("ati_session");

  await page.getByRole("button", { name: "Çıkış yap" }).click();
  await expect(page).toHaveURL(/\/giris$/);
  await page.goto("/panel");
  await expect(page).toHaveURL(/\/giris\?sonra=%2Fpanel$|\/giris\?sonra=\/panel$/);
});

test("panel lisansları ve cihaz kullanımını gösterir, tam anahtarı göstermez", async ({ page }) => {
  const email = uniqueEmail("lisans");
  await register(page, email);
  await verify(page, email);
  await grantLicense(email);
  await login(page, email);
  await expect(page).toHaveURL(/\/panel$/);
  const row = page.getByRole("row", { name: /30 Gün - 1 Cihaz/ });
  await expect(row).toContainText("ATI-****-****-****-E2E1");
  await expect(row).toContainText("Etkinleştirilmeyi bekliyor");
  await expect(row).toContainText("1 / 1");
});

test("parola sıfırlama eski parolayı ve oturumları geçersiz kılar", async ({ page }) => {
  const email = uniqueEmail("sifirla");
  await register(page, email);
  await verify(page, email);

  await page.goto("/sifremi-unuttum");
  await page.getByLabel("E-posta", { exact: true }).fill(email);
  await page.getByRole("button", { name: "Sıfırlama bağlantısı gönder" }).click();
  await expect(page.getByRole("status")).toContainText("parola sıfırlama bağlantısı gönderildi");

  const link = await latestLink(email, "password_reset");
  await page.goto(link.replace("http://127.0.0.1:3100", ""));
  await expect(page).toHaveURL(/\/sifre-sifirla$/);
  await page.getByLabel("Yeni parola", { exact: true }).fill("Yepyeni-Parola-2026");
  await page.getByLabel("Yeni parola (tekrar)").fill("Baska-Bir-Parola-2026");
  await page.getByRole("button", { name: "Parolayı değiştir" }).click();
  await expect(page.getByText("Parolalar eşleşmiyor")).toBeVisible();
  await page.getByLabel("Yeni parola (tekrar)").fill("Yepyeni-Parola-2026");
  await page.getByRole("button", { name: "Parolayı değiştir" }).click();
  await expect(page.getByRole("status")).toContainText("Parolanız değiştirildi");

  await login(page, email);
  await expect(page.getByRole("alert").filter({ hasText: "E-posta veya parola hatalı" })).toBeVisible();
  await login(page, email, "Yepyeni-Parola-2026");
  await expect(page).toHaveURL(/\/panel$/);
});

test("giriş sonrası yalnızca site içi adrese yönlendirir", async ({ page }) => {
  const email = uniqueEmail("yonlendir");
  await register(page, email);
  await verify(page, email);
  await login(page, email, PASSWORD, "/giris?sonra=//kotu-site.example/tuzak");
  await expect(page).toHaveURL(/127\.0\.0\.1:3100\/panel$/);
});

test("başka bir siteden gelen giriş isteği reddedilir", async ({ request }) => {
  const response = await request.post("http://127.0.0.1:8100/v1/auth/login", {
    headers: { Origin: "https://kotu-site.example" },
    data: { email: "biri@example.com", password: "herhangi-bir-parola" },
  });
  expect(response.status()).toBe(403);
});

test.afterAll(async () => {
  // Oturum belirteçleri veritabanında yalnızca özet olarak durur.
  const rows = await sql<{ n: string }>("SELECT count(*) AS n FROM customer_sessions WHERE length(refresh_token_hash) <> 32");
  expect(rows[0]?.n).toBe("0");
});
