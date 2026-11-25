import type { Metadata } from 'next';
import type { MeResponse, ProfitRulesDto, StoreSettingsDto } from '@esm/shared';
import { api } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { Card, Notice, PageHeader } from '@/components/ui';
import { ProfitRulesForm, StoreSettingsForm, UserSettingsForm } from '@/components/settings-forms';

export const metadata: Metadata = { title: 'Ayarlar' };

export default async function SettingsPage() {
  const [me, { current }] = await Promise.all([api<MeResponse>('/me'), loadStores()]);
  const [settings, rules] = current
    ? await Promise.all([
        api<StoreSettingsDto>(`/stores/${current.id}/settings`),
        api<ProfitRulesDto>(`/stores/${current.id}/profit-rules`),
      ])
    : [null, null];

  return (
    <>
      <PageHeader
        title="Ayarlar"
        description="Hesap, mağaza stratejisi, diller, reklam bütçesi ve kâr politikası"
      />
      <div className="space-y-6">
        <Card title="Kişisel ayarlar">
          <UserSettingsForm me={me} />
        </Card>
        {current && settings && rules ? (
          <>
            <Card title={`Mağaza: ${current.name}`}>
              <StoreSettingsForm settings={settings} />
            </Card>
            <Card title="Kâr politikası (katkı eşikleri)">
              <p className="mb-4 text-sm text-slate-600">
                Net katkı = Net satış geliri − Toplam değişken giderler. Eşikler ürün yayın
                kararlarında kullanılır (FAZ 4 Profit Engine). Değişiklikler denetim kaydına
                yazılır.
              </p>
              <ProfitRulesForm rules={rules} />
            </Card>
            <Card title="API bağlantıları">
              <Notice>
                Etsy (FAZ 2), Printify (FAZ 3) ve reklam hesapları (FAZ 8) resmi OAuth akışlarıyla
                bağlanacak. API anahtarları yalnızca sunucu tarafındaki <code>.env</code> dosyasında
                tutulur; bu panele anahtar girilmez.
              </Notice>
            </Card>
          </>
        ) : (
          <Notice>Mağaza ayarları için önce Genel Bakış sayfasından mağaza kaydı oluşturun.</Notice>
        )}
      </div>
    </>
  );
}
