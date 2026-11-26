import { expect, test } from '@playwright/test';

const password = 'e2e-Password-123!';
const email = `ads-e2e-${Date.now()}@example.test`;
const d = (o: number) => new Date(Date.now() - o * 86_400_000).toISOString().slice(0, 10);

test('FAZ 8: bütçe sınırı → CSV rapor → kâr odaklı dağıtım → onay → manuel uygulama', async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.goto('/signup');
  await page.getByLabel('Ad soyad').fill('Ads Owner');
  await page.getByLabel('E-posta').fill(email);
  await page.getByLabel('Parola').fill(password);
  await page.getByRole('button', { name: 'Hesap oluştur' }).click();
  await page.waitForURL('**/dashboard');
  await page.getByLabel('Mağaza adı').fill('E2E Ads');
  await page.getByRole('button', { name: 'Mağaza kaydı oluştur' }).click();
  await expect(page.getByRole('heading', { name: 'Genel Bakış' })).toBeVisible();

  await page
    .getByRole('navigation')
    .getByRole('link', { name: /Reklam Yönetimi/ })
    .click();
  await expect(page.getByText('Önce günlük reklam bütçesi üst sınırını belirleyin')).toBeVisible();
  await expect(page.getByText('Etsy Open API v3’te Etsy Ads uç noktası yok')).toBeVisible();

  const policy = page.getByRole('form', { name: 'Bütçe sınırı' });
  await policy.getByLabel('Günlük üst sınır').fill('40');
  await policy.getByLabel(/Aylık üst sınır/).fill('900');
  await policy.getByRole('button', { name: 'Sınırı kaydet' }).click();
  await expect(policy.getByRole('status')).toHaveText('Bütçe sınırı kaydedildi.');

  const acct = page.getByRole('form', { name: 'Reklam hesabı ekle' });
  await acct.getByLabel('Platform').selectOption('pinterest_ads');
  await acct.getByLabel('Hesap kimliği').fill('549');
  await acct.getByLabel('Hesap adı').fill('Pins');
  await acct.getByRole('button', { name: 'Ekle' }).click();
  await expect(acct.getByRole('status')).toContainText('eklendi');

  const csv = page.getByRole('form', { name: 'Rapor içe aktar' });
  await csv
    .getByLabel('CSV', { exact: true })
    .fill(
      [
        'date,campaign,impressions,clicks,spend,orders,revenue',
        `${d(1)},Plant tees,4000,150,12.00,0,0`,
        `${d(2)},Plant tees,4000,90,8.00,0,0`,
        `${d(1)},Mug pins,900,40,3.00,1,22.00`,
      ].join('\n'),
    );
  await csv.getByRole('button', { name: 'İçe aktar' }).click();
  await expect(csv.getByRole('status')).toHaveText('3 satır içe aktarıldı.');

  const table = page.getByRole('table', { name: 'Kampanyalar' });
  await expect(table.getByRole('row', { name: /Plant tees/ })).toContainText('20.00');
  // no profitable orders yet → break-even unknown → no judgement on missing data
  await expect(table.getByRole('row', { name: /Plant tees/ })).toContainText('Veri yetersiz');

  const prop = page.getByRole('form', { name: 'Bütçe önerisi' });
  await prop.getByLabel('Toplam günlük bütçe').fill('60');
  await prop.getByRole('button', { name: 'Dağıtım önerisi oluştur' }).click();
  await expect(prop.getByRole('alert')).toContainText('sınırı aşıyor');
  await prop.getByLabel('Toplam günlük bütçe').fill('30');
  await prop.getByRole('button', { name: 'Dağıtım önerisi oluştur' }).click();
  await expect(page.getByTestId('proposal-status')).toHaveText('draft');
  const sub = page.getByRole('form', { name: 'Öneriyi onaya gönder' });
  await sub.getByLabel('Gerekçe').fill('Test bütçesi');
  await sub.getByRole('button', { name: 'Onaya gönder' }).click();
  await expect(page.getByTestId('proposal-status')).toHaveText('pending_approval');

  await page.goto('/dashboard/etsy');
  const card = page.getByRole('article', { name: /Onay: Reklam bütçesi dağıtımı/ });
  await expect(card).toContainText('MANUEL');
  await card.getByLabel(/Parola/).fill(password);
  await card.getByRole('button', { name: 'Onayla' }).click();
  await expect(card).toHaveCount(0, { timeout: 10_000 });

  await page.goto('/dashboard/ads');
  const manual = page.getByRole('article', { name: /Manuel uygulama: Reklam bütçesi dağıtımı/ });
  await expect(manual).toContainText('panelinde uygulayın');
  await manual.getByLabel('Not').fill('Pinterest Ads panelinde günlük bütçeleri güncelledim');
  await manual.getByRole('button', { name: 'Uyguladım' }).click();
  await expect(page.getByTestId('proposal-status')).toHaveText('applied', { timeout: 10_000 });
  await expect(
    page.getByRole('table', { name: 'Kampanyalar' }).getByRole('row', { name: /Plant tees/ }),
  ).toContainText('15.00');
});
