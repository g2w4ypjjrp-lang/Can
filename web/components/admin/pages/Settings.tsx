"use client";

import { useEffect, useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { useAdmin } from "@/components/admin/AdminSession";
import { AdminPage, Feedback, TotpInput, inputClass, useAdminAction, useAdminQuery } from "@/components/admin/kit";
import { Button, Card, Notice } from "@/components/ui";
import { can, dateTime } from "@/lib/admin";
import { DESIGN_LABELS, DESIGNS, type Design } from "@/lib/design";

interface PaymentView {
  provider: string;
  mode: "test" | "live";
  public: Record<string, string>;
  secrets: Record<string, { configured: boolean; hint: string | null; updated_at: string | null }>;
  live_allowed: boolean;
  providers: Record<string, { public: string[]; secrets: string[] }>;
  webhook_urls?: Record<string, string>;
}

const PROVIDER_LABELS: Record<string, string> = {
  none: "Seçilmedi",
  paytr: "PayTR",
  iyzico: "iyzico",
  lemonsqueezy: "Lemon Squeezy (satıcı adına satış, vergi levhası gerekmez)",
  simulator: "Test simülatörü (gerçek tahsilat yok)",
};
// Alan adlarının açıklamaları (sağlayıcı panelinde nerede bulunduğu).
const FIELD_LABELS: Record<string, string> = {
  merchant_id: "Mağaza no (merchant_id)",
  merchant_key: "Mağaza anahtarı (merchant_key)",
  merchant_salt: "Mağaza gizli tuzu (merchant_salt)",
  api_key: "API anahtarı",
  secret_key: "Gizli anahtar",
  store_id: "Mağaza numarası (Settings → Stores, yalnızca rakam)",
  variant_id: "Ürün varyant numarası (Products → ürün → varyant, yalnızca rakam)",
  signing_secret: "Webhook imza sırrı (Settings → Webhooks → Signing secret)",
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
            {FIELD_LABELS[name] ?? name}
            <input name={`public.${name}`} defaultValue={provider === view.data?.provider ? view.data.public[name] ?? "" : ""} className={`mt-1 ${inputClass}`} />
          </label>
        ))}
        {spec.secrets.map((name) => {
          const info = provider === view.data?.provider ? view.data.secrets[name] : undefined;
          return (
            <label key={name} className="block text-sm text-fg">
              {FIELD_LABELS[name] ?? name} {info?.configured ? <span className="text-muted">(tanımlı {info.hint}, {dateTime(info.updated_at)} — değiştirmek için yeni değer girin)</span> : <span className="text-muted">(tanımlı değil)</span>}
              <input name={`secret.${name}`} type="password" autoComplete="off" className={`mt-1 ${inputClass}`} />
            </label>
          );
        })}
        {view.data.webhook_urls?.[provider] ? (
          <Notice tone="info" title="Bildirim (webhook) adresi" role="note">
            Sağlayıcının panelinde bildirim adresi olarak şunu girin:{" "}
            <code className="break-all font-mono text-xs" data-testid="webhook-url">{view.data.webhook_urls[provider]}</code>
            {provider === "lemonsqueezy" ? (
              <> Olaylardan <strong>order_created</strong> ve <strong>order_refunded</strong> seçili olsun. Mağaza para birimi paketlerin para birimiyle aynı olmalı; aksi hâlde sipariş otomatik teslim edilmez, incelemeye düşer.</>
            ) : null}
          </Notice>
        ) : null}
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

/** Site görünümü: herkese açık sayfaların (ve bu panelin) renk tasarımı. Değişiklik ~30 sn içinde
 *  sitede görünür; ziyaretçinin açık/koyu tema seçimi korunur. */
