// Yönetim paneli uçtan uca: davet (TOTP kurulumu, kurtarma kodları), paket fiyatı → sitede görünür,
// lisans üretme/dondurma/tam anahtar (TOTP), mesajlar, denetim zinciri, yönetici daveti, ödeme
// ayarları (canlı mod kapalı), çıkış/giriş (parola + TOTP), sınırlı rolün yetkisi, erişilebilirlik.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { inviteAdmin, sql } from "./db";
import { TotpDevice } from "./totp";

const PASSWORD = "Yonetici-Parolasi-2026!";
const ARGON2 = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA";

test.describe.configure({ mode: "serial" });
test.setTimeout(180_000);

async function noAxeViolations(target: Page) {
  const result = await new AxeBuilder({ page: target }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

async function acceptInvite(target: Page, path: string): Promise<TotpDevice> {
  await target.goto(path);
  await expect(target).toHaveURL(/\/yonetim\/davet$/); // belirteç adres çubuğundan silinir
  const secret = (await target.getByTestId("totp-secret").textContent())!.trim();
  const device = new TotpDevice(secret);
  await target.getByLabel("Parola", { exact: true }).fill(PASSWORD);
  await target.getByLabel("Parola (tekrar)").fill(PASSWORD);
  await target.getByLabel("Doğrulama kodu").fill(await device.next());
  await target.getByRole("button", { name: "Hesabı etkinleştir" }).click();
  await expect(target.getByTestId("recovery-codes").locator("li")).toHaveCount(10);
  await target.getByLabel("Kodları güvenli bir yere kaydettim").check();
  await target.getByRole("button", { name: "Panele geç" }).click();
  return device;
}

let root: TotpDevice;
let supportInvite = "";
// Testler tek bir yönetici yolculuğudur: aynı tarayıcı bağlamı ve oturum paylaşılır.
let context: BrowserContext;
let page: Page;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({ locale: "tr-TR", timezoneId: "Europe/Istanbul", baseURL: "http://127.0.0.1:3100" });
  page = await context.newPage();
});

test.afterAll(async () => {
  await context.close();
  await sql("UPDATE license_plans SET is_active = false WHERE code = 'd30_1dev'");
});

test("yönetici davetle etkinleşir, paket fiyatı sitede görünür", async () => {
  root = await acceptInvite(page, inviteAdmin("kok@example.com", "Kök Yönetici"));
  await expect(page.getByRole("heading", { level: 1, name: "Özet" })).toBeVisible();
  await expect(page.getByTestId("admin-email")).toHaveText("kok@example.com");
  await noAxeViolations(page);

  await page.getByRole("link", { name: "Paketler ve fiyatlar" }).click();
  const row = page.getByTestId("plan-d30_1dev");
  // Fiyatsız paket satışa açılamaz.
  await row.getByLabel("Satışta").check();
  await row.getByRole("button", { name: "30 Gün - 1 Cihaz kaydet" }).click();
  await expect(row.getByRole("alert").filter({ hasText: "Fiyatı girilmemiş" })).toBeVisible();
  await row.getByLabel("30 Gün - 1 Cihaz fiyatı").fill("1.499,90");
  await row.getByLabel("30 Gün - 1 Cihaz para birimi").selectOption("TRY");
  await row.getByRole("button", { name: "30 Gün - 1 Cihaz kaydet" }).click();
  await expect(page.getByTestId("plan-d30_1dev").getByRole("status")).toContainText("Kaydedildi");
  await page.goto("/paketler");
  await expect(page.getByText("₺1.499,90")).toBeVisible();
});

test("lisans üretilir, dondurulur, tam anahtar TOTP ile gösterilir", async () => {
  await sql("INSERT INTO customers (email, password_hash, email_verified_at) VALUES ('alici@example.com', $1, now())", [ARGON2]);
  await page.goto("/yonetim/lisanslar");
  await page.getByLabel("Müşteri e-postası (boşsa satış havuzuna)").fill("alici@example.com");
  await page.getByRole("button", { name: "Üret", exact: true }).click();
  const key = (await page.getByTestId("issued-key").textContent())!.trim();
  expect(key).toMatch(/^ATI-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$/);
  await page.getByLabel("Lisans ara").fill(key);
  await page.getByRole("button", { name: "Ara" }).click();
  await expect(page.getByTestId("license-total")).toHaveText("1 lisans");
  await page.getByRole("button", { name: /ayrıntı$/ }).first().click();
  await page.getByLabel("Dondurma nedeni").fill("ödeme incelemesi");
  await page.getByRole("button", { name: "Dondur" }).click();
  await expect(page.getByTestId("license-status")).toHaveText("Donduruldu");
  await page.getByLabel("Doğrulama kodu (TOTP)").fill(await root.next());
  await page.getByRole("button", { name: "Tam anahtarı göster" }).click();
  await expect(page.getByTestId("license-key")).toHaveText(key);
  await noAxeViolations(page);
});

