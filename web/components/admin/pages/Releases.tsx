"use client";

import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { AdminPage, Feedback, Table, TotpInput, cell, inputClass, smallButton, useAdminAction, useAdminQuery, StatusPill } from "@/components/admin/kit";
import { dateTime } from "@/lib/admin";
import { formatSize } from "@/lib/releases";

interface AdminRelease {
  id: string;
  platform: "windows" | "ios";
  version: string;
  download_url: string;
  sha256: string | null;
  size_bytes: number | null;
  min_os: string;
  notes: string;
  signed: boolean;
  updatable: boolean;
  status: "draft" | "published" | "withdrawn";
  published_at: string | null;
  withdrawn_at: string | null;
  created_at: string;
}

const STATUS: Record<AdminRelease["status"], string> = {
  draft: "Taslak",
  published: "Yayında",
  withdrawn: "Geri çekildi",
};
const PLATFORM: Record<AdminRelease["platform"], string> = { windows: "Windows", ios: "iPhone" };

function text(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function NewRelease({ onCreated }: { onCreated: () => void }) {
  const api = useApi();
  const action = useAdminAction();
  const [platform, setPlatform] = useState<AdminRelease["platform"]>("windows");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const size = text(data, "size_bytes");
    const body: Record<string, unknown> = {
      platform,
      version: text(data, "version"),
      download_url: text(data, "download_url"),
      min_os: text(data, "min_os"),
      notes: text(data, "notes"),
      signed: data.get("signed") === "on",
    };
    if (platform === "windows") {
      body.sha256 = text(data, "sha256");
      body.size_bytes = size === "" ? null : Number(size);
      const signature = text(data, "update_signature");
      if (signature) body.update_signature = signature;
    }
    const ok = await action.run(() => api.post("/admin/v1/releases", body), "Taslak eklendi. Bilgileri kontrol edip yayınlayın.");
    if (ok) {
      form.reset();
      onCreated();
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-4 rounded-xl border border-border bg-surface p-5" aria-labelledby="yeni-surum">
      <h2 id="yeni-surum" className="text-lg font-semibold text-fg">
        Yeni sürüm (taslak)
      </h2>
      <div className="grid gap-4 md:grid-cols-3">
        <label htmlFor="surum-platform" className="block text-sm font-medium text-fg">
          Platform
          <select id="surum-platform" value={platform} onChange={(e) => setPlatform(e.target.value as AdminRelease["platform"])} className={`mt-1 ${inputClass}`}>
            <option value="windows">Windows (kurulum paketi)</option>
            <option value="ios">iPhone (App Store / TestFlight)</option>
          </select>
        </label>
        <label htmlFor="surum-no" className="block text-sm font-medium text-fg">
          Sürüm numarası
          <input id="surum-no" name="version" required placeholder="1.0.0" pattern="\d{1,4}\.\d{1,4}\.\d{1,6}(-[0-9A-Za-z.]{1,20})?" className={`mt-1 ${inputClass}`} />
        </label>
        <label htmlFor="surum-os" className="block text-sm font-medium text-fg">
          En düşük sistem
          <input id="surum-os" name="min_os" placeholder={platform === "windows" ? "Windows 10 (64 bit)" : "iOS 17"} className={`mt-1 ${inputClass}`} />
        </label>
      </div>
      <label htmlFor="surum-adres" className="block text-sm font-medium text-fg">
        {platform === "windows" ? "İndirme adresi (https://indir.canarslan.net.tr/…-setup.exe)" : "App Store veya TestFlight adresi"}
        <input id="surum-adres" name="download_url" type="url" required className={`mt-1 ${inputClass}`} />
      </label>
      {platform === "windows" ? (
        <div className="grid gap-4 md:grid-cols-[2fr_1fr]">
          <label htmlFor="surum-ozet" className="block text-sm font-medium text-fg">
            SHA-256 özeti (derleme çıktısındaki .sha256 dosyası)
            <input id="surum-ozet" name="sha256" required pattern="[0-9a-fA-F]{64}" className={`mt-1 ${inputClass} font-mono`} />
          </label>
          <label htmlFor="surum-boyut" className="block text-sm font-medium text-fg">
            Boyut (bayt)
            <input id="surum-boyut" name="size_bytes" required inputMode="numeric" pattern="\d+" className={`mt-1 ${inputClass}`} />
          </label>
        </div>
      ) : null}
      {platform === "windows" ? (
        <label htmlFor="surum-imza" className="block text-sm font-medium text-fg">
          Güncelleme imzası (isteğe bağlı; yonet.ps1 surum-hazirla çıktısı). Girilirse kurulu uygulamalar bu sürüme
          kendiliğinden güncellenir.
          <textarea id="surum-imza" name="update_signature" rows={2} maxLength={4000} spellCheck={false} className={`mt-1 ${inputClass} font-mono text-xs`} />
        </label>
      ) : null}
      <label htmlFor="surum-notlar" className="block text-sm font-medium text-fg">
        Sürüm notları (sitede gösterilir)
        <textarea id="surum-notlar" name="notes" rows={3} maxLength={4000} className={`mt-1 ${inputClass}`} />
      </label>
      {platform === "windows" ? (
        <label className="flex items-center gap-2 text-sm text-fg">
          <input type="checkbox" name="signed" className="h-4 w-4" />
          Kurulum paketi kod imzalı (imza sertifikası G6 onayıyla alınır)
        </label>
      ) : null}
      <button type="submit" className={smallButton} disabled={action.pending}>
        Taslak ekle
      </button>
      <Feedback error={action.error} message={action.message} />
    </form>
  );
}

function ReleaseRow({ release, onChanged }: { release: AdminRelease; onChanged: () => void }) {
  const api = useApi();
  const action = useAdminAction();
  const label = `${PLATFORM[release.platform]} ${release.version}`;

  async function publish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = new FormData(event.currentTarget).get("code");
    const ok = await action.run(() => api.post(`/admin/v1/releases/${release.id}/publish`, { code }), "Yayınlandı");
    if (ok) onChanged();
  }

  async function withdraw(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reason = new FormData(event.currentTarget).get("reason");
    const ok = await action.run(() => api.post(`/admin/v1/releases/${release.id}/withdraw`, { reason }), "Geri çekildi");
    if (ok) onChanged();
  }

  return (
    <tr data-testid={`release-${release.platform}-${release.version}`}>
      <td className={cell}>
        <p className="font-medium">{label}</p>
        <p className="text-xs text-muted">{release.signed ? "Kod imzalı" : release.platform === "windows" ? "İmzasız" : ""}</p>
        {release.platform === "windows" ? (
          <p className="text-xs text-muted" data-testid="release-updatable">
            {release.updatable ? "Otomatik güncelleme: açık" : "Otomatik güncelleme: yok (imza girilmedi)"}
          </p>
        ) : null}
      </td>
      <td className={cell}>
        <a href={release.download_url} className="break-all text-link underline underline-offset-2" rel="noopener">
          {release.download_url}
        </a>
        {release.sha256 ? <p className="mt-1 break-all font-mono text-xs text-muted">{release.sha256}</p> : null}
        {release.size_bytes ? <p className="text-xs text-muted">{formatSize(release.size_bytes)}</p> : null}
      </td>
      <td className={cell}>
        <StatusPill testId="release-status" tone={release.status === "published" ? "success" : release.status === "withdrawn" ? "neutral" : "warn"}>
          {STATUS[release.status]}
        </StatusPill>
        <p className="text-xs text-muted">{dateTime(release.published_at ?? release.created_at)}</p>
      </td>
      <td className={cell}>
        <div className="space-y-3">
          {release.status !== "published" ? (
            <form onSubmit={(e) => void publish(e)} className="space-y-2">
              <TotpInput id={`yayin-kod-${release.id}`} />
              <button type="submit" className={smallButton} disabled={action.pending} aria-label={`${label} yayınla`}>
                Yayınla
              </button>
            </form>
          ) : null}
          {release.status !== "withdrawn" ? (
            <form onSubmit={(e) => void withdraw(e)} className="space-y-2">
              <label htmlFor={`geri-neden-${release.id}`} className="block text-sm font-medium text-fg">
                Geri çekme nedeni
                <input id={`geri-neden-${release.id}`} name="reason" required minLength={3} maxLength={300} className={`mt-1 ${inputClass}`} />
              </label>
              <button type="submit" className={smallButton} disabled={action.pending} aria-label={`${label} geri çek`}>
                Geri çek
              </button>
            </form>
          ) : null}
          <Feedback error={action.error} message={action.message} />
        </div>
      </td>
    </tr>
  );
}

export function Releases() {
  const releases = useAdminQuery<AdminRelease[]>("/admin/v1/releases");
  return (
    <AdminPage
      title="Sürümler (indirme)"
      lead="Sitenin İndir sayfası her platformun yayındaki en son sürümünü gösterir. Yayınlamak doğrulama kodu ister. Yayınlanan sürümün adresi ve SHA-256 özeti değiştirilemez; hatalıysa geri çekip yeni sürüm ekleyin."
    >
      <NewRelease onCreated={releases.reload} />
      <Feedback error={releases.error} />
      {releases.data ? (
        releases.data.length === 0 ? (
          <p className="text-sm text-muted">Henüz sürüm eklenmedi.</p>
        ) : (
          <Table caption="Uygulama sürümleri" head={["Sürüm", "Dosya", "Durum", "İşlem"]}>
            {releases.data.map((release) => (
              <ReleaseRow key={release.id} release={release} onChanged={releases.reload} />
            ))}
          </Table>
        )
      ) : null}
    </AdminPage>
  );
}
