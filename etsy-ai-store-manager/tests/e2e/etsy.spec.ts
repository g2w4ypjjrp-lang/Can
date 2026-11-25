import { expect, test, type Page } from '@playwright/test';

// Uses the Etsy CONTRACT STUB (tests/helpers/etsy-stub.ts) in place of etsy.com.
const STUB = 'http://127.0.0.1:4600';
const password = 'e2e-Password-123!';
const email = `etsy-e2e-${Date.now()}@example.test`;

async function login(page: Page) {
  await page.goto('/login');
  await page.getByLabel('E-posta').fill(email);
  await page.getByLabel('Parola').fill(password);
  await page.getByRole('button', { name: 'Giriş yap' }).click();
  await page.waitForURL('**/dashboard');
}

test.describe.serial('FAZ 2: Etsy bağlantısı, içe aktarma ve onaylı ilan değişikliği', () => {
  test('kayıt + mağaza', async ({ page }) => {
    await page.goto('/signup');
    await page.getByLabel('Ad soyad').fill('Etsy Owner');
    await page.getByLabel('E-posta').fill(email);
    await page.getByLabel('Parola').fill(password);
    await page.getByRole('button', { name: 'Hesap oluştur' }).click();
    await page.waitForURL('**/dashboard');
    await page.getByLabel('Mağaza adı').fill('E2E Etsy');
    await page.getByRole('button', { name: 'Mağaza kaydı oluştur' }).click();
    await expect(page.getByRole('heading', { name: 'Genel Bakış' })).toBeVisible();
  });

  test('Etsy ile bağlan → OAuth (PKCE) → içe aktarma', async ({ page }) => {
    await login(page);
    await page
      .getByRole('navigation')
      .getByRole('link', { name: /Etsy Mağazam/ })
      .click();
    await expect(page.getByTestId('etsy-connection')).toContainText('Bağlı değil');
    await page.getByRole('button', { name: 'Etsy ile bağlan' }).click();
    await page.waitForURL('**/dashboard/etsy?connected=1');
    await expect(page.getByText('Etsy mağazanız bağlandı')).toBeVisible();
    await expect(async () => {
      await page.reload();
      await expect(page.getByRole('heading', { name: 'İlanlar (30)' })).toBeVisible({
        timeout: 1000,
      });
    }).toPass({ timeout: 20_000 });
    await expect(page.getByTestId('etsy-connection')).toContainText('StubCeramics');
    // dashboard now reports live data
    await page.goto('/dashboard');
    await expect(page.getByTestId('data-origin')).toHaveText('Canlı veri');
  });

  test('ilan değişikliği önerilir, parolayla onaylanır ve Etsy’de yalnızca o alan değişir', async ({
    page,
    request,
  }) => {
    await login(page);
    await page.goto('/dashboard/etsy?q=Mug%201');
    await page.getByRole('link', { name: 'Handmade Ceramic Mug 1', exact: true }).click();
    const form = page.getByRole('form', { name: 'İlan değişikliği' });
    await form.getByLabel(/Başlık/).fill('Handmade Ceramic Mug – Personalized Gift');
    await form.getByLabel(/Gerekçe/).fill('Arama eşleşmesini iyileştirmek');
    await form.getByRole('button', { name: 'Değişiklik önerisi oluştur' }).click();
    await expect(form.getByRole('status')).toContainText('Onaylanana kadar');

    const before = await (await request.get(`${STUB}/__test/listings/900001`)).json();
    expect(before.title).toBe('Handmade Ceramic Mug 1');

    await page.goto('/dashboard/etsy');
    const card = page.getByRole('article', { name: /Onay: İlan güncelle/ });
    await expect(card).toContainText('PATCH /v3/application/shops/{shop_id}/listings/{listing_id}');
    await expect(card).toContainText('Handmade Ceramic Mug 1');
    // wrong password is refused
    await card.getByLabel(/Parola/).fill('wrong-password');
    await card.getByRole('button', { name: 'Onayla' }).click();
    await expect(card.getByRole('alert')).toHaveText('Parola doğrulanamadı');
    await card.getByLabel(/Parola/).fill(password);
    await card.getByRole('button', { name: 'Onayla' }).click();
    await expect(async () => {
      await page.reload();
      await expect(page.getByTestId('decision').first()).toContainText('Etsy’ye uygulandı', {
        timeout: 1000,
      });
    }).toPass({ timeout: 20_000 });

    await expect(async () => {
      const after = await (await request.get(`${STUB}/__test/listings/900001`)).json();
      expect(after.title).toBe('Handmade Ceramic Mug – Personalized Gift');
      expect(after.description).toBe(before.description);
      expect(after.price).toEqual(before.price);
      expect(after.tags).toEqual(before.tags);
    }).toPass({ timeout: 20_000 });

    await page.goto('/dashboard/notifications');
    await expect(page.getByText('Değişiklik Etsy’ye uygulandı')).toBeVisible();
  });
});
