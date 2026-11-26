import { expect, test } from '@playwright/test';

// Claude and Printify are replaced by contract stubs (tests/helpers/*-stub.ts).
const password = 'e2e-Password-123!';
const email = `design-e2e-${Date.now()}@example.test`;

test('FAZ 6: tasarım → AI SVG üretimi → baskı dosyası → IP incelemesi → onay → Printify taslağı', async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.goto('/signup');
  await page.getByLabel('Ad soyad').fill('Design Owner');
  await page.getByLabel('E-posta').fill(email);
  await page.getByLabel('Parola').fill(password);
  await page.getByRole('button', { name: 'Hesap oluştur' }).click();
  await page.waitForURL('**/dashboard');
  await page.getByLabel('Mağaza adı').fill('E2E Design');
  await page.getByRole('button', { name: 'Mağaza kaydı oluştur' }).click();
  await expect(page.getByRole('heading', { name: 'Genel Bakış' })).toBeVisible();

  await page.goto('/dashboard/printify');
  const pf = page.getByRole('form', { name: 'Printify bağlantısı' });
  await pf.getByRole('button', { name: 'Printify mağazasını bağla' }).click();
  await expect(page.getByTestId('printify-connection')).toContainText('My Etsy via Printify');

  await page
    .getByRole('navigation')
    .getByRole('link', { name: /Tasarım Stüdyosu/ })
    .click();
  const form = page.getByRole('form', { name: 'Yeni tasarım' });
  await form.getByLabel('Başlık').fill('Grow Slow Botanical Tee');
  await form.getByLabel(/Tasarım özeti/).fill('Minimal botanical typography: grow slow');
  await form
    .getByLabel(/yaratıcı yönlendirmeniz/)
    .fill('Two-line serif lettering with a single hand-drawn fern, sage and cream palette');
  await form.getByRole('button', { name: 'Tasarım oluştur' }).click();
  await page.waitForURL(/design-studio\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId('human-contribution')).toContainText('hand-drawn fern');

  const ops = page.getByRole('form', { name: 'Tasarım işlemleri' });
  await ops.getByRole('button', { name: 'AI ile tasarım üret' }).click();
  await expect(ops.getByRole('status')).toContainText('kuyruğa alındı');
  await expect(async () => {
    await page.reload();
    await expect(page.getByText('v1 · AI üretimi')).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 30_000 });
  await expect(page.getByText('4500×5400 px')).toBeVisible();
  // the image proxy serves the stored PNG to the signed-in user
  const img = page.getByRole('img', { name: 'Sürüm 1' });
  await expect(img).toBeVisible();
  expect(await img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);

  // approval is refused until IP review + print file exist
  await ops.getByRole('button', { name: 'Onayla' }).click();
  await expect(ops.getByRole('alert')).toBeVisible();

  const v1 = page.getByRole('form', { name: /Sürüm işlemleri/ }).first();
  await v1.getByRole('button', { name: 'Baskıya hazırla' }).click();
  await expect(page.getByText(/v2 · Baskı dosyası/)).toBeVisible({ timeout: 10_000 });

  await page
    .getByRole('form', { name: 'Tasarım işlemleri' })
    .getByRole('button', { name: 'IP incelemesi yap' })
    .click();
  await expect(async () => {
    await page.reload();
    await expect(page.getByText(/AI IP incelemesi/)).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 30_000 });

  await page
    .getByRole('form', { name: 'Tasarım işlemleri' })
    .getByRole('button', { name: 'Onayla' })
    .click();
  const product = page.getByRole('form', { name: 'Printify ürünü oluştur' });
  await expect(product).toBeVisible({ timeout: 10_000 });
  await product.getByLabel(/Açıklama/).fill('Original botanical typography tee');
  await product.getByLabel(/varyant/).fill('12100');
  await product.getByLabel(/Satış fiyatı/).fill('28.99');
  await product.getByRole('button', { name: 'Printify’da taslak ürün oluştur' }).click();
  await expect(async () => {
    await page.reload();
    await expect(page.getByRole('link', { name: 'Grow Slow Botanical Tee' })).toBeVisible({
      timeout: 1000,
    });
  }).toPass({ timeout: 15_000 });
});