function SiteDesign() {
  const api = useApi();
  const view = useAdminQuery<{ design: Design }>("/admin/v1/settings/appearance");
  const action = useAdminAction();
  const [choice, setChoice] = useState<Design | null>(null);
  const current = choice ?? view.data?.design ?? null;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!current) return;
    const ok = await action.run(
      () => api.put("/admin/v1/settings/appearance", { design: current }),
      `Kaydedildi: ${DESIGN_LABELS[current].name}. Site yaklaşık 30 saniye içinde güncellenir.`,
    );
    if (ok) view.reload();
  }

  return (
    <Card as="section" className="space-y-4" aria-labelledby="site-gorunumu">
      <div>
        <h2 id="site-gorunumu" className="text-lg font-semibold text-fg">
          Site görünümü
        </h2>
        <p className="mt-1 text-sm text-muted">
          Sitenin renk tasarımını seçin. Her tasarım açık ve koyu temada okunabilirlik denetiminden geçer; ziyaretçinin
          açık/koyu seçimi korunur.
        </p>
      </div>
      <Feedback error={view.error} />
      <form onSubmit={(e) => void save(e)} className="space-y-4">
        <fieldset>
          <legend className="visually-hidden">Tasarım modu</legend>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {DESIGNS.map((code) => (
              <label
                key={code}
                className={`card-lift flex cursor-pointer flex-col gap-3 rounded-2xl border p-3 transition-colors ${
                  current === code ? "border-accent-text bg-surface-2 ring-2 ring-ring" : "border-border bg-surface hover:border-border-strong"
                }`}
              >
                <span aria-hidden="true" className={`swatch-${code} h-16 rounded-xl shadow-sm`} />
                <span className="flex items-start gap-2">
                  <input
                    type="radio"
                    name="design"
                    value={code}
                    checked={current === code}
                    onChange={() => setChoice(code)}
                    className="mt-1 h-4 w-4"
                    data-testid={`design-${code}`}
                  />
                  <span>
                    <span className="block text-sm font-semibold text-fg">{DESIGN_LABELS[code].name}</span>
                    <span className="block text-xs text-muted">{DESIGN_LABELS[code].hint}</span>
                  </span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <Button type="submit" disabled={action.pending || !current || current === view.data?.design} data-testid="design-save">
          Tasarımı kaydet
        </Button>
        <Feedback error={action.error} message={action.message} />
      </form>
    </Card>
  );
}

interface Announcement {
  enabled: boolean;
  text: string;
  link: string;
  tone: "info" | "success" | "warning" | "campaign";
  ends_at: string | null;
  active: boolean;
}

const TONES: [Announcement["tone"], string][] = [
  ["campaign", "Kampanya (renkli, hareketli)"],
  ["info", "Bilgi (mavi)"],
  ["success", "Müjde (yeşil)"],
  ["warning", "Uyarı (sarı)"],
];

function localInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Sitenin en üstündeki duyuru şeridi. Kampanya açıkken ve duyuru yokken şerit kampanyayı geri
 *  sayımla kendiliğinden gösterir. */
function AnnouncementSettings() {
  const api = useApi();
  const view = useAdminQuery<Announcement>("/admin/v1/settings/announcement");
  const action = useAdminAction();
  const a = view.data;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const ends = String(data.get("ends_at") ?? "");
    const ok = await action.run(
      () =>
        api.put("/admin/v1/settings/announcement", {
          enabled: data.get("enabled") === "on",
          text: String(data.get("text") ?? "").trim(),
          link: String(data.get("link") ?? "").trim(),
          tone: data.get("tone"),
          ends_at: ends ? new Date(ends).toISOString() : null,
        }),
      "Kaydedildi. Site yaklaşık 30 saniye içinde güncellenir.",
    );
    if (ok) view.reload();
  }

  return (
    <Card as="section" className="space-y-4" aria-labelledby="duyuru-seridi">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="duyuru-seridi" className="text-lg font-semibold text-fg">
            Duyuru şeridi
          </h2>
          <p className="mt-1 text-sm text-muted">
            Sitenin en üstünde ince bir şerit. Yeni sürüm, bakım, kampanya gibi duyurular için. Duyuru yokken açık bir indirim
            kampanyası varsa şerit onu geri sayımla gösterir.
          </p>
        </div>
        {a ? (
          <span
            className={`rounded-full border px-3 py-1 text-xs font-semibold ${a.active ? "border-success-border bg-success-bg text-success-fg" : "border-border bg-surface-2 text-muted"}`}
            data-testid="announcement-state"
          >
            {a.active ? "Yayında" : "Kapalı"}
          </span>
        ) : null}
      </div>
      <Feedback error={view.error} />
      {a ? (
        <form key={`${a.text}-${a.enabled}-${a.ends_at}`} onSubmit={(e) => void save(e)} className="space-y-3" data-testid="announcement-form">
          <label className="flex items-center gap-2 text-sm font-medium text-fg">
            <input type="checkbox" name="enabled" defaultChecked={a.enabled} className="h-4 w-4" /> Şeridi göster
          </label>
          <label className="block text-sm text-fg">
            Metin (en çok 160 karakter)
            <input name="text" maxLength={160} defaultValue={a.text} placeholder="Örn. Yeni sürüm 0.14.7 yayında: anlık fiyatlar" className={`mt-1 ${inputClass}`} />
          </label>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block text-sm text-fg">
              Bağlantı (isteğe bağlı)
              <input name="link" maxLength={300} defaultValue={a.link} placeholder="/indir ya da https://…" className={`mt-1 ${inputClass}`} />
            </label>
            <label className="block text-sm text-fg">
              Görünüm
              <select name="tone" defaultValue={a.tone} className={`mt-1 ${inputClass}`}>
                {TONES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm text-fg">
              Bitiş (boş: siz kapatana kadar)
              <input name="ends_at" type="datetime-local" defaultValue={localInput(a.ends_at)} className={`mt-1 ${inputClass}`} />
            </label>
          </div>
          <Button type="submit" disabled={action.pending}>
            Şeridi kaydet
          </Button>
          <Feedback error={action.error} message={action.message} />
        </form>
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
          <SiteDesign />
          <AnnouncementSettings />
        </>
      ) : null}
      <RecoveryCodes />
    </AdminPage>
  );
}
