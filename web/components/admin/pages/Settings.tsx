"use client";

import { useEffect, useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { useAdmin } from "@/components/admin/AdminSession";
import { AdminPage, Feedback, TotpInput, inputClass, useAdminAction, useAdminQuery } from "@/components/admin/kit";
import { Button, Card, Notice } from "@/components/ui";
import { can, dateTime } from "@/lib/admin";

interface PaymentView {
  provider: string;
  mode: "test" | "live";
  public: Record<string, string>;
  secrets: Record<string, { configured: boolean; hint: string | null; updated_at: string | null }>;
  live_allowed: boolean;
  providers: Record<string, { public: string[]; secrets: string[] }>;
}

const PROVIDER_LABELS: Record<string, string> = {
  none: "Seçilmedi",
  iyzico: "iyzico",
  paytr: "PayTR",
  stripe: "Stripe",
  paddle: "Paddle",
  lemon_squeezy: "Lemon Squeezy",
};
const COMPANY_FIELDS: [string, string][] = [
  ["legal_name", "Ticaret unvanı"],
  ["address", "Adres"],
  ["tax_office", "Vergi dairesi"],
  ["tax_number", "Vergi kimlik no (10-11 hane)"],
  ["mersis", "MERSİS no (16 hane)"],
  ["kep", "KEP adresi"],
  ["email", "E-posta"],
  ["phone", "Telefon"],
];

function PaymentSettings() {
  const api = useApi();
  const view = useAdminQuery<PaymentView>("/admin/v1/settings/payment");
  const action = useAdminAction();
  const [provider, setProvider] = useState("none");
  const [mode, setMode] = useState<"test" | "live">("test");

  useEffect(() => {
    if (view.data) {
      setProvider(view.data.provider);
      setMode(view.data.mode);
    }
  }, [view.data]);

  if (!view.data) return <Feedback error={view.error} />;
  const spec = view.data.providers[provider] ?? { public: [], secrets: [] };

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const pub: Record<string, string> = {};
    for (const name of spec.public) pub[name] = String(data.get(`public.${name}`) ?? "");
    const secrets: Record<string, string> = {};
    for (const name of spec.secrets) {
      const value = String(data.get(`secret.${name}`) ?? "").trim();
      if (value) secrets[name] = value;
    }
    const code = String(data.get("code") ?? "").trim();
    const result = await action.run(
      () =>
        api.put<PaymentView>("/admin/v1/settings/payment", {
          provider,
          mode,
          public: pub,
          secrets,
          code: code || null,
          confirm: String(data.get("confirm") ?? "") || null,
        }),
      "Ödeme ayarları kaydedildi",
    );
    if (result) view.reload();
  }

  return (
    <Card as="section" className="space-y-4">
      <h2 className="text-lg font-semibold text-fg">Ödeme</h2>
      <p className="text-sm text-muted">
        Anahtarlar şifreli saklanır ve bir daha görüntülenemez (yalnızca son 4 karakter). Anahtar girmek, değiştirmek ve
        canlı moda geçmek için doğrulama uygulamanızdaki güncel kod istenir.
      </p>
      {!view.data.live_allowed ? (
        <Notice tone="warning" title="Canlı ödeme kapalı" role="note">
          Bu kurulumda gerçek ödeme alınamaz. Açılması işletme sahibinin açık onayına (G3) ve dağıtım ayarına
          bağlıdır; o zamana kadar yalnızca sağlayıcının test ortamı kullanılabilir.
        </Notice>
      ) : null}
      <form onSubmit={(e) => void save(e)} className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm text-fg">
            Sağlayıcı
            <select value={provider} onChange={(e) => setProvider(e.target.value)} className={`mt-1 ${inputClass}`}>
              {Object.keys(view.data.providers).map((p) => <option key={p} value={p}>{PROVIDER_LABELS[p] ?? p}</option>)}
            </select>
          </label>
          <label className="text-sm text-fg">
            Mod
            <select value={mode} onChange={(e) => setMode(e.target.value as "test" | "live")} className={`mt-1 ${inputClass}`}>
              <option value="test">Test (sandbox)</option>
              <option value="live" disabled={!view.data.live_allowed}>Canlı</option>
            </select>
          </label>
        </div>
        {spec.public.map((name) => (
          <label key={name} className="block text-sm text-fg">
            {name}
            <input name={`public.${name}`} defaultValue={provider === view.data?.provider ? view.data.public[name] ?? "" : ""} className={`mt-1 ${inputClass}`} />
          </label>
        ))}
        {spec.secrets.map((name) => {
          const info = provider === view.data?.provider ? view.data.secrets[name] : undefined;
          return (
            <label key={name} className="block text-sm text-fg">
              {name} {info?.configured ? <span className="text-muted">(tanımlı {info.hint}, {dateTime(info.updated_at)} — değiştirmek için yeni değer girin)</span> : <span className="text-muted">(tanımlı değil)</span>}
              <input name={`secret.${name}`} type="password" autoComplete="off" className={`mt-1 ${inputClass}`} />
            </label>
          );
        })}
        {mode === "live" ? (
          <label className="block text-sm text-fg">
            Onay için <strong>CANLI ÖDEMEYİ AÇ</strong> yazın
            <input name="confirm" className={`mt-1 ${inputClass}`} />
          </label>
        ) : null}
        <TotpInput id="odeme-kod" label="Doğrulama kodu (anahtar değişikliği veya canlı mod için)" required={false} />
        <Feedback error={action.error} message={action.message} />
        <Button type="submit" disabled={action.pending}>Kaydet</Button>
      </form>
    </Card>
  );
}

