import { expect, test } from '@playwright/test';

const password = 'e2e-Password-123!';
const email = `finance-e2e-${Date.now()}@example.test`;

test('FAZ 4: simülatör, karar ve ücret kuralı doğrulama', async ({ page }) => {
  await page.goto('/signup');
  await page.getByLabel('Ad soyad').fill('Finance Owner');
  await page.getByLabel('E-posta').fill(email);
  await page.getByLabel('Parola').fill(password);
  await page.getByRole('button', { name: 'Hesap oluştur' }).click();
  await page.waitForURL('**/dashboard');
  await page.getByLabel('Mağaza adı').fill('E2E Finance');
  await page.getByRole('button', { name: 'Mağaza kaydı oluştur' }).click();
  await expect(page.getByRole('heading', { name: 'Genel Bakış' })).toBeVisible();

  await page
    .getByRole('navigation')
    .getByRole('link', { name: /Finans ve Kâr/ })
    .click();
  await expect(page.getByText('Satıcı (banka) ülkesi ayarlanmadı')).toBeVisible();

  await page.goto('/dashboard/settings');
  const storeForm = page.getByRole('form', { name: 'Mağaza ayarları' });
  await storeForm.getByLabel(/banka\) ülkesi/).fill('US');
  await storeForm.getByLabel(/Ödeme hesabı para birimi/).fill('USD');
  await storeForm.getByRole('button', { name: 'Mağaza ayarlarını kaydet' }).click();
  await expect(storeForm.getByRole('status')).toHaveText('Kaydedildi');

  await page.goto('/dashboard/finance');
  const sim = page.getByRole('form', { name: 'Kârlılık simülatörü' });
  await sim.getByRole('button', { name: 'Hesapla' }).click();
  const result = page.getByTestId('simulation-result');
  await expect(result).toContainText('11.0910 USD');
  await expect(result).toContainText('Yayınlanabilir');
  await expect(result).toContainText('28.99');
  await expect(result).toContainText('doğrulanmamış');

  await sim.getByLabel('Satış fiyatı (birim)').fill('15');
  await sim.getByRole('button', { name: 'Hesapla' }).click();
  await expect(result).toContainText('-2.4750 USD');
  await expect(result).toContainText('Reddedilir');

  const rules = page.getByRole('table', { name: 'Ücret kuralları' });
  const txRow = rules.getByRole('row', { name: /İşlem/ }).first();
  await txRow.getByRole('button', { name: 'Doğrula' }).click();
  await expect(rules.getByRole('row', { name: /İşlem/ }).first()).toContainText('✓');
});
