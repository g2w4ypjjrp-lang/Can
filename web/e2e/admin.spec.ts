// Yönetim paneli uçtan uca: davet (TOTP kurulumu, kurtarma kodları), paket fiyatı → sitede görünür,
// lisans üretme/dondurma/tam anahtar (TOTP), mesajlar, denetim zinciri, yönetici daveti, ödeme
// ayarları (canlı mod kapalı), sürüm yayınlama → İndir sayfası, çıkış/giriş (parola + TOTP),
// sınırlı rolün yetkisi, erişilebilirlik.
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

test("genel kampanya: yüzde indirim sitede üstü çizili fiyatla görünür, kapatılınca kalkar", async () => {
  await page.goto("/yonetim/paketler");
  const form = page.getByTestId("campaign-form");
  await expect(page.getByTestId("campaign-state")).toHaveText("Kapalı");
  await form.getByLabel("Kampanya açık (bütün ücretli paketlere uygulanır)").check();
  await form.getByLabel("İndirim (%)").fill("20");
  await form.getByLabel("Kampanya adı (sitede görünür, isteğe bağlı)").fill("Kasım indirimi");
  await expect(form).toContainText("1.000 ₺ olan paket 800 ₺ olur");
  await noAxeViolations(page);
  await form.getByRole("button", { name: "Kampanyayı kaydet" }).click();
  await expect(page.getByTestId("campaign-state")).toHaveText("Yayında · %20");

  await page.goto("/paketler");
  await expect(page.getByTestId("campaign-banner")).toContainText("Kasım indirimi: bütün paketlerde %20 indirim");
  await expect(page.getByTestId("price-d30_1dev-list")).toContainText("₺1.499,90");
  await expect(page.getByTestId("price-d30_1dev")).toContainText("₺1.199,92");
  await expect(page.getByTestId("price-d30_1dev")).toContainText("%20 indirim");
  await noAxeViolations(page);
  await page.goto("/satin-al?paket=d30_1dev");
  await expect(page.getByTestId("order-total")).toContainText("₺1.199,92");

  await page.goto("/yonetim/paketler");
  await page.getByTestId("campaign-form").getByLabel("Kampanya açık (bütün ücretli paketlere uygulanır)").uncheck();
  await page.getByTestId("campaign-form").getByRole("button", { name: "Kampanyayı kaydet" }).click();
  await expect(page.getByTestId("campaign-state")).toHaveText("Kapalı");
  await page.goto("/paketler");
  await expect(page.getByTestId("campaign-banner")).toHaveCount(0);
  await expect(page.getByTestId("price-d30_1dev-list")).toHaveCount(0);
});

