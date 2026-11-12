import { createDecipheriv, createECDH, createHmac, randomBytes, type ECDH } from "node:crypto";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

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
  for (const id of ["phone-positions", "phone-history", "phone-opportunities", "phone-events", "phone-bot"]) {
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

// --- Kilit ekranı bildirimleri (Web Push) ------------------------------------------------------
// Gerçek bildirim servisi (Apple/Google) testte kullanılamaz: tarayıcının abonelik API'si sahte
// bir bildirim servisine (yerel HTTP sunucusu) işaret eden aboneliği döndürür. Motor bildirimi bu
// aboneliğin anahtarına şifreler; test, telefonun gizli anahtarıyla çözüp içeriği doğrular.

function decryptPush(body: Buffer, ecdh: ECDH, auth: Buffer): { title: string; body: string; kind: string } {
  const salt = body.subarray(0, 16);
  const idlen = body[20]!;
  const sender = body.subarray(21, 21 + idlen);
  const sealed = body.subarray(21 + idlen);
  const mac = (key: Buffer, data: Buffer) => createHmac("sha256", key).update(data).digest();
  const shared = ecdh.computeSecret(sender);
  const ikm = mac(mac(auth, shared), Buffer.concat([Buffer.from("WebPush: info\0"), ecdh.getPublicKey(), sender, Buffer.from([1])]));
  const prk = mac(salt, ikm);
  const cek = mac(prk, Buffer.from("Content-Encoding: aes128gcm\0\x01")).subarray(0, 16);
  const nonce = mac(prk, Buffer.from("Content-Encoding: nonce\0\x01")).subarray(0, 12);
  const decipher = createDecipheriv("aes-128-gcm", cek, nonce);
  decipher.setAuthTag(sealed.subarray(sealed.length - 16));
  const plain = Buffer.concat([decipher.update(sealed.subarray(0, sealed.length - 16)), decipher.final()]);
  return JSON.parse(plain.subarray(0, plain.length - 1).toString("utf8"));
}

test("kilit ekranı bildirimi: telefon abone olur, motor şifreli bildirimi gönderir", async ({ page, request }) => {
  const received: { headers: Record<string, string | string[] | undefined>; body: Buffer }[] = [];
  const server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => {
      received.push({ headers: req.headers, body: Buffer.concat(chunks) });
      res.statusCode = 201;
      res.end();
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as AddressInfo).port;
  const ecdh = createECDH("prime256v1");
  ecdh.generateKeys();
  const auth = randomBytes(16);
  const b64url = (b: Buffer) => b.toString("base64url");

  await page.addInitScript(
    ({ endpoint, p256dh, authKey }) => {
      const bytes = (text: string) => Uint8Array.from(atob(text.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0)).buffer;
      // Ana ekrandan açılmış uygulama gibi davran (iPhone'da bildirim yalnızca orada çalışır).
      const media = window.matchMedia.bind(window);
      window.matchMedia = (q: string) =>
        q.includes("display-mode: standalone") ? ({ matches: true, media: q, addEventListener() {}, removeEventListener() {} } as unknown as MediaQueryList) : media(q);
      let permission: NotificationPermission = "default";
      Object.defineProperty(Notification, "permission", { get: () => permission });
      Notification.requestPermission = async () => (permission = "granted");
      let subscription: unknown = null;
      const registration = {
        pushManager: {
          getSubscription: async () => subscription,
          subscribe: async (options: { applicationServerKey: Uint8Array }) => {
            subscription = {
              endpoint,
              options: { applicationServerKey: options.applicationServerKey },
              getKey: (name: string) => bytes(name === "p256dh" ? p256dh : authKey),
              unsubscribe: async () => {
                subscription = null;
                return true;
              },
            };
            return subscription;
          },
        },
      };
      let registered = false;
      Object.defineProperty(navigator, "serviceWorker", {
        value: {
          register: async () => {
            registered = true;
            return registration;
          },
          getRegistration: async () => (registered ? registration : undefined),
          ready: Promise.resolve(registration),
        },
      });
    },
    { endpoint: `http://127.0.0.1:${port}/push/abone-1`, p256dh: b64url(ecdh.getPublicKey()), authKey: b64url(auth) },
  );

  await engine(request, "post", "/v1/remote/enabled", { enabled: true });
  await expect.poll(async () => (await engine(request, "get", "/v1/remote/status")).connected, { timeout: 20_000 }).toBe(true);
  const { qr } = await engine(request, "post", "/v1/remote/pairing");
  await page.goto(`/telefon${qr.slice(qr.indexOf("#"))}`);
  await expect(page.getByTestId("phone-phase")).toContainText("Bağlı", { timeout: 20_000 });

  await expect(page.getByTestId("phone-push-state")).toHaveText("Kapalı");
  await page.getByTestId("phone-push-enable").click();
  await expect(page.getByTestId("phone-toast")).toContainText("Bildirimler açıldı");
  await expect(page.getByTestId("phone-push-state")).toHaveText("Açık");
  const status = await engine(request, "get", "/v1/remote/status");
  expect(status.devices.find((d: { revoked: boolean }) => !d.revoked).push).toBe(true);

  await page.getByTestId("phone-push-test").click();
  await expect(page.getByTestId("phone-toast")).toContainText("Deneme bildirimi gönderildi");
  await expect.poll(() => received.length).toBeGreaterThan(0);
  const first = received[0]!;
  expect(first.headers["content-encoding"]).toBe("aes128gcm");
  expect(String(first.headers.authorization)).toMatch(/^vapid t=.+, k=/);
  expect(first.body.includes(Buffer.from("Deneme"))).toBe(false); // içerik şifreli
  expect(decryptPush(first.body, ecdh, auth).title).toBe("🔔 Deneme bildirimi");

  // Acil durdurma: telefon sayfası açık olmasa da kilit ekranına bildirim gider.
  await page.getByTestId("phone-kill").click();
  await page.getByTestId("phone-kill-confirm").click();
  await expect(page.getByTestId("phone-kill-on")).toBeVisible();
  await expect
    .poll(() => received.map((r) => decryptPush(r.body, ecdh, auth).title))
    .toContain("🛑 Acil durdurma devrede");
  await engine(request, "post", "/v1/kill-switch/release", { confirmation: "SERBEST BIRAK" });

  await page.getByTestId("phone-push-disable").click();
  await expect(page.getByTestId("phone-push-state")).toHaveText("Kapalı");
  await expect.poll(async () => (await engine(request, "get", "/v1/remote/status")).devices.some((d: { push: boolean }) => d.push)).toBe(false);
  server.close();
});
