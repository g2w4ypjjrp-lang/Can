import { expect, test, type Page } from '@playwright/test';

const password = 'e2e-Password-123!';
const email = `e2e-${Date.now()}@example.test`;

async function signUp(page: Page, email: string) {
  await page.goto('/signup');
  await page.getByLabel('Ad soyad').fill('E2E Owner');
  await page.getByLabel('E-posta').fill(email);
  await page.getByLabel('Parola').fill(password);
  await page.getByRole('button', { name: 'Hesap oluştur' }).click();
  await page.waitForURL('**/dashboard');
}

async function logIn(page: Page) {
  await page.goto('/login');
  await page.getByLabel('E-posta').fill(email);
  await page.getByLabel('Parola').fill(password);
  await page.getByRole('button', { name: 'Giriş yap' }).click();
  await page.waitForURL('**/dashboard');
}

test.describe.serial('Faz 1 akışı (gerçek Supabase Auth + API + RLS)', () => {
  test('korumalı sayfalar girişe yönlendirir', async ({ page }) => {
    await page.goto('/dashboard/settings');
    await expect(page).toHaveURL(/\/login\?next=%2Fdashboard%2Fsettings/);
  });

  test('hatalı parola reddedilir', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('E-posta').fill('nobody@example.test');
    await page.getByLabel('Parola').fill('wrong-password-123');
    await page.getByRole('button', { name: 'Giriş yap' }).click();
    await expect(page.locator('form').getByRole('alert')).toHaveText('E-posta veya parola hatalı');
  });

  test('kayıt → mağaza kaydı → gerçek veri olmadan dashboard', async ({ page }) => {
    await signUp(page, email);
    await expect(page.getByRole('heading', { name: 'Hoş geldiniz' })).toBeVisible();
    await expect(page.getByTestId('user-email')).toHaveText('E2E Owner');
    await page.getByLabel('Mağaza adı').fill('E2E Etsy Shop');
    await page.getByRole('button', { name: 'Mağaza kaydı oluştur' }).click();
    await expect(page.getByRole('heading', { name: 'Genel Bakış' })).toBeVisible();
    await expect(page.getByTestId('data-origin')).toHaveText('Veri kaynağı bağlı değil');
    await expect(page.getByText('Etsy mağazası henüz bağlanmadı')).toBeVisible();
    await expect(page.getByText('Bu dönemde kayıtlı satış yok')).toBeVisible();
    await expect(page.getByTestId('kpis')).toContainText('Aylık sipariş');
  });

  test('sol menüde 17 modül var ve planlanan modüller dürüst durum gösterir', async ({ page }) => {
    await logIn(page);
    const nav = page.getByRole('navigation');
    await expect(nav.getByRole('link')).toHaveCount(17);
    await nav.getByRole('link', { name: /Siparişler/ }).click();
    await expect(page.getByRole('heading', { name: 'Siparişler' })).toBeVisible();
    await expect(page.getByText('FAZ 9')).toBeVisible();
    await expect(page.getByTestId('module-status')).toHaveText('Durum: Planlandı');
  });

  test('kâr politikası ve mağaza ayarları güncellenir, hatalı sıra reddedilir', async ({
    page,
  }) => {
    await logIn(page);
    await page.goto('/dashboard/settings');
    const profit = page.getByRole('form', { name: 'Kâr politikası' });
    await expect(profit.getByLabel(/Hedef katkı/)).toHaveValue('10.00');
    await profit.getByLabel(/Hedef katkı/).fill('12');
    await profit.getByLabel(/“Yayınlanabilir” eşiği/).fill('12');
    await profit.getByRole('button', { name: 'Kâr politikasını kaydet' }).click();
    await expect(profit.getByRole('status')).toHaveText('Kaydedildi');

    await profit.getByLabel(/“Onay bekler” eşiği/).fill('20');
    await profit.getByRole('button', { name: 'Kâr politikasını kaydet' }).click();
    await expect(profit.getByRole('alert')).toContainText('Yayınlanabilir');

    const store = page.getByRole('form', { name: 'Mağaza ayarları' });
    await store.getByRole('checkbox', { name: 'Deutsch' }).check();
    await store.getByLabel(/Günlük toplam reklam bütçesi/).fill('15');
    await store.getByRole('button', { name: 'Mağaza ayarlarını kaydet' }).click();
    await expect(store.getByRole('status')).toHaveText('Kaydedildi');

    await page.reload();
    await expect(
      page.getByRole('form', { name: 'Kâr politikası' }).getByLabel(/Hedef katkı/),
    ).toHaveValue('12.00');
    await expect(
      page
        .getByRole('form', { name: 'Mağaza ayarları' })
        .getByRole('checkbox', { name: 'Deutsch' }),
    ).toBeChecked();
    await expect(
      page
        .getByRole('form', { name: 'Mağaza ayarları' })
        .getByLabel(/Günlük toplam reklam bütçesi/),
    ).toHaveValue('15.00');
  });

  test('çıkış yapınca oturum kapanır', async ({ page }) => {
    await logIn(page);
    await page.getByRole('button', { name: /Çıkış/ }).click();
    await page.waitForURL('**/login');
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/login/);
  });

  test('PWA manifest ve service worker sunulur', async ({ request }) => {
    const manifest = await request.get('/manifest.webmanifest');
    expect(manifest.ok()).toBe(true);
    expect((await manifest.json()).display).toBe('standalone');
    expect((await request.get('/sw.js')).ok()).toBe(true);
    expect((await request.get('/icons/icon-512.png')).ok()).toBe(true);
  });

  test('mobilde menü açılır @mobile', async ({ page }) => {
    await signUp(page, `e2e-mobile-${Date.now()}@example.test`);
    await page.getByRole('button', { name: 'Menüyü aç' }).click();
    await page
      .getByRole('navigation')
      .getByRole('link', { name: /Ayarlar/ })
      .click();
    await expect(page.getByRole('heading', { name: 'Ayarlar', exact: true })).toBeVisible();
  });
});
