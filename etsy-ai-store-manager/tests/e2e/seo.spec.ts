import { expect, test, type Locator, type Page } from '@playwright/test';
import pg from 'pg';

// Etsy and Claude are contract stubs (tests/helpers/*-stub.ts).
const STUB = 'http://127.0.0.1:4600';
const DB =
  process.env.E2E_DATABASE_URL ?? 'postgresql://postgres:postgres@127.0.0.1:54322/postgres';
const password = 'e2e-Password-123!';
const email = `seo-e2e-${Date.now()}@example.test`;

async function sql(q: string, params: unknown[] = []) {
  const c = new pg.Client({ connectionString: DB });
  await c.connect();
  try {
    return await c.query(q, params);
  } finally {
    await c.end();
  }
}

async function approveOnEtsyPage(page: Page, name: RegExp) {
  await page.goto('/dashboard/etsy');
  const card: Locator = page.getByRole('article', { name });
  await expect(card).toBeVisible();
  const pw = card.getByLabel(/Parola/);
  if (await pw.count()) await pw.fill(password);
  await card.getByRole('button', { name: 'Onayla' }).click();
  await expect(card).toHaveCount(0, { timeout: 10_000 });
}

test('FAZ 7: AI SEO önerisi → onay → Etsy; çok dilli çeviri → insan incelemesi → onay', async ({
  page,
  request,
}) => {
  test.setTimeout(150_000);
  await page.goto('/signup');
  await page.getByLabel('Ad soyad').fill('SEO Owner');
  await page.getByLabel('E-posta').fill(email);
  await page.getByLabel('Parola').fill(password);
  await page.getByRole('button', { name: 'Hesap oluştur' }).click();
  await page.waitForURL('**/dashboard');
  await page.getByLabel('Mağaza adı').fill('E2E SEO');
  await page.getByRole('button', { name: 'Mağaza kaydı oluştur' }).click();
  await expect(page.getByRole('heading', { name: 'Genel Bakış' })).toBeVisible();

  // the Etsy stub shop can belong to one store only: release it from earlier E2E stores
  await sql(
    `update public.stores set external_shop_id = null where external_shop_id = '55001' and name like 'E2E%'`,
  );
  await page.goto('/dashboard/etsy');
  await page.getByRole('button', { name: 'Etsy ile bağlan' }).click();
  await page.waitForURL('**/dashboard/etsy?connected=1');
  await expect(async () => {
    await page.reload();
    await expect(page.getByRole('heading', { name: 'İlanlar (30)' })).toBeVisible({
      timeout: 1000,
    });
  }).toPass({ timeout: 20_000 });
  await sql(
    `update public.store_settings set languages = array['en','de'] where store_id = (select id from public.stores where name = 'E2E SEO' order by created_at desc limit 1)`,
  );

  // ---- SEO draft
  await page.goto('/dashboard/etsy?q=Mug%202');
  await page.getByRole('link', { name: 'Handmade Ceramic Mug 2', exact: true }).click();
  await page.waitForURL(/\/dashboard\/etsy\/listings\/[0-9a-f-]{36}$/);
  const listingUrl = page.url();
  await page
    .getByRole('form', { name: 'SEO önerisi iste' })
    .getByRole('button', { name: 'AI SEO önerisi hazırla' })
    .click();
  await expect(
    page.getByRole('form', { name: 'SEO önerisi iste' }).getByRole('status'),
  ).toContainText('hazırlanıyor');
  const card = page.getByRole('article', { name: 'SEO önerisi en' }).first();
  await expect(async () => {
    await page.reload();
    await expect(card.getByTestId('seo-status')).toHaveText('draft', { timeout: 1000 });
  }).toPass({ timeout: 30_000 });
  await expect(card.getByLabel(/^Başlık/)).toHaveValue(/^Botanical T-Shirt/);
  await expect(card.getByLabel('Kontrol sonuçları')).toContainText('boş etiket hakkı');
  await card.getByLabel('Gerekçe').fill('Arama görünürlüğü');
  await card.getByRole('button', { name: 'Uygulamak için onaya gönder' }).click();
  await expect(card.getByRole('status')).toContainText('Onay isteği oluşturuldu');
  const before = await (await request.get(`${STUB}/__test/listings/900002`)).json();
  expect(before.title).toBe('Handmade Ceramic Mug 2'); // nothing sent before approval

  await approveOnEtsyPage(page, /Onay: SEO uygula/);
  await expect(async () => {
    const after = await (await request.get(`${STUB}/__test/listings/900002`)).json();
    expect(after.title).toBe(
      'Botanical T-Shirt, Grow Slow Fern Tee, Minimal Plant Lover Gift for Gardeners',
    );
    expect(after.tags).toHaveLength(12);
    expect(after.price).toEqual(before.price);
  }).toPass({ timeout: 20_000 });

  // ---- translation
  await page.goto(listingUrl);
  await expect(
    page.getByRole('article', { name: 'SEO önerisi en' }).first().getByTestId('seo-status'),
  ).toHaveText('applied');
  const tf = page.getByRole('form', { name: 'Çeviri iste' });
  await tf.getByLabel('de').check();
  await tf.getByRole('button', { name: 'AI ile yerelleştir' }).click();
  const tr = page.getByRole('article', { name: 'Çeviri de' });
  await expect(async () => {
    await page.reload();
    await expect(tr.getByTestId('translation-status')).toHaveText('draft', { timeout: 1000 });
  }).toPass({ timeout: 30_000 });
  await expect(tr).toContainText('Geri çeviri');
  await tr.getByRole('button', { name: 'İnceledim, doğru' }).click();
  await expect(tr.getByTestId('translation-status')).toHaveText('reviewed', { timeout: 10_000 });
  await tr.getByLabel('Gerekçe').fill('Almanya pazarı');
  await tr.getByRole('button', { name: 'Etsy’ye eklemek için onaya gönder' }).click();
  await expect(tr.getByRole('status')).toContainText('Onay isteği');
  await approveOnEtsyPage(page, /Onay: Çeviri yayınla \(de\)/);
  await expect(async () => {
    await page.goto(listingUrl);
    await expect(
      page.getByRole('article', { name: 'Çeviri de' }).getByTestId('translation-status'),
    ).toHaveText('published', {
      timeout: 1000,
    });
  }).toPass({ timeout: 20_000 });

  // ---- SEO centre + live checker
  await page
    .getByRole('navigation')
    .getByRole('link', { name: /SEO Merkezi/ })
    .click();
  await expect(page.getByRole('table', { name: 'SEO önerileri' })).toContainText('Uygulandı');
  const chk = page.getByRole('form', { name: 'Kural kontrolü' });
  await chk.getByLabel('Başlık').fill('Plant Shirt Plant Lover Plant Gift');
  await chk.getByLabel('Açıklama').fill('Nice shirt');
  await chk.getByRole('button', { name: 'Kontrol et' }).click();
  await expect(page.getByTestId('seo-check')).toContainText('gönderilemez');
});
