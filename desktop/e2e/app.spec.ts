import { expect, type Page, test } from "@playwright/test";
import { ENGINE_PORT, ENGINE_TOKEN } from "../playwright.config";

// e2e_backend.py içindeki sahte test ağı hesabının anahtarı (gerçek değil).
const API_KEY = "E2eTestAnahtar0123456789abcdef";
const SECRET = "E2eTestGizli0123456789abcdefXYZ";

const HASH = `#engine=http://127.0.0.1:${ENGINE_PORT}&token=${ENGINE_TOKEN}`;
const errors: string[] = [];

async function open(page: Page, nav?: string) {
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`/${HASH}`);
  await expect(page.getByTestId("top-state")).toBeVisible();
  if (nav) await page.getByTestId(`nav-${nav}`).click();
}

test.describe.configure({ mode: "serial" });

test.afterAll(() => {
  expect(errors, "arayüzde yakalanmamış hata olmamalı").toEqual([]);
});

test("genel bakış motor durumunu ve hazırlık koşullarını gösterir", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("engine-state")).toHaveText("Çalışıyor");
  await expect(page.getByTestId("trading-mode")).toHaveText("Sanal işlem");
  await expect(page.getByTestId("conditions")).toContainText("market_data.usdm_futures");
  await expect(page.getByTestId("conditions")).toContainText("risk.daily_loss");
});

test("başlarken kartı yapılacakları gösterir ve ilgili ekrana götürür", async ({ page }) => {
  await open(page);
  const card = page.getByTestId("getting-started");
  await expect(card).toBeVisible();
  await expect(card).toContainText("1 / 3 adım tamam"); // lisans (bu sürümde zorunlu değil) tamam
  await expect(page.getByTestId("gs-binance")).toContainText("demo.binance.com");
  await page.getByTestId("gs-phone").click();
  await expect(page.getByTestId("page-phone")).toBeVisible();
  await page.getByTestId("nav-dashboard").click();
  await page.getByTestId("gs-binance").click();
  await expect(page.getByTestId("page-settings")).toBeVisible();
});

test("bütün ekranlar açılır", async ({ page }) => {
  await open(page);
  for (const key of [
    "markets",
    "opportunities",
    "whales",
    "analysis",
    "trading",
    "performance",
    "risk",
    "strategies",
    "phone",
    "settings",
    "dashboard",
  ]) {
    await page.getByTestId(`nav-${key}`).click();
    await expect(page.getByTestId(`page-${key}`)).toBeVisible();
  }
});

test("piyasa ekranı canlı fiyatları listeler ve arar", async ({ page }) => {
  await open(page, "markets");
  const table = page.getByTestId("tickers");
  await expect(table).toContainText("BTCUSDT");
  await expect(table).toContainText("SOLUSDT");
  await page.getByTestId("market-search").fill("eth");
  await expect(table).toContainText("ETHUSDT");
  await expect(table).not.toContainText("BTCUSDT");
});

test("acil durdurma devreye girer; kaldırmak için onay ifadesi gerekir", async ({ page }) => {
  await open(page);
  await page.getByTestId("kill-engage").click();
  await page.getByRole("dialog").getByRole("button", { name: "Durdur" }).click();
  await expect(page.getByTestId("top-state")).toHaveText("Acil durdurma");
  await page.getByTestId("kill-release").click();
  const dialog = page.getByRole("dialog");
  const confirm = dialog.getByRole("button", { name: "Kaldır" });
  await expect(confirm).toBeDisabled();
  await dialog.getByRole("textbox").fill("SERBEST BIRAK");
  await confirm.click();
  await expect(page.getByTestId("top-state")).toHaveText("Çalışıyor");
});

