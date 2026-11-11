import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext } from "@playwright/test";

import { ENGINE_PORT, ENGINE_TOKEN } from "../playwright.phone.config";

const ENGINE = `http://127.0.0.1:${ENGINE_PORT}`;
const auth = { Authorization: `Bearer ${ENGINE_TOKEN}` };

async function engine(request: APIRequestContext, method: "get" | "post", path: string, data?: unknown) {
  const response = await request[method](`${ENGINE}${path}`, { headers: auth, data });
  expect(response.ok(), `${path}: ${response.status()}`).toBeTruthy();
  return response.json();
}

test("telefonun kamerasıyla okunan QR: tarayıcı eşleşir, her şeyi görür, acil durdurabilir", async ({ page, request }) => {
  await engine(request, "post", "/v1/remote/enabled", { enabled: true });
  await expect.poll(async () => (await engine(request, "get", "/v1/remote/status")).connected, { timeout: 20_000 }).toBe(true);
  const { qr } = await engine(request, "post", "/v1/remote/pairing");
  // QR, telefon sayfasının adresidir; eşleştirme bilgisi # sonrasındadır.
  expect(qr).toMatch(/^https:\/\/canarslan\.net\.tr\/telefon#p=[A-Za-z0-9_-]+$/);
  const fragment = qr.slice(qr.indexOf("#"));

  await page.goto(`/telefon${fragment}`);
  await expect(page.getByTestId("phone-app")).toBeVisible();
  await expect(page.getByTestId("phone-phase")).toContainText("Bağlı", { timeout: 20_000 });
  // Gizli eşleştirme değeri adres çubuğundan silinir.
  expect(new URL(page.url()).hash).toBe("");
  await expect(page.getByTestId("phone-engine-state")).not.toHaveText("Bekleniyor");
  await expect(page.getByTestId("phone-mode")).toHaveText(/Sanal|Demo para|GERÇEK PARA/);
  await expect(page.getByTestId("phone-bot-state")).toHaveText(/Çalışıyor|Durdu/);
  for (const id of ["phone-positions", "phone-opportunities", "phone-events", "phone-bot"]) {
    await expect(page.getByTestId(id)).toBeVisible();
  }

  // Motor bu cihazı "browser" korumasıyla kaydetti.
  const status = await engine(request, "get", "/v1/remote/status");
  expect(status.devices.some((d: { protection: string; revoked: boolean }) => d.protection === "browser" && !d.revoked)).toBe(true);

  const axe = await new AxeBuilder({ page }).analyze();
  expect(axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);

  // Acil durdurma: imzalı komut motora ulaşır.
  await page.getByTestId("phone-kill").click();
  await page.getByTestId("phone-kill-confirm").click();
  await expect(page.getByTestId("phone-toast")).toContainText("Acil durdurma devrede");
  await expect(page.getByTestId("phone-kill-on")).toBeVisible();
  const engineStatus = await engine(request, "get", "/v1/status");
  expect(engineStatus.kill_switch.engaged).toBe(true);
  await engine(request, "post", "/v1/kill-switch/release", { confirmation: "SERBEST BIRAK" });

  // Sayfa yeniden açılınca (adreste kod yok) bu tarayıcıdaki eşleşmeyle yeniden bağlanır.
  await page.goto("/telefon");
  await expect(page.getByTestId("phone-phase")).toContainText("Bağlı", { timeout: 20_000 });

  // Masaüstünden eşleştirme kaldırılınca motor bu tarayıcının komutlarını uygulamaz ve yanıt
  // vermez (bilgi sızdırmaz); telefon yanıt gelmediğini söyler.
  const device = (await engine(request, "get", "/v1/remote/status")).devices.find((d: { protection: string }) => d.protection === "browser");
  await engine(request, "post", `/v1/remote/devices/revoke?device_id=${device.id}`);
  await page.getByTestId("phone-kill").click();
  await page.getByTestId("phone-kill-confirm").click();
  await expect(page.getByTestId("phone-toast")).toContainText("yanıt gelmedi", { timeout: 15_000 });
  expect((await engine(request, "get", "/v1/status")).kill_switch.engaged).toBe(false);
});

test("adresteki kod bozuk ya da süresi dolmuşsa nedeni açıkça yazılır", async ({ page }) => {
  await page.goto("/telefon#p=bozukkod");
  await expect(page.getByTestId("phone-error")).toBeVisible();
  await expect(page.getByTestId("phone-welcome")).toContainText("QR kodu göster");
});
