"use client";

import { Laptop, Smartphone } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { ErrorBox } from "@/components/auth/ErrorBox";
import { formValue, useSubmit } from "@/components/auth/useSubmit";
import { Button, Card, Field, Notice } from "@/components/ui";
import type { License, Message } from "@/lib/api";
import { formatDate, licenseStatusLabel } from "@/lib/format";

/** Panelde tek lisans: durum, anahtar (parola ile gösterme), bilgisayarlar ve kaldırma. */
export function LicenseCard({ license, onChanged }: { license: License; onChanged: () => void }) {
  const api = useApi();
  const reveal = useSubmit();
  const removal = useSubmit();
  const [askPassword, setAskPassword] = useState(false);
  const [key, setKey] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const titleId = `lisans-${license.id}`;

  function onReveal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    void reveal.run(async () => {
      const result = await api.post<{ key: string }>(`/v1/me/licenses/${license.id}/reveal`, {
        password: formValue(form, "password"),
      });
      setKey(result.key);
      setAskPassword(false);
    });
  }

  function remove(deviceId: string) {
    void removal.run(async () => {
      const result = await api.post<Message>(`/v1/me/licenses/${license.id}/devices/${deviceId}/deactivate`);
      setConfirming(null);
      onChanged();
      return result.message ?? "Bilgisayar kaldırıldı.";
    });
  }

  return (
    <Card as="article" className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id={titleId} className="text-lg font-semibold text-fg">
            {license.plan_name}
          </h3>
          <p className="mt-1 text-sm text-muted">
            {licenseStatusLabel(license.status)} ·{" "}
            {license.expires_at
              ? `Bitiş: ${formatDate(license.expires_at)}`
              : license.activated_at
                ? "Süresiz"
                : "Süre ilk etkinleştirmede başlar"}
          </p>
        </div>
        <span className="rounded-full border border-border px-3 py-1 text-sm text-fg" data-testid="device-usage">
          {license.active_devices} / {license.device_limit} bilgisayar
        </span>
      </div>

      <div>
        <p className="text-sm font-medium text-fg">Lisans anahtarı</p>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <code className="rounded-lg bg-surface-2 px-3 py-1.5 font-mono text-sm text-fg" data-testid="license-key">
            {key ?? license.key_hint}
          </code>
          {key ? (
            <Button variant="ghost" onClick={() => void navigator.clipboard?.writeText(key)}>
              Kopyala
            </Button>
          ) : (
            <Button variant="secondary" onClick={() => setAskPassword(true)} aria-expanded={askPassword}>
              Anahtarı göster
            </Button>
          )}
        </div>
        {askPassword && !key ? (
          <form onSubmit={onReveal} className="mt-3 flex flex-wrap items-end gap-3">
            <div className="min-w-60 flex-1">
              <Field
                id={`parola-${license.id}`}
                name="password"
                type="password"
                label="Güvenliğiniz için parolanızı girin"
                autoComplete="current-password"
                required
              />
            </div>
            <Button type="submit" disabled={reveal.pending}>
              {reveal.pending ? "Doğrulanıyor…" : "Göster"}
            </Button>
          </form>
        ) : null}
        <div className="mt-2">
          <ErrorBox error={reveal.error} />
        </div>
      </div>

      <section aria-labelledby={`${titleId}-cihazlar`}>
        <h4 id={`${titleId}-cihazlar`} className="text-sm font-medium text-fg">
          Bilgisayarlar
        </h4>
        {license.devices.length === 0 ? (
          <p className="mt-2 text-sm text-muted">
            Henüz etkinleştirilmedi. Windows uygulamasında Ayarlar &gt; Lisans bölümüne anahtarınızı girin.
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-border rounded-xl border border-border">
            {license.devices.map((device) => (
              <li key={device.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="flex items-center gap-3">
                  {device.platform === "ios" ? (
                    <Smartphone aria-hidden="true" className="h-5 w-5 text-muted" />
                  ) : (
                    <Laptop aria-hidden="true" className="h-5 w-5 text-muted" />
                  )}
                  <div>
                    <p className="font-medium text-fg">{device.name}</p>
                    <p className="text-xs text-muted">Son görülme: {formatDate(device.last_seen_at)}</p>
                  </div>
                </div>
                {confirming === device.id ? (
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-fg">Kaldırılsın mı?</span>
                    <Button variant="secondary" onClick={() => setConfirming(null)}>
                      Vazgeç
                    </Button>
                    <Button onClick={() => remove(device.id)} disabled={removal.pending}>
                      Evet, kaldır
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="secondary"
                    onClick={() => setConfirming(device.id)}
                    disabled={license.device_resets_left <= 0}
                    aria-label={`${device.name} bilgisayarını kaldır`}
                  >
                    Kaldır
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted" data-testid="resets-left">
          Son 30 günde kalan bilgisayar kaldırma hakkı: {license.device_resets_left}
        </p>
        {removal.done ? (
          <div className="mt-2">
            <Notice tone="success" role="status">
              {removal.done}
            </Notice>
          </div>
        ) : null}
        <div className="mt-2">
          <ErrorBox error={removal.error} />
        </div>
      </section>
    </Card>
  );
}