test("gerçek hesap kilitli; test ağı anahtarı doğrulanmadan saklanmaz", async ({ page }) => {
  await open(page, "settings");
  await expect(page.getByTestId("mode-live")).toBeDisabled();
  const form = page.getByTestId("key-usdm_futures");
  await form.getByTestId("key-usdm_futures-api").fill(API_KEY);
  await form.getByTestId("key-usdm_futures-secret").fill("YanlisGizli0123456789abcdef");
  await form.getByTestId("key-usdm_futures-save").click();
  await expect(form.getByTestId("key-usdm_futures-result")).toContainText("reddetti");
  await expect(form.getByTestId("key-usdm_futures-result")).toContainText("demo.binance.com");
  await expect(form.getByTestId("key-usdm_futures-state")).toHaveText("Anahtar yok");

  await form.getByTestId("key-usdm_futures-api").fill(API_KEY);
  await form.getByTestId("key-usdm_futures-secret").fill(SECRET);
  await form.getByTestId("key-usdm_futures-save").click();
  await expect(form.getByTestId("key-usdm_futures-result")).toContainText("Anahtar doğrulandı");
  await expect(form.getByTestId("key-usdm_futures-state")).toContainText("Bağlı …cdef");
  await expect(form.getByTestId("key-usdm_futures-secret")).toHaveValue(""); // gizli anahtar ekranda kalmaz

  await page.getByTestId("mode-testnet").click();
  await expect(page.getByTestId("settings-mode")).toHaveText("Test ağı");
});

test("test ağında işlem: risk kapısı stopsuz işlemi reddeder, korumalı işlemi açar ve kapatır", async ({ page }) => {
  await open(page, "trading");
  await expect(page.getByTestId("exec-usdm_futures")).toContainText("Bağlı");
  const form = page.getByTestId("trade-form");
  await form.getByTestId("trade-qty").fill("2");
  await form.getByTestId("trade-ref").fill("100");
  await form.getByTestId("trade-submit").click();
  await expect(form.getByRole("alert")).toContainText("Zarar durdur zorunludur");

  await form.getByTestId("trade-stop").fill("95");
  await form.getByTestId("trade-tp1").fill("110");
  await form.getByTestId("trade-tp2").fill("120");
  await form.getByTestId("trade-submit").click();
  await expect(form.getByTestId("trade-result")).toContainText("open");
  await expect(form.getByTestId("trade-result")).toContainText("3 koruma emri");

  const positions = page.getByTestId("positions");
  await expect(positions).toContainText("BTCUSDT");
  await expect(positions).toContainText("Stop var");
  await expect(page.getByTestId("orders").locator("tbody tr")).toHaveCount(3);

  await page.getByTestId("close-BTCUSDT").click();
  await page.getByRole("dialog").getByRole("button", { name: "Piyasa fiyatından kapat" }).click();
  await expect(page.getByText("Açık pozisyon yok")).toBeVisible();
  await expect(page.getByText("Açık emir yok")).toBeVisible();
});

test("risk ekranı kararları ve gerekçeleri gösterir", async ({ page }) => {
  await open(page, "risk");
  const decisions = page.getByTestId("decisions");
  await expect(decisions).toContainText("Onaylandı");
  await expect(decisions).toContainText("Reddedildi");
  await expect(decisions).toContainText("Zarar durdur zorunludur");
  await expect(page.getByTestId("risk-events")).toContainText("gate.stop_required");
  await expect(page.getByTestId("risk-limits")).toContainText("%0.5");
});

test("bot (otomatik işlem) başlatılıp durdurulur", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("auto-state")).toHaveText("Kapalı");
  await page.getByTestId("auto-toggle").click();
  await expect(page.getByTestId("auto-state")).toHaveText("Açık");
  await page.getByTestId("auto-toggle").click();
  await expect(page.getByTestId("auto-state")).toHaveText("Kapalı");
});

