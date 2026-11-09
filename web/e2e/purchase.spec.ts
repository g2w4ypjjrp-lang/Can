// Satın alma uçtan uca (gerçek API + PostgreSQL): paket → fatura bilgileri ve yasal onaylar → ödeme
// simülatörü (imzalı bildirim, gerçek teslim hattı) → sonuç sayfası → panelde lisans ve sipariş;
// başarısız ödeme; yöneticinin siparişi görmesi ve TOTP ile iade (lisans iptal); yasal metinlerde
// satıcı bilgisi; erişilebilirlik.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { login, register, verify } from "./customer";
import { inviteAdmin, sql, uniqueEmail } from "./db";
import { TotpDevice } from "./totp";

const ADMIN_PASSWORD = "Yonetici-Parolasi-2026!";

test.describe.configure({ mode: "serial" });
test.setTimeout(180_000);

async function noAxeViolations(target: Page) {
  const result = await new AxeBuilder({ page: target }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

async function upsertSetting(key: string, value: unknown) {
  await sql(
    "INSERT INTO system_settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
    [key, JSON.stringify(value)],
  );
}

let context: BrowserContext;
let page: Page;
const email = uniqueEmail("alici");
let orderNo = "";

test.beforeAll(async ({ browser }) => {
  await upsertSetting("payment", { provider: "simulator", mode: "test", public: {}, secrets: {} });
  await upsertSetting("company", {
    legal_name: "Örnek Yazılım A.Ş.",
    address: "Örnek Mah. Deneme Cad. No: 1 Kadıköy / İstanbul",
    mersis: "0123456789012345",
    email: "destek@canarslan.net.tr",
  });
  await sql("UPDATE license_plans SET price_minor = 149900, currency = 'TRY', is_active = true WHERE code = 'd30_1dev'");
  context = await browser.newContext({ locale: "tr-TR", timezoneId: "Europe/Istanbul", baseURL: "http://127.0.0.1:3100" });
  page = await context.newPage();
});

test.afterAll(async () => {
  await context.close();
  await sql("UPDATE license_plans SET is_active = false WHERE code = 'd30_1dev'");
  await sql("DELETE FROM system_settings WHERE key IN ('payment', 'company')");
});

test("yasal metinlerde satıcı bilgisi panelden gelir", async () => {
  await page.goto("/yasal/on-bilgilendirme");
  await expect(page.getByText("Örnek Yazılım A.Ş.")).toBeVisible();
  await expect(page.getByText("0123456789012345")).toBeVisible();
  await expect(page.getByText("[KEP adresi]")).toBeVisible(); // girilmeyen alan yer tutucuyla
  await page.goto("/yasal/mesafeli-satis-sozlesmesi");
  await expect(page.getByText("Örnek Yazılım A.Ş.")).toBeVisible();
});

test("paket satın alınır: test ödemesi → lisans panelde", async () => {
  await register(page, email);
  await verify(page, email);
  await login(page, email, undefined, "/giris?sonra=/satin-al?paket=d30_1dev");
  await expect(page).toHaveURL(/\/satin-al\?paket=d30_1dev$/);

  await expect(page.getByRole("note").filter({ hasText: "Test modu" })).toBeVisible();
  await expect(page.getByLabel("Ad soyad")).toHaveValue("Deneme Kullanıcı");
  await page.getByLabel("Telefon").fill("+90 532 000 00 00");
  await page.getByLabel("Adres").fill("Örnek Mah. Deneme Sok. No: 1 Kadıköy");
  await page.getByLabel("Şehir").fill("İstanbul");
  await page.getByLabel(/Ön bilgilendirme formunu/).check();
  await page.getByLabel(/Mesafeli satış sözleşmesini/).check();
  await page.getByLabel(/elektronik ortamda teslim edileceğini/).check();
  await noAxeViolations(page);
  await page.getByRole("button", { name: "Ödemeye geç · ₺1.499,00" }).click();

  await expect(page).toHaveURL(/\/odeme\/test\?oturum=/);
  await expect(page.getByRole("note").filter({ hasText: "Test simülatörü" })).toBeVisible();
  await expect(page.getByText("₺1.499,00")).toBeVisible();
  await noAxeViolations(page);
  await page.getByRole("button", { name: "Ödemeyi onayla (başarılı)" }).click();

  await expect(page).toHaveURL(/\/odeme\/sonuc\?siparis=\d+$/);
  orderNo = new URL(page.url()).searchParams.get("siparis")!;
  await expect(page.getByTestId("order-status")).toHaveText("Tamamlandı");
  await expect(page.getByRole("status").filter({ hasText: "lisansınız hazır" })).toBeVisible();
  await expect(page.getByText(/^ATI-\*{4}-\*{4}-\*{4}-[0-9A-Z]{4}$/)).toBeVisible();
  await noAxeViolations(page);

  await page.getByRole("link", { name: "Müşteri paneline git" }).click();
  await expect(page).toHaveURL(/\/panel$/);
  await expect(page.getByRole("heading", { name: "30 Gün - 1 Cihaz" })).toBeVisible();
  await expect(page.getByTestId(`order-${orderNo}-status`)).toHaveText("Tamamlandı");

  const delivered = await sql<{ n: string }>(
    "SELECT count(*) AS n FROM email_outbox WHERE to_email = $1 AND template = 'license_delivery' AND NOT (payload::text LIKE '%ATI-%')",
    [email],
  );
  expect(delivered[0]!.n).toBe("1");
});

test("başarısız ödemede lisans verilmez", async () => {
  await page.goto("/satin-al?paket=d30_1dev");
  await page.getByLabel("Telefon").fill("+90 532 000 00 00");
  await page.getByLabel("Adres").fill("Örnek Mah. Deneme Sok. No: 1 Kadıköy");
  await page.getByLabel("Şehir").fill("İstanbul");
  for (const label of [/Ön bilgilendirme formunu/, /Mesafeli satış sözleşmesini/, /elektronik ortamda teslim edileceğini/]) {
    await page.getByLabel(label).check();
  }
  await page.getByRole("button", { name: /Ödemeye geç/ }).click();
  await expect(page).toHaveURL(/\/odeme\/test\?oturum=/);
  await page.getByRole("button", { name: "Ödemeyi reddet (başarısız)" }).click();
  await expect(page.getByTestId("order-status")).toHaveText("Ödeme başarısız");
  await expect(page.getByRole("alert").filter({ hasText: "Ödeme tamamlanamadı" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Yeniden dene" })).toBeVisible();
  const licenses = await sql<{ n: string }>(
    "SELECT count(*) AS n FROM licenses l JOIN customers c ON c.id = l.customer_id WHERE c.email = $1",
    [email],
  );
  expect(licenses[0]!.n).toBe("1");
});

test("yönetici siparişi görür, TOTP ile iade eder ve lisans iptal olur", async ({ browser }) => {
  const adminContext = await browser.newContext({ locale: "tr-TR", timezoneId: "Europe/Istanbul", baseURL: "http://127.0.0.1:3100" });
  const admin = await adminContext.newPage();
  await admin.goto(inviteAdmin("finans@example.com", "Finans Yetkilisi", "finance"));
  const device = new TotpDevice((await admin.getByTestId("totp-secret").textContent())!.trim());
  await admin.getByLabel("Parola", { exact: true }).fill(ADMIN_PASSWORD);
  await admin.getByLabel("Parola (tekrar)").fill(ADMIN_PASSWORD);
  await admin.getByLabel("Doğrulama kodu").fill(await device.next());
  await admin.getByRole("button", { name: "Hesabı etkinleştir" }).click();
  await admin.getByLabel("Kodları güvenli bir yere kaydettim").check();
  await admin.getByRole("button", { name: "Panele geç" }).click();

  await admin.getByRole("link", { name: "Siparişler" }).click();
  await admin.getByLabel("Sipariş no veya e-posta").fill(orderNo);
  await admin.getByRole("button", { name: "Süz" }).click();
  await admin.getByRole("button", { name: `Sipariş ${orderNo} ayrıntı` }).click();
  await expect(admin.getByTestId("admin-order-status")).toHaveText("Tamamlandı");
  await expect(admin.getByText(email).first()).toBeVisible();
  await noAxeViolations(admin);

  await admin.getByLabel("Neden").fill("Müşteri talebi");
  await admin.getByLabel("Doğrulama kodu (TOTP)").fill(await device.next());
  await admin.getByRole("button", { name: "İadeyi başlat" }).click();
  await expect(admin.getByRole("status").filter({ hasText: "İade yapıldı" })).toBeVisible();
  await expect(admin.getByTestId("admin-order-status")).toHaveText("İade edildi");
  await expect(admin.getByTestId("admin-order-license")).toContainText("İptal edildi");
  await adminContext.close();

  await page.goto("/panel");
  await expect(page.getByTestId(`order-${orderNo}-status`)).toHaveText("İade edildi");
  await expect(page.getByRole("article").filter({ hasText: "30 Gün - 1 Cihaz" })).toContainText("İptal edildi");
});