function CompanySettings() {
  const api = useApi();
  const company = useAdminQuery<Record<string, string>>("/admin/v1/settings/company");
  const action = useAdminAction();
  if (!company.data) return <Feedback error={company.error} />;
  return (
    <Card as="section" className="space-y-4">
      <h2 className="text-lg font-semibold text-fg">Şirket ve fatura bilgileri</h2>
      <p className="text-sm text-muted">Yasal metinlerde ve faturalarda kullanılır.</p>
      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          const body = Object.fromEntries(COMPANY_FIELDS.map(([k]) => [k, String(data.get(k) ?? "").trim()]));
          void action.run(() => api.put("/admin/v1/settings/company", body), "Şirket bilgileri kaydedildi");
        }}
      >
        {COMPANY_FIELDS.map(([key, label]) => (
          <label key={key} className="text-sm text-fg">
            {label}
            <input name={key} defaultValue={company.data?.[key] ?? ""} className={`mt-1 ${inputClass}`} />
          </label>
        ))}
        <div className="sm:col-span-2">
          <Feedback error={action.error} message={action.message} />
          <Button type="submit" className="mt-2" disabled={action.pending}>Kaydet</Button>
        </div>
      </form>
    </Card>
  );
}

function RecoveryCodes() {
  const api = useApi();
  const { me, reload } = useAdmin();
  const action = useAdminAction();
  const [codes, setCodes] = useState<string[] | null>(null);
  return (
    <Card as="section" className="space-y-3">
      <h2 className="text-lg font-semibold text-fg">Kurtarma kodları</h2>
      <p className="text-sm text-muted">Kalan kod: {me?.recovery_codes_left ?? "—"}. Yeni kod üretmek eski kodları geçersiz kılar.</p>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          const code = new FormData(e.currentTarget).get("code");
          void action.run(async () => {
            const r = await api.post<{ recovery_codes: string[] }>("/admin/v1/auth/recovery-codes", { code });
            setCodes(r.recovery_codes);
            reload();
          });
        }}
      >
        <TotpInput id="kurtarma-kod" />
        <Button type="submit" variant="secondary">Yeni kodlar üret</Button>
      </form>
      <Feedback error={action.error} />
      {codes ? (
        <ul className="grid max-w-md grid-cols-2 gap-2 font-mono text-sm">
          {codes.map((c) => <li key={c} className="rounded bg-surface-2 px-3 py-1.5 text-center text-fg">{c}</li>)}
        </ul>
      ) : null}
    </Card>
  );
}

export function Settings() {
  const { me } = useAdmin();
  return (
    <AdminPage title="Ayarlar">
      {can(me, "settings.manage") ? (
        <>
          <PaymentSettings />
          <CompanySettings />
        </>
      ) : null}
      <RecoveryCodes />
    </AdminPage>
  );
}
