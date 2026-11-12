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
  // Açılış ekranı motor yanıt verince kendiliğinden kapanır.
  await expect(page.getByTestId("splash")).toHaveCount(0, { timeout: 10_000 });
  if (nav) await go(page, nav);
}

/** Menüde gider; "Gelişmiş" grubu kapalıysa önce açılır. */
async function go(page: Page, nav: string) {
  const item = page.getByTestId(`nav-${nav}`);
  if (!(await item.isVisible())) await page.getByTestId("nav-advanced").click();
  await item.click();
}

test.describe.configure({ mode: "serial" });

test.afterAll(() => {
  expect(errors, "arayüzde yakalanmamış hata olmamalı").toEqual([]);
});

test("açılış ekranı gösterilir, motor hazır olunca kapanır", async ({ page }) => {
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`/${HASH}`);
  const splash = page.getByTestId("splash");
  await expect(splash).toBeVisible();
  await expect(splash).toContainText("İşlem motoru başlatılıyor");
  await expect(splash).toHaveCount(0, { timeout: 10_000 });
  await expect(page.getByTestId("top-state")).toBeVisible();
});

test("genel bakış motor durumunu ve hazırlık koşullarını gösterir", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("engine-state")).toHaveText("Çalışıyor");
  await expect(page.getByTestId("trading-mode")).toHaveText("Sanal işlem");
  await expect(page.getByTestId("conditions")).toContainText("Futures piyasa verisi");
  await expect(page.getByTestId("conditions")).toContainText("Günlük zarar sınırı");
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
    "lab",
    "phone",
    "settings",
    "dashboard",
  ]) {
    await go(page, key);
    await expect(page.getByTestId(`page-${key}`)).toBeVisible();
  }
});

