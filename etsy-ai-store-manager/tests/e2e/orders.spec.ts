import { expect, test, type Page } from '@playwright/test';
import pg from 'pg';

// Etsy and Claude are contract stubs (tests/helpers/*-stub.ts).
const DB =
  process.env.E2E_DATABASE_URL ?? 'postgresql://postgres:postgres@127.0.0.1:54322/postgres';
const password = 'e2e-Password-123!';
const email = `orders-e2e-${Date.now()}@example.test`;

async function sql(q: string) {
  const c = new pg.Client({ connectionString: DB });
  await c.connect();
  try {
    await c.query(q);
  } finally {
    await c.end();
  }
}
async function approve(page: Page, name: RegExp) {
  await page.goto('/dashboard/etsy');
  const card = page.getByRole('article', { name });
  await expect(card).toBeVisible();
  const pw = card.getByLabel(/Parola/);
  if (await pw.count()) await pw.fill(password);
  await card.getByRole('button', { name: 'Onayla' }).click();
  await expect(card).toHaveCount(0, { timeout: 10_000 });
}

test('FAZ 9: siparişler → takip no onayı → Etsy; yorum/mesaj → AI taslak → onay → manuel gönderim', async ({
  page,
}) => {
  test.setTimeout(150_000);
  await page.goto('/signup');
  await page.getByLabel('Ad soyad').fill('Orders Owner');
  await page.getByLabel('E-posta').fill(email);
  await page.getByLabel('Parola').fill(password);
  await page.getByRole('button', { name: 'Hesap oluştur' }).click();
  await page.waitForURL('**/dashboard');
  await page.getByLabel('Mağaza adı').fill('E2E Orders');
  await page.getByRole('button', { name: 'Mağaza kaydı oluştur' }).click();
  await expect(page.getByRole('heading', { name: 'Genel Bakış' })).toBeVisible();
  await sql(
    `update public.stores set external_shop_id = null where external_shop_id = '55001' and name like 'E2E%'`,
  );
  await page.goto('/dashboard/etsy');
  await page.getByRole('button', { name: 'Etsy ile bağlan' }).click();
  await page.waitForURL('**/dashboard/etsy?connected=1');

  await page.goto('/dashboard/orders');
  await expect(async () => {
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Siparişler (3)' })).toBeVisible({
      timeout: 1000,
    });
  }).toPass({ timeout: 20_000 });
  await page.getByRole('link', { name: 'Gönderilmemiş' }).click();
  await page.getByRole('link', { name: '#1001' }).click();
  const tf = page.getByRole('form', { name: 'Takip numarası' });
  await tf.getByLabel('Takip numarası').fill('9400E2E1001');
  await tf.getByLabel('Kargo firması').fill('usps');
  await tf.getByLabel('Gerekçe').fill('Kargoya verildi');
  await tf.getByRole('button', { name: 'Onaya gönder' }).click();
  await expect(tf.getByRole('status')).toContainText('Onay isteği');
  await approve(page, /Onay: Kargo takip no gönder/);
  await page.goto('/dashboard/orders?filter=unshipped');
  await expect(async () => {
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Siparişler (0)' })).toBeVisible({
      timeout: 1000,
    });
  }).toPass({ timeout: 20_000 });

  // low-rated Etsy review → AI draft
  await page.goto('/dashboard/customers');
  const review = page.getByRole('article').filter({ hasText: 'Etsy yorumu 2★' });
  await expect(async () => {
    await page.reload();
    await expect(review.getByTestId('message-status')).toHaveText('draft_ready', { timeout: 1000 });
  }).toPass({ timeout: 30_000 });
  await expect(review.getByLabel('Yanıt taslağı')).toHaveValue(/sorry/);

  // pasted message → draft → approval → sent manually
  const add = page.getByRole('form', { name: 'Mesaj ekle' });
  await add.getByLabel('Müşteri mesajı').fill('Hello, can you change the color of my order?');
  await add.getByLabel('Sipariş no').fill('1001');
  await add.getByRole('button', { name: 'Kaydet ve taslak hazırla' }).click();
  await expect(add.getByRole('status')).toContainText('Kaydedildi');
  const msg = page.getByRole('article').filter({ hasText: 'change the color' });
  await expect(async () => {
    await page.reload();
    await expect(msg.getByTestId('message-status')).toHaveText('draft_ready', { timeout: 1000 });
  }).toPass({ timeout: 30_000 });
  await msg
    .getByLabel('Yanıt taslağı')
    .fill('Hi! Your order already shipped with USPS 9400E2E1001, so the color cannot be changed.');
  await msg.getByRole('button', { name: 'Yanıtı onaya gönder' }).click();
  await approve(page, /Onay: Müşteri mesajı yanıtı/);
  await page.goto('/dashboard/customers');
  await expect(page.getByText('USPS 9400E2E1001, so the color').first()).toBeVisible();
  await page
    .getByRole('form', { name: 'Manuel uygulamayı onayla' })
    .getByLabel('Not')
    .fill('Etsy Mesajlar’dan gönderildi');
  await page
    .getByRole('form', { name: 'Manuel uygulamayı onayla' })
    .getByRole('button', { name: 'Uyguladım' })
    .click();
  await expect(page.getByText('Onaylandı — Etsy’de gönderin')).toHaveCount(0, { timeout: 10_000 });
  await expect(page.getByRole('article').filter({ hasText: 'change the color' })).toHaveCount(0); // no longer open
});