test("lisans: yazım hatası yakalanır, geçerli anahtar etkinleşir, bilgisayar lisanstan çıkarılır", async ({ page }) => {
  await open(page, "settings");
  const license = page.getByTestId("license");
  await expect(license.getByTestId("license-state")).toHaveText("Etkin değil");
  const input = license.getByTestId("license-key");
  // Yazarken biçimlendirilir; son karakter (kontrol) yanlış: motor sunucuya gitmeden reddeder.
  await input.fill("ati7xk9pq82mn45zr60");
  await expect(input).toHaveValue("ATI-7XK9-PQ82-MN45-ZR60");
  await license.getByRole("button", { name: "Etkinleştir" }).click();
  await expect(license).toContainText("yazım hatası");
  // Biçimi doğru ama satılmamış anahtar: sunucu reddeder.
  await input.fill("ATI-0000-0000-0000-0000");
  await license.getByRole("button", { name: "Etkinleştir" }).click();
  await expect(license).toContainText("Lisans anahtarı geçersiz");

  await input.fill("ATI-7XK9-PQ82-MN45-ZR61");
  await license.getByRole("button", { name: "Etkinleştir" }).click();
  await expect(license.getByTestId("license-state")).toHaveText("Etkin");
  await expect(license.getByTestId("license-details")).toContainText("30 Gün - 1 Cihaz");
  await expect(license.getByTestId("license-details")).toContainText("ATI-****-****-****-ZR61");

  await license.getByTestId("license-release").click();
  await page.getByRole("dialog").getByRole("button", { name: "Lisanstan çıkar" }).click();
  await expect(license.getByTestId("license-state")).toHaveText("Etkin değil");
});

test("telefondan kontrol: varsayılan kapalı, açılınca aktarma servisine bağlanır ve QR üretir", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("top-phone")).toHaveText("Telefon kapalı");
  await page.getByTestId("phone-mini").click();
  await expect(page.getByTestId("page-phone")).toBeVisible();
  const toggle = page.getByTestId("remote-toggle");
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("relay-state")).toHaveText("Kapalı");
  await expect(page.getByTestId("pair-start")).toBeDisabled();

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("relay-state")).toHaveText("Bağlı");
  await expect(page.getByTestId("top-phone")).toHaveText("Telefon: eşleştirin");
  await page.getByTestId("pair-start").click();
  const qr = page.getByTestId("pair-qr");
  await expect(qr.getByRole("img", { name: "Eşleştirme QR kodu" })).toBeVisible();
  await expect(page.getByTestId("pair-remaining")).toContainText("tek kullanımlık");
  await expect(page.getByTestId("devices")).toHaveCount(0); // henüz eşli telefon yok (boş durum)

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("relay-state")).toHaveText("Kapalı");
  await expect(qr).toHaveCount(0);
  await expect(page.getByTestId("pair-start")).toBeDisabled();
});

test("lisans zorunluyken lisans girilmeden uygulama açılmaz; etkinleştirince açılır", async ({ page }) => {
  // Uçtan uca motor kaynaktan çalışır (lisans zorunlu değil). Kurulum paketindeki zorunlu durum,
  // motorun gerçek yanıtına "zorunlu" işareti eklenerek taklit edilir; etkinleştirme gerçektir.
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("**/v1/license", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), enforced: true } });
  });
  await page.goto(`/${HASH}`);
  const gate = page.getByTestId("license-gate");
  await expect(gate).toBeVisible();
  await expect(gate.getByRole("heading", { name: "Lisansınızı etkinleştirin" })).toBeVisible();
  await expect(page.getByTestId("nav-dashboard")).toHaveCount(0);
  await expect(page.getByTestId("license-gate-stop")).toBeEnabled(); // acil durdurma her zaman

  const input = page.getByTestId("license-gate-key");
  await input.fill("ATI-0000-0000-0000-0000");
  await page.getByTestId("license-gate-activate").click();
  await expect(gate).toContainText("Lisans anahtarı geçersiz");
  await input.fill("ati7xk9pq82mn45zr61");
  await expect(input).toHaveValue("ATI-7XK9-PQ82-MN45-ZR61");
  await page.getByTestId("license-gate-activate").click();
  await expect(gate).toHaveCount(0);
  await expect(page.getByTestId("top-state")).toBeVisible();

  // Temizlik: bilgisayar lisanstan çıkarılınca kapı yeniden açılır.
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("license-release").click();
  await page.getByRole("dialog").getByRole("button", { name: "Lisanstan çıkar" }).click();
  await expect(gate).toBeVisible();
});