test("piyasa ekranı canlı fiyatları listeler ve arar", async ({ page }) => {
  await open(page, "markets");
  const table = page.getByTestId("tickers");
  await expect(table).toContainText("BTCUSDT");
  await expect(table).toContainText("SOLUSDT");
  // Anlık fiyat: Binance işlem akışındaki her yeni fiyat motor → olay akışı → hücre yolunu
  // beklemeden izler (sayfa yenilenmeden).
  await expect(table.locator('[data-live="1"]').first()).toBeVisible({ timeout: 15_000 });
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

test("gerçek para onay ifadesi ve gerçek hesap anahtarı olmadan açılmaz; demo anahtarı doğrulanmadan saklanmaz", async ({ page }) => {
  await open(page, "settings");
  await page.getByTestId("mode-live").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("gerçek parayla");
  const confirmLive = dialog.getByRole("button", { name: "Gerçek parayı aç" });
  await expect(confirmLive).toBeDisabled(); // ifade yazılmadan onaylanamaz
  await dialog.getByLabel(/Onaylamak için yazın/).fill("GERCEK PARA ILE ISLEM YAPILMASINI ONAYLIYORUM");
  await confirmLive.click();
  await expect(page.getByTestId("mode-checks")).toContainText("para çekme yetkisi KAPALI");
  await expect(page.getByTestId("mode-live")).toHaveAttribute("aria-checked", "false");
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
  await expect(page.getByTestId("mode-testnet")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("top-mode")).toHaveText("Demo Trading");
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

  // Açık pozisyonun anlık kâr/zararı (güncel fiyatla) görünür.
  await expect(page.getByTestId("pnl-BTCUSDT")).toContainText("USDT", { timeout: 10_000 });
  await page.getByTestId("close-BTCUSDT").click();
  await page.getByRole("dialog").getByRole("button", { name: "Piyasa fiyatından kapat" }).click();
  // Kapanan işlem geçmişte net kâr/zararıyla görünür.
  const history = page.getByTestId("history");
  await expect(history.getByTestId("history-rows")).toContainText("BTCUSDT", { timeout: 15_000 });
  await expect(history.getByTestId("history-summary")).toContainText("Toplam net");
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

test("ana sayfada Binance bakiyesi görünür (piyasa başına cüzdan)", async ({ page }) => {
  await open(page);
  const hero = page.getByTestId("balance-hero");
  await expect(hero.getByTestId("balance-total")).toContainText("USDT");
  await expect(hero.getByTestId("balance-wallets")).toContainText("Futures cüzdanı");
  await expect(hero.getByTestId("balance-wallets")).toContainText("kullanılabilir");
});

test("bot paneli: başlat/durdur, hazırlık listesi ve sonraki karar", async ({ page }) => {
  await open(page);
  const panel = page.getByTestId("bot-panel");
  await expect(panel.getByTestId("auto-state")).toHaveText("Durdu");
  await expect(panel.getByTestId("bot-env")).toHaveText(/^(Sanal|Demo para)$/);
  await expect(panel.getByTestId("bot-next")).toContainText("Sonraki karar");
  // Ya her şey hazır ya da eksikler "Düzelt" bağlantısıyla listelenir.
  await expect(panel.getByTestId("bot-ready").or(panel.getByTestId("bot-checks"))).toBeVisible();
  await panel.getByTestId("auto-toggle").click();
  await expect(panel.getByTestId("auto-state")).toHaveText("Çalışıyor");
  await expect(panel.getByTestId("bot-message")).toContainText("Bot başladı");
  await panel.getByTestId("auto-toggle").click();
  await expect(panel.getByTestId("auto-state")).toHaveText("Durdu");
  await expect(panel.getByTestId("bot-message")).toContainText("durduruldu");

  // Karar aralığı: kaydedilir, motor yeniden başlayınca geçerli olur (tarayıcıda yeniden başlatma yok).
  await panel.getByTestId("interval-1m").click();
  await page.getByRole("dialog").getByRole("button", { name: "Kaydet ve motoru yeniden başlat" }).click();
  await expect(panel.getByTestId("bot-message")).toContainText("Uygulamayı kapatıp açınca");
  await expect(panel.getByTestId("interval-1m")).toHaveAttribute("aria-checked", "true");
  await expect(panel.getByText("Yeniden başlatınca geçerli")).toBeVisible();
  await panel.getByTestId("interval-1h").click();
  await page.getByRole("dialog").getByRole("button", { name: "Kaydet ve motoru yeniden başlat" }).click();
  await expect(panel.getByText("Yeniden başlatınca geçerli")).toHaveCount(0);
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

test("backtest ve eğitim ekranı: üç bölüm açılır, geçmiş veri kapalıysa açıklama gösterir", async ({ page }) => {
  await open(page, "lab");
  await expect(page.getByTestId("page-lab")).toBeVisible();
  for (const id of ["lab-history", "lab-backtest", "lab-train"]) await expect(page.getByTestId(id)).toBeVisible();
  // Uçtan uca motorda geçmiş veri servisi kapalı: çökmeden açıklama gösterilir.
  await expect(page.getByTestId("lab-history")).toContainText("Geçmiş veri");
  await expect(page.getByTestId("lab-backtest")).toContainText("etkin değil");
  await page.getByTestId("lab-bt-symbols").fill("");
  await expect(page.getByTestId("lab-bt-start")).toBeDisabled();
});

test("telegram bildirimi: biçim denetimi, kayıtlı anahtar ipucu, kapalı başlar", async ({ page }) => {
  await open(page, "settings");
  const card = page.getByTestId("telegram");
  await expect(card.getByTestId("telegram-state")).toHaveText("Kapalı");
  await expect(card.getByTestId("telegram-test")).toBeDisabled();
  await card.getByTestId("telegram-token").fill("yanlis");
  await card.getByTestId("telegram-chat").fill("987654321");
  await card.getByTestId("telegram-save").click();
  await expect(card).toContainText("Bot anahtarı biçimi geçersiz");
  await card.getByTestId("telegram-discover").click();
  await expect(card).toContainText("geçerli bir bot anahtarı");
});

test("hata raporları varsayılan kapalı; ne gönderildiği açıklanır, açılıp kapatılır", async ({ page }) => {
  await open(page, "settings");
  const card = page.getByTestId("crash-reports");
  await expect(card.getByTestId("crash-state")).toHaveText("Kapalı");
  await expect(card).toContainText("Gönderilmeyen");
  await expect(card).toContainText("lisans anahtarınız");
  await card.getByTestId("crash-toggle").click();
  await expect(card.getByTestId("crash-state")).toHaveText("Açık");
  await expect(card.getByTestId("crash-sent")).toContainText("Bu oturumda gönderilen: 0");
  await card.getByTestId("crash-toggle").click();
  await expect(card.getByTestId("crash-state")).toHaveText("Kapalı");
});

test("bot ayarları: risk sınırı aşılamaz, kaydedilir ve varsayılana döner", async ({ page }) => {
  await open(page, "trading");
  const card = page.getByTestId("bot-settings");
  await expect(card.getByTestId("bot-min-score")).toHaveValue("70");
  await card.getByTestId("bot-risk").fill("0,9");
  await card.getByTestId("bot-save").click();
  await expect(card).toContainText("risk sınırını");
  await card.getByTestId("bot-risk").fill("0,4");
  await card.getByTestId("bot-min-score").fill("85");
  await card.getByTestId("bot-market-spot").check();
  await expect(card.getByTestId("bot-trailing")).toBeChecked(); // varsayılan: iz süren stop açık
  await card.getByTestId("bot-trailing").uncheck();
  await card.getByTestId("bot-losses").fill("2");
  await card.getByTestId("bot-pause").fill("120");
  // Kalite filtreleri: varsayılan kazanç/risk 1,5; hacim filtresi kapalı.
  await expect(card.getByTestId("bot-rr")).toHaveValue("1.5");
  await expect(card.getByTestId("bot-volume")).toHaveValue("0");
  await card.getByTestId("bot-rr").fill("2");
  await card.getByTestId("bot-volume").fill("50");
  await card.getByTestId("bot-save").click();
  await expect(card.getByTestId("bot-message")).toContainText("Kaydedildi");
  await page.reload();
  const saved = page.getByTestId("bot-settings");
  await expect(saved.getByTestId("bot-min-score")).toHaveValue("85");
  await expect(saved.getByTestId("bot-market-spot")).toBeChecked();
  await expect(saved.getByTestId("bot-trailing")).not.toBeChecked();
  await expect(saved.getByTestId("bot-losses")).toHaveValue("2");
  await expect(saved.getByTestId("bot-pause")).toHaveValue("120");
  await expect(saved.getByTestId("bot-rr")).toHaveValue("2");
  await expect(saved.getByTestId("bot-volume")).toHaveValue("50");
  await page.getByTestId("bot-settings").getByTestId("bot-reset").click();
  await expect(page.getByTestId("bot-settings").getByTestId("bot-min-score")).toHaveValue("70");
  await expect(page.getByTestId("bot-settings").getByTestId("bot-rr")).toHaveValue("1.5");
});


test("gerçek para: anahtar (para çekme kapalı) bağlanınca onayla açılır, bot ve işlem ekranı uyarır, Demo'ya dönülür", async ({ page }) => {
  await open(page, "settings");
  const form = page.getByTestId("live-key-usdm_futures");
  await expect(form).toContainText("Para çekme yetkisini KESİNLİKLE açmayın");
  await form.getByTestId("live-key-usdm_futures-api").fill(API_KEY);
  await form.getByTestId("live-key-usdm_futures-secret").fill(SECRET);
  await form.getByTestId("live-key-usdm_futures-save").click();
  await expect(form.getByTestId("live-key-usdm_futures-state")).toContainText("Bağlı …cdef");

  await page.getByTestId("mode-live").click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/Onaylamak için yazın/).fill("GERCEK PARA ILE ISLEM YAPILMASINI ONAYLIYORUM");
  await dialog.getByRole("button", { name: "Gerçek parayı aç" }).click();
  await expect(page.getByTestId("top-mode")).toHaveText("GERÇEK PARA");
  await expect(page.getByTestId("live-banner")).toBeVisible();

  await open(page, "trading");
  await expect(page.getByTestId("trading-live-notice")).toBeVisible();
  await expect(page.getByTestId("trade-form")).toContainText("GERÇEK PARA");
  const bot = page.getByTestId("bot-settings");
  await expect(bot.getByTestId("bot-mode-live")).toHaveAttribute("aria-checked", "true");
  await bot.getByTestId("bot-mode-testnet").click(); // bot kartından Demo'ya dönüş (onay gerekmez)
  await expect(page.getByTestId("top-mode")).toHaveText("Demo Trading");
  await open(page, "settings");
  await page.getByTestId("live-key-usdm_futures").getByRole("button", { name: "Anahtarı sil" }).click();
  await expect(page.getByTestId("live-key-usdm_futures-state")).toHaveText("Anahtar yok");
});