test("indirim kuponu oluşturulur, listelenir ve kapatılır", async () => {
  await page.goto("/yonetim");
  await page.getByRole("link", { name: "İndirim kuponları" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "İndirim kuponları" })).toBeVisible();
  await page.getByLabel("Kod", { exact: true }).fill("panel10");
  await page.getByLabel("İndirim (%)").fill("10");
  await page.getByLabel("Kullanım sınırı").fill("50");
  await page.getByLabel("Not").fill("Panel testi");
  await page.getByLabel("30 Gün - 1 Cihaz").check();
  await page.getByRole("button", { name: "Kuponu oluştur" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Kupon oluşturuldu" })).toBeVisible();
  const row = page.getByTestId("coupon-PANEL10");
  await expect(row).toContainText("%10");
  await expect(row).toContainText("d30_1dev");
  await expect(row).toContainText("0 / 50");
  await expect(page.getByTestId("coupon-state-PANEL10")).toHaveText("Geçerli");
  await noAxeViolations(page);
  await row.getByRole("button", { name: "PANEL10 kapat" }).click();
  await expect(page.getByTestId("coupon-state-PANEL10")).toHaveText("Kapalı");
  // Aynı kod ikinci kez oluşturulamaz.
  await page.getByLabel("Kod", { exact: true }).fill("PANEL10");
  await page.getByLabel("İndirim (%)").fill("5");
  await page.getByRole("button", { name: "Kuponu oluştur" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Bu kod zaten var" })).toBeVisible();
});

test("uygulama hata raporu ayıklanmış olarak görünür ve durumu değiştirilir", async () => {
  const response = await page.request.post("http://127.0.0.1:8100/v1/crash-reports", {
    data: {
      app: "engine", version: "0.4.0", os: "Windows 11", component: "ati_engine.market",
      error_type: "TimeoutError", message: "zaman aşımı: kisi@example.com",
      stack: 'File "C:\\Users\\Ad Soyad\\x.py", line 3, in run', fingerprint: "ab".repeat(16),
    },
  });
  expect(response.status()).toBe(202);
  await page.goto("/yonetim");
  await page.getByRole("link", { name: "Hata raporları" }).click();
  const card = page.getByTestId("crash-abababab");
  await expect(card).toContainText("TimeoutError");
  await expect(card).toContainText("<e-posta>");
  await expect(card).not.toContainText("kisi@example.com");
  await card.getByText("Kod satırları").click();
  await expect(card.locator("pre")).toContainText("<kullanici>");
  await expect(card.locator("pre")).not.toContainText("Ad Soyad");
  await expect(page.getByTestId("crash-status-abababab")).toHaveText("Yeni");
  await noAxeViolations(page);
  await card.getByLabel("TimeoutError durumu").selectOption("fixed");
  await expect(page.getByTestId("crash-status-abababab")).toHaveText("Düzeltildi");
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
  await page.getByLabel("Doğrulama kodu (TOTP)", { exact: true }).fill(await root.next());
  await page.getByRole("button", { name: "Tam anahtarı göster" }).click();
  await expect(page.getByTestId("license-key")).toHaveText(key);
  await noAxeViolations(page);
});

test("satış havuzundaki lisans müşteriye atanır", async () => {
  await sql("INSERT INTO customers (email, password_hash, email_verified_at) VALUES ('havuz@example.com', $1, now())", [ARGON2]);
  await page.goto("/yonetim/lisanslar");
  await page.getByLabel("Müşteri e-postası (boşsa satış havuzuna)").fill("");
  await page.getByRole("button", { name: "Üret", exact: true }).click();
  const key = (await page.getByTestId("issued-key").textContent())!.trim();
  await page.getByLabel("Lisans ara").fill(key);
  await page.getByRole("button", { name: "Ara" }).click();
  await expect(page.getByTestId("license-total")).toHaveText("1 lisans");
  await page.getByRole("button", { name: /ayrıntı$/ }).first().click();
  await expect(page.getByTestId("license-status")).toHaveText("Hazırlanıyor");
  await expect(page.getByTestId("license-pool-note")).toBeVisible();
  await page.getByLabel("Atanacak müşterinin e-postası").fill("havuz@example.com");
  await page.getByRole("button", { name: "Müşteriye ata" }).click();
  await expect(page.getByTestId("license-status")).toHaveText("Etkinleştirilmeyi bekliyor");
  await expect(page.getByTestId("license-pool-note")).toHaveCount(0);
  await noAxeViolations(page);
});

test("lisans TOTP ve onayla silinir; listeden kalkar", async () => {
  await sql("INSERT INTO customers (email, password_hash, email_verified_at) VALUES ('silinecek-lisans@example.com', $1, now())", [ARGON2]);
  await page.goto("/yonetim/lisanslar");
  await page.getByLabel("Müşteri e-postası (boşsa satış havuzuna)").fill("silinecek-lisans@example.com");
  await page.getByRole("button", { name: "Üret", exact: true }).click();
  const key = (await page.getByTestId("issued-key").textContent())!.trim();
  await page.getByLabel("Lisans ara").fill(key);
  await page.getByRole("button", { name: "Ara" }).click();
  await expect(page.getByTestId("license-total")).toHaveText("1 lisans");
  await page.getByRole("button", { name: /ayrıntı$/ }).first().click();
  const zone = page.getByTestId("license-delete");
  await zone.getByText("Lisansı sil").click();
  await zone.getByLabel("Lisans silme nedeni").fill("hatalı üretim");
  await zone.getByLabel("Silme için doğrulama kodu (TOTP)").fill(await root.next());
  await noAxeViolations(page);
  await zone.getByRole("button", { name: "Kalıcı olarak sil" }).click();
  await expect(zone.getByRole("button", { name: "Kalıcı olarak sil" })).toBeVisible(); // onay kutusu işaretlenmeden gönderilmez
  await zone.getByLabel(/silinsin$/).check();
  await zone.getByRole("button", { name: "Kalıcı olarak sil" }).click();
  await expect(page.getByRole("status").filter({ hasText: /Lisans #\d+ silindi/ })).toBeVisible();
  await expect(page.getByTestId("license-delete")).toHaveCount(0);
  await page.getByRole("button", { name: "Ara" }).click();
  await expect(page.getByTestId("license-total")).toHaveText("0 lisans");
  const rows = await sql<{ status: string; deleted: boolean }>(
    "SELECT l.status::text AS status, l.deleted_at IS NOT NULL AS deleted FROM licenses l JOIN customers c ON c.id = l.customer_id WHERE c.email = 'silinecek-lisans@example.com'",
  );
  expect(rows).toEqual([{ status: "cancelled", deleted: true }]);
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

test("müşteri e-posta yazılarak ve TOTP ile silinir; kişisel veri kalmaz", async () => {
  await sql("INSERT INTO customers (email, password_hash, full_name) VALUES ($1, $2, $3)", [
    "silinecek@example.com",
    ARGON2,
    "Silinecek Kişi",
  ]);
  await page.goto("/yonetim/musteriler");
  await page.getByLabel("Müşteri ara").fill("silinecek");
  await page.getByRole("button", { name: "Ara", exact: true }).click();
  await page.getByRole("button", { name: "silinecek@example.com ayrıntı" }).click();
  const remove = page.getByRole("button", { name: "Müşteriyi kalıcı olarak sil" });
  await expect(remove).toBeDisabled();
  await page.getByLabel(/Onaylamak için e-postayı yazın/).fill("silinecek@example.com");
  await page.getByLabel("Silme nedeni").fill("KVKK silme talebi");
  await page.getByLabel("Doğrulama kodu (TOTP)").fill(await root.next());
  await noAxeViolations(page);
  await remove.click();
  await expect(page.getByTestId("customer-deleted")).toBeVisible();
  await expect(page.getByRole("button", { name: "silinecek@example.com ayrıntı" })).toHaveCount(0);
  const rows = await sql<{ status: string; email: string; full_name: string | null }>(
    "SELECT status::text AS status, email::text AS email, full_name FROM customers WHERE email LIKE 'silindi-%'",
  );
  expect(rows).toHaveLength(1);
  expect(rows[0]!.status).toBe("deleted");
  expect(rows[0]!.full_name).toBeNull();
});

test("site tasarımı panelden seçilir; her tasarım açık ve koyu temada erişilebilir", async () => {
  for (const code of ["zumrut", "gunbatimi", "altin", "grafit", "okyanus"]) {
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/yonetim/ayarlar");
    await page.getByTestId(`design-${code}`).check();
    await page.getByTestId("design-save").click();
    await expect(page.getByRole("status").filter({ hasText: "Kaydedildi" })).toBeVisible();
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-design", code);
    await page.waitForLoadState("networkidle");
    await noAxeViolations(page);
    await page.emulateMedia({ colorScheme: "dark" });
    await page.reload();
    await page.waitForLoadState("networkidle");
    await noAxeViolations(page);
  }
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/yonetim/ayarlar");
  await noAxeViolations(page);
});

test("sürüm eklenir, TOTP ile yayınlanır ve İndir sayfasında görünür", async () => {
  const sha = "3f".repeat(32);
  await page.goto("/indir");
  await expect(page.getByText("İndirme yakında açılacak")).toBeVisible();

  await page.goto("/yonetim");
  await page.getByRole("navigation", { name: "Yönetim menüsü" }).getByRole("link", { name: "Sürümler (indirme)" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Sürümler (indirme)" })).toBeVisible();
  // İzinsiz alan adındaki dosya reddedilir (sunucu denetimi).
  await page.getByLabel("Sürüm numarası").fill("1.0.0");
  await page.getByLabel(/^İndirme adresi/).fill("https://kotu.example/kurulum-setup.exe");
  await page.getByLabel(/^SHA-256 özeti/).fill(sha);
  await page.getByLabel("Boyut (bayt)").fill("95000000");
  await page.getByRole("button", { name: "Taslak ekle" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "yalnızca şu alan adlarından" })).toBeVisible();
  await page.getByLabel(/^İndirme adresi/).fill("https://indir.canarslan.net.tr/AI-Trading-Intelligence_1.0.0_x64-setup.exe");
  await page.getByLabel("Sürüm notları (sitede gösterilir)").fill("İlk genel sürüm.");
  await page.getByRole("button", { name: "Taslak ekle" }).click();
  const row = page.getByTestId("release-windows-1.0.0");
  await expect(row.getByTestId("release-status")).toHaveText("Taslak");
  await noAxeViolations(page);

  // Taslak sitede görünmez; yayınlandıktan sonra görünür.
  await page.goto("/indir");
  await expect(page.getByText("İndirme yakında açılacak")).toBeVisible();
  await page.goto("/yonetim/surumler");
  await row.getByLabel("Doğrulama kodu (TOTP)").fill(await root.next());
  await row.getByRole("button", { name: "Windows 1.0.0 yayınla" }).click();
  await expect(row.getByTestId("release-status")).toHaveText("Yayında");

  await page.goto("/indir");
  await expect(page.getByTestId("windows-version")).toContainText("Sürüm 1.0.0");
  await expect(page.getByTestId("windows-sha256")).toHaveText(sha);
  const download = page.getByRole("link", { name: "Windows için indir" });
  await expect(download).toHaveAttribute("href", "https://indir.canarslan.net.tr/AI-Trading-Intelligence_1.0.0_x64-setup.exe");
  await expect(page.getByText("Bu sürüm henüz kod imzalı değil")).toBeVisible();
  await expect(page.getByText("İlk genel sürüm.")).toBeVisible();
  await noAxeViolations(page);

  // Geri çekilince sayfadan kalkar.
  await page.goto("/yonetim/surumler");
  await row.getByLabel("Geri çekme nedeni").fill("Test sürümü");
  await row.getByRole("button", { name: "Windows 1.0.0 geri çek" }).click();
  await expect(row.getByTestId("release-status")).toHaveText("Geri çekildi");
  await page.goto("/indir");
  await expect(page.getByText("İndirme yakında açılacak")).toBeVisible();
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
