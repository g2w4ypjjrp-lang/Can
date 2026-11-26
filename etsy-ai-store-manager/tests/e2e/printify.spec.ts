import { expect, test } from '@playwright/test';

// Printify CONTRACT STUB (tests/helpers/printify-stub.ts) stands in for api.printify.com.
const password = 'e2e-Password-123!';
const email = `printify-e2e-${Date.now()}@example.test`;

test.describe.serial('FAZ 3: Printify', () => {
  test('bağlan → ürünler ve maliyetler → sağlayıcı karşılaştırması → yayın isteği onaya düşer', async ({
    page,
  }) => {
    await page.goto('/signup');
    await page.getByLabel('Ad soyad').fill('Printify Owner');
    await page.getByLabel('E-posta').fill(email);
    await page.getByLabel('Parola').fill(password);
    await page.getByRole('button', { name: 'Hesap oluştur' }).click();
    await page.waitForURL('**/dashboard');
    await page.getByLabel('Mağaza adı').fill('E2E Printify');
    await page.getByRole('button', { name: 'Mağaza kaydı oluştur' }).click();
    await expect(page.getByRole('heading', { name: 'Genel Bakış' })).toBeVisible();

    await page
      .getByRole('navigation')
      .getByRole('link', { name: /Printify/ })
      .click();
    const form = page.getByRole('form', { name: 'Printify bağlantısı' });
    await expect(form.getByLabel(/My Etsy via Printify/)).toBeChecked();
    await form.getByRole('button', { name: 'Printify mağazasını bağla' }).click();
    await expect(page.getByTestId('printify-connection')).toContainText('My Etsy via Printify');

    await expect(async () => {
      await page.goto('/dashboard/products');
      // the stub is shared across specs (the design spec adds a draft), so match by name
      await expect(page.getByRole('row', { name: /Retro Sunset Tee/ })).toBeVisible({
        timeout: 1000,
      });
    }).toPass({ timeout: 20_000 });
    await expect(page.getByRole('row', { name: /Custom Mug 11oz/ })).toContainText('$5,16');

    await page.goto('/dashboard/printify?q=mug&bp=68&country=US');
    const table = page.getByRole('table', { name: 'Sağlayıcı karşılaştırması' });
    await expect(table.getByRole('row').nth(1)).toContainText('Monster Digital');
    await expect(table.getByRole('row').nth(1)).toContainText('$4,75');

    // Profit Engine needs the seller (bank) country
    await page.goto('/dashboard/settings');
    const storeForm = page.getByRole('form', { name: 'Mağaza ayarları' });
    await storeForm.getByLabel(/banka\) ülkesi/).fill('US');
    await storeForm.getByLabel(/Ödeme hesabı para birimi/).fill('USD');
    await storeForm.getByRole('button', { name: 'Mağaza ayarlarını kaydet' }).click();
    await expect(storeForm.getByRole('status')).toHaveText('Kaydedildi');

    await page.goto('/dashboard/products');
    await page.getByRole('link', { name: 'Retro Sunset Tee' }).click();
    const prof = page.getByRole('table', { name: 'Varyant kârlılığı' });
    await expect(prof).toContainText('$9,29');
    await expect(prof).toContainText('Onay bekler');
    await page
      .getByRole('form', { name: 'Yayın isteği' })
      .getByLabel('Gerekçe')
      .fill('Yeni koleksiyon');
    await page.getByRole('button', { name: 'Etsy’de yayınlama isteği oluştur' }).click();
    await expect(
      page.getByRole('form', { name: 'Yayın isteği' }).getByRole('status'),
    ).toContainText('Yayın isteği oluşturuldu');
    await page.goto('/dashboard/etsy');
    await expect(
      page.getByRole('article', { name: /Onay: Etsy’de yayınla: Retro Sunset Tee/ }),
    ).toContainText('publish.json');
  });
});
