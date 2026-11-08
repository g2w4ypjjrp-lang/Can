// Her herkese açık sayfa: güvenlik başlıkları, CSP ihlali olmaması, risk uyarısı, kazanç vaadi
// bulunmaması ve axe ile WCAG 2.1 AA erişilebilirlik denetimi (açık ve koyu tema).
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { findForbiddenClaims, RISK_NOTICE_MARKER } from "../lib/content-policy";
import { PUBLIC_PAGES } from "../lib/pages";

function collectProblems(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  page.on("pageerror", (error) => problems.push(error.message));
  return problems;
}

async function axe(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]).analyze();
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`);
}

for (const path of PUBLIC_PAGES) {
  test(`sayfa ${path}: başlıklar, içerik kuralı ve erişilebilirlik`, async ({ page }) => {
    const problems = collectProblems(page);
    const response = await page.goto(path);
    expect(response?.status()).toBe(200);

    const headers = response!.headers();
    const csp = headers["content-security-policy"] ?? "";
    expect(csp).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("connect-src 'self' http://127.0.0.1:8100");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
    expect(headers["x-powered-by"]).toBeUndefined();

    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("html")).toHaveAttribute("lang", "tr");
    const text = await page.locator("body").innerText();
    expect(findForbiddenClaims(text)).toEqual([]);
    expect(text).toContain(RISK_NOTICE_MARKER);

    // Sayfa etkileşimli hâle gelmeli (nonce'lu betikler çalıştı, hidrasyon tamam).
    await page.waitForLoadState("networkidle");
    expect(await axe(page)).toEqual([]);
    // Koyu tema: sayfa koyu temada yeniden yüklenir (renk geçişi animasyonu ölçümü bozmasın).
    await page.emulateMedia({ colorScheme: "dark" });
    await page.reload();
    await page.waitForLoadState("networkidle");
    expect(await axe(page)).toEqual([]);
    expect(problems).toEqual([]);
  });
}

test("aynı sayfanın iki isteği farklı nonce alır", async ({ request }) => {
  const nonceOf = async () => (await request.get("/")).headers()["content-security-policy"]?.match(/nonce-([^']+)/)?.[1];
  const [a, b] = [await nonceOf(), await nonceOf()];
  expect(a).toBeTruthy();
  expect(a).not.toBe(b);
});

test("istemci tarafı gezinme ve mobil menü çalışır", async ({ page }) => {
  const problems = collectProblems(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByText("Menü", { exact: true }).click();
  await page.getByRole("navigation", { name: "Mobil menü" }).getByRole("link", { name: "SSS" }).click();
  await expect(page).toHaveURL(/\/sss$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sık sorulan sorular");
  await page.getByText("Yazılım kazanç sağlar mı?").click();
  await expect(page.getByText("Hayır, böyle bir vaadimiz yok.", { exact: false })).toBeVisible();
  expect(await axe(page)).toEqual([]);
  expect(problems).toEqual([]);
});

test("robots ve site haritası özel sayfaları dışarıda bırakır", async ({ request }) => {
  const robots = await (await request.get("/robots.txt")).text();
  expect(robots).toContain("Disallow: /panel");
  expect(robots).toContain("Sitemap: http://127.0.0.1:3100/sitemap.xml");
  const sitemap = await (await request.get("/sitemap.xml")).text();
  expect(sitemap).toContain("http://127.0.0.1:3100/paketler");
  expect(sitemap).not.toContain("/panel");
});

test("bilinmeyen adres 404 döner", async ({ page }) => {
  const response = await page.goto("/yok-boyle-bir-sayfa");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sayfa bulunamadı");
});
