import { expect, test } from '@playwright/test';

// Etsy and Claude are replaced by contract stubs (tests/helpers/*-stub.ts).
const password = 'e2e-Password-123!';
const email = `market-e2e-${Date.now()}@example.test`;

test('FAZ 5: pazar araştırması → gerçek Etsy verisi + AI fırsatları → kısa liste', async ({
  page,
}) => {
  await page.goto('/signup');
  await page.getByLabel('Ad soyad').fill('Market Owner');
  await page.getByLabel('E-posta').fill(email);
  await page.getByLabel('Parola').fill(password);
  await page.getByRole('button', { name: 'Hesap oluştur' }).click();
  await page.waitForURL('**/dashboard');
  await page.getByLabel('Mağaza adı').fill('E2E Market');
  await page.getByRole('button', { name: 'Mağaza kaydı oluştur' }).click();
  await expect(page.getByRole('heading', { name: 'Genel Bakış' })).toBeVisible();

  await page
    .getByRole('navigation')
    .getByRole('link', { name: /Pazar Araştırma/ })
    .click();
  const form = page.getByRole('form', { name: 'Araştırma başlat' });
  await form.getByLabel(/Konu/).fill('plant mug');
  await form.getByLabel('Alıcı ülkesi').fill('US');
  await form.getByLabel(/Web’de trend/).check();
  await form.getByRole('button', { name: 'Araştırmayı başlat' }).click();
  await page.waitForURL(/market-research\?id=/);

  await expect(async () => {
    await page.reload();
    await expect(page.getByRole('table', { name: 'Pazar verisi' })).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 25_000 });
  await expect(page.getByRole('table', { name: 'Pazar verisi' })).toContainText('12.500');
  const card = page.getByRole('article', { name: 'Fırsat: Botanical Line-Art Plant Mom Mug' });
  await expect(card).toContainText('bilinmiyor'); // no production cost known yet -> no invented profit
  await expect(card).toContainText('[veri]');
  await expect(card).toContainText('[tahmin]');
  await expect(page.getByRole('article', { name: 'Fırsat: Famous Wizard Fan Mug' })).toContainText(
    'Yüksek fikri mülkiyet riski',
  );
  await card.getByRole('button', { name: 'Kısa listeye al' }).click();
  await expect(card).toContainText('Durum: shortlisted');

  await page.goto('/dashboard/opportunities?status=shortlisted');
  await expect(page.getByRole('article')).toHaveCount(1);
});
