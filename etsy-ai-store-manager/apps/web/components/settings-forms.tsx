'use client';

import { useActionState } from 'react';
import {
  STORE_LANGUAGES,
  type MeResponse,
  type ProfitRulesDto,
  type StoreSettingsDto,
} from '@esm/shared';
import {
  updateProfitRulesAction,
  updateStoreSettingsAction,
  updateUserSettingsAction,
  type FormState,
} from '@/app/dashboard/actions';

const input = 'w-full rounded-lg border border-line bg-white px-3 py-2 text-sm';
const label = 'mb-1 block text-sm font-medium text-slate-700';

function Status({ state, pending }: { state: FormState; pending: boolean }) {
  if (pending) return <span className="text-sm text-slate-500">Kaydediliyor…</span>;
  if (state.error)
    return (
      <span role="alert" className="text-sm text-red-700">
        {state.error}
      </span>
    );
  if (state.ok)
    return (
      <span role="status" className="text-sm text-emerald-700">
        Kaydedildi
      </span>
    );
  return null;
}

function Submit({ pending, children }: { pending: boolean; children: React.ReactNode }) {
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded-lg bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-60"
    >
      {children}
    </button>
  );
}

export function UserSettingsForm({ me }: { me: MeResponse }) {
  const [state, action, pending] = useActionState<FormState, FormData>(
    updateUserSettingsAction,
    {},
  );
  const s = me.settings;
  return (
    <form action={action} className="grid gap-4 sm:grid-cols-2" aria-label="Kişisel ayarlar">
      <label>
        <span className={label}>Ad soyad</span>
        <input name="fullName" defaultValue={me.fullName ?? ''} maxLength={120} className={input} />
      </label>
      <label>
        <span className={label}>E-posta</span>
        <input value={me.email} disabled className={`${input} bg-slate-50 text-slate-500`} />
      </label>
      <label>
        <span className={label}>Saat dilimi</span>
        <input name="timezone" defaultValue={me.timezone} className={input} />
      </label>
      <label>
        <span className={label}>Panel dili</span>
        <select name="uiLanguage" defaultValue={s.uiLanguage} className={input}>
          <option value="tr">Türkçe</option>
          <option value="en">English</option>
        </select>
      </label>
      <label>
        <span className={label}>Raporlama para birimi</span>
        <input
          name="baseCurrency"
          defaultValue={s.baseCurrency}
          maxLength={3}
          className={`${input} uppercase`}
        />
      </label>
      <fieldset className="space-y-2 sm:col-span-2">
        <legend className={label}>Bildirimler ve güvenlik</legend>
        <Check name="notifyEmail" defaultChecked={s.notifyEmail} text="E-posta bildirimleri" />
        <Check name="notifyPush" defaultChecked={s.notifyPush} text="Anlık (push) bildirimler" />
        <Check name="notifyDailyReport" defaultChecked={s.notifyDailyReport} text="Günlük rapor" />
        <Check
          name="requireReauthForSensitive"
          defaultChecked={s.requireReauthForSensitive}
          text="Hassas işlemlerde yeniden kimlik doğrulama iste"
        />
      </fieldset>
      <div className="flex items-center gap-3 sm:col-span-2">
        <Submit pending={pending}>Kaydet</Submit>
        <Status state={state} pending={pending} />
      </div>
    </form>
  );
}

function Check({
  name,
  defaultChecked,
  text,
}: {
  name: string;
  defaultChecked: boolean;
  text: string;
}) {
  return (
    <label className="flex items-center gap-2 text-sm text-slate-700">
      <input
        type="checkbox"
        name={name}
        defaultChecked={defaultChecked}
        className="h-4 w-4 rounded border-line accent-brand-600"
      />
      {text}
    </label>
  );
}