test("mesajlar, denetim zinciri ve yönetici daveti", async () => {
  await sql("INSERT INTO contact_messages (name, email, topic, message) VALUES ('Ayşe', 'ayse.yonetim@example.com', 'license', 'Lisansımı taşımak istiyorum, yardım eder misiniz?')");
  await page.goto("/yonetim/mesajlar");
  await expect(page.getByText("Lisansımı taşımak istiyorum")).toBeVisible();
  await page.getByLabel("Ayşe mesajının durumu").selectOption("closed");
  await expect(page.getByRole("status").filter({ hasText: "Durum güncellendi" })).toBeVisible();

  await page.goto("/yonetim/denetim");
  await page.getByRole("button", { name: "Zinciri doğrula" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Zincir sağlam" })).toBeVisible();

  await page.goto("/yonetim/yoneticiler");
  await page.getByLabel("E-posta").fill("destek@example.com");
  await page.getByLabel("Ad soyad").fill("Destek Uzmanı");
  await page.getByRole("button", { name: "Davet oluştur" }).click();
  const link = (await page.getByTestId("invite-link").textContent())!.trim();
  supportInvite = new URL(link).pathname + new URL(link).search;
  expect(supportInvite).toContain("/yonetim/davet?token=");
});

test("ödeme ayarları: canlı mod kapalı, şirket bilgileri kaydedilir", async () => {
  await page.goto("/yonetim/ayarlar");
  await expect(page.getByRole("note")).toContainText("Canlı ödeme kapalı");
  await expect(page.locator("option[value=live]")).toHaveJSProperty("disabled", true);
  await page.getByLabel("Sağlayıcı").selectOption("paytr");
  await page.getByLabel("merchant_id").fill("123456");
  await expect(page.getByText("merchant_key (tanımlı değil)")).toBeVisible();
  await page.getByRole("button", { name: "Kaydet" }).first().click();
  await expect(page.getByRole("status").filter({ hasText: "Ödeme ayarları kaydedildi" })).toBeVisible();
  await page.getByLabel("Ticaret unvanı").fill("Örnek Yazılım A.Ş.");
  await page.getByLabel("Vergi kimlik no (10-11 hane)").fill("1234567890");
  await page.getByRole("button", { name: "Kaydet" }).nth(1).click();
  await expect(page.getByRole("status").filter({ hasText: "Şirket bilgileri kaydedildi" })).toBeVisible();
  await noAxeViolations(page);
});

test("çıkış ve parola + TOTP ile yeniden giriş", async () => {
  await page.goto("/yonetim");
  await page.getByRole("button", { name: "Çıkış yap" }).click();
  await expect(page).toHaveURL(/\/yonetim\/giris$/);
  await page.goto("/yonetim/lisanslar");
  await expect(page).toHaveURL(/\/yonetim\/giris\?sonra=/);
  await page.getByLabel("E-posta").fill("kok@example.com");
  await page.getByLabel("Parola").fill("yanlis-parola-xyz");
  await page.getByRole("button", { name: "Devam" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Giriş başarısız" })).toBeVisible();
  await page.getByLabel("Parola").fill(PASSWORD);
  await page.getByRole("button", { name: "Devam" }).click();
  await page.getByLabel("Doğrulama kodu").fill(await root.next());
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page).toHaveURL(/\/yonetim\/lisanslar$/);
  await noAxeViolations(page);
});

test("destek rolü paket yönetimini göremez ve sunucu reddeder", async ({ browser }) => {
  const other = await browser.newContext({ baseURL: "http://127.0.0.1:3100" });
  const support = await other.newPage();
  await acceptInvite(support, supportInvite);
  const nav = support.getByRole("navigation", { name: "Yönetim menüsü" });
  await expect(nav.getByRole("link", { name: "Lisanslar" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Paketler ve fiyatlar" })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Yöneticiler" })).toHaveCount(0);
  await support.goto("/yonetim/paketler");
  await expect(support.getByRole("alert").filter({ hasText: "Bu işlem için yetkiniz yok" })).toBeVisible();
  await other.close();
});