export function StoreSettingsForm({ settings }: { settings: StoreSettingsDto }) {
  const [state, action, pending] = useActionState<FormState, FormData>(
    updateStoreSettingsAction,
    {},
  );
  return (
    <form action={action} className="grid gap-4 sm:grid-cols-2" aria-label="Mağaza ayarları">
      <input type="hidden" name="storeId" value={settings.storeId} />
      <label>
        <span className={label}>Satış stratejisi</span>
        <select name="salesStrategy" defaultValue={settings.salesStrategy} className={input}>
          <option value="growth">Büyüme öncelikli</option>
          <option value="balanced">Dengeli büyüme ve kârlılık</option>
          <option value="profit">Kârlılık öncelikli</option>
        </select>
      </label>
      <label>
        <span className={label}>AI yetkisi</span>
        <select name="automationLevel" defaultValue={settings.automationLevel} className={input}>
          <option value="manual">Yalnızca öneri</option>
          <option value="controlled">Kontrollü otomasyon (onaylı)</option>
          <option value="autonomous_limited">Sınırlı otonom (düşük riskli işler)</option>
        </select>
      </label>
      <fieldset className="sm:col-span-2">
        <legend className={label}>Mağaza dilleri (SEO / çeviri)</legend>
        <div className="flex flex-wrap gap-3">
          {STORE_LANGUAGES.map((l) => (
            <label key={l.code} className="flex items-center gap-1.5 text-sm text-slate-700">
              <input
                type="checkbox"
                name="languages"
                value={l.code}
                defaultChecked={settings.languages.includes(l.code)}
                className="h-4 w-4 accent-brand-600"
              />
              {l.name}
            </label>
          ))}
        </div>
      </fieldset>
      <label>
        <span className={label}>Varsayılan dil</span>
        <select name="defaultLanguage" defaultValue={settings.defaultLanguage} className={input}>
          {STORE_LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span className={label}>Hedef pazarlar (ISO, virgülle)</span>
        <input
          name="targetMarkets"
          defaultValue={settings.targetMarkets.join(', ')}
          placeholder="US, GB, DE, FR"
          className={input}
        />
      </label>
      <label>
        <span className={label}>Günlük toplam reklam bütçesi sınırı</span>
        <input
          name="dailyAdBudgetCap"
          defaultValue={settings.dailyAdBudgetCap}
          inputMode="decimal"
          className={input}
        />
        <span className="mt-1 block text-xs text-slate-500">
          Tüm platformların toplamı bu tutarı aşamaz. 0 = reklam kapalı.
        </span>
      </label>
      <label>
        <span className={label}>Bütçe para birimi</span>
        <input
          name="adBudgetCurrency"
          defaultValue={settings.adBudgetCurrency}
          maxLength={3}
          className={`${input} uppercase`}
        />
      </label>
      <label>
        <span className={label}>Mağaza saat dilimi (raporlar)</span>
        <input name="timezone" defaultValue={settings.timezone} className={input} />
      </label>
      <div className="flex items-center gap-3 sm:col-span-2">
        <Submit pending={pending}>Mağaza ayarlarını kaydet</Submit>
        <Status state={state} pending={pending} />
      </div>
    </form>
  );
}

const PROFIT_FIELDS: Array<{ name: keyof ProfitRulesDto; text: string; hint: string }> = [
  { name: 'targetContribution', text: 'Hedef katkı / sipariş', hint: 'Varsayılan 10' },
  { name: 'excellentThreshold', text: '“Çok iyi” eşiği (≥)', hint: 'Varsayılan 15' },
  { name: 'publishThreshold', text: '“Yayınlanabilir” eşiği (≥)', hint: 'Varsayılan 10' },
  { name: 'reviewThreshold', text: '“Onay bekler” eşiği (≥)', hint: 'Varsayılan 7' },
  {
    name: 'minThreshold',
    text: '“Önerilmez” alt sınırı (≥)',
    hint: 'Altı: reddedilir. Varsayılan 0',
  },
  {
    name: 'defaultAdCostPerOrder',
    text: 'Sipariş başı reklam payı (tahmin)',
    hint: 'Gerçek harcama ayrıca izlenir',
  },
  {
    name: 'otherVariableCostFixed',
    text: 'Diğer sabit değişken gider / sipariş',
    hint: 'Ambalaj vb.',
  },
  { name: 'returnReserveRate', text: 'İade rezervi oranı', hint: '0.03 = %3' },
  { name: 'remakeReserveRate', text: 'Yeniden üretim rezervi oranı', hint: '0.01 = %1' },
  { name: 'otherVariableCostRate', text: 'Diğer değişken gider oranı', hint: 'Ciroya oran' },
  {
    name: 'taxRateOnProfit',
    text: 'Vergi sonrası tahmin oranı',
    hint: 'Vergi öncesi katkıdan ayrı gösterilir',
  },
];

export function ProfitRulesForm({ rules }: { rules: ProfitRulesDto }) {
  const [state, action, pending] = useActionState<FormState, FormData>(updateProfitRulesAction, {});
  return (
    <form action={action} className="space-y-4" aria-label="Kâr politikası">
      <input type="hidden" name="storeId" value={rules.storeId} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {PROFIT_FIELDS.map((f) => (
          <label key={f.name}>
            <span className={label}>
              {f.text}
              {!f.name.toLowerCase().includes('rate') && (
                <span className="font-normal text-slate-400"> ({rules.currency})</span>
              )}
            </span>
            <input
              name={f.name}
              defaultValue={rules[f.name]}
              inputMode="decimal"
              className={input}
            />
            <span className="mt-1 block text-xs text-slate-500">{f.hint}</span>
          </label>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <Submit pending={pending}>Kâr politikasını kaydet</Submit>
        <Status state={state} pending={pending} />
      </div>
    </form>
  );
}
