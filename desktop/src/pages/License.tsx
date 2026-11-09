import { type FormEvent, useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import type { LicenseStatusResponse } from "../api/types.gen";
import { Badge, Card, Confirm, ErrorBox, Field } from "../components/ui";
import { time } from "../lib/format";

const STATE_LABELS: Record<LicenseStatusResponse["state"], string> = {
  not_configured: "Yapılandırılmadı",
  unlicensed: "Etkin değil",
  active: "Etkin",
  offline_grace: "Çevrim dışı (tolerans)",
  lease_expired: "Yenileme gerekli",
  license_expired: "Süresi doldu",
  revoked: "Geçersiz",
  clock_error: "Saat hatası",
};

function tone(state: LicenseStatusResponse["state"]): "ok" | "warn" | "bad" | "neutral" {
  if (state === "active") return "ok";
  if (state === "offline_grace") return "warn";
  if (state === "not_configured" || state === "unlicensed") return "neutral";
  return "bad";
}

/** Lisans anahtarını yazarken biçimlendirir: ATI-XXXX-XXXX-XXXX-XXXX. */
export function formatKeyInput(raw: string): string {
  let body = raw.toUpperCase().replace(/[^0-9A-Z]/g, "");
  if (body.startsWith("ATI")) body = body.slice(3);
  body = body.slice(0, 16);
  const groups = body.match(/.{1,4}/g) ?? [];
  return groups.length ? `ATI-${groups.join("-")}` : "";
}

/** Lisans durumu, etkinleştirme ve bilgisayar değişikliği (Ayarlar ekranının bir bölümü). */
export function LicenseSection() {
  const status = usePoll((c) => c.get<LicenseStatusResponse>("/v1/license"), 10_000);
  const [key, setKey] = useState("");
  const [confirmRelease, setConfirmRelease] = useState(false);
  const activate = useAction((c, value: string) => c.post<LicenseStatusResponse>("/v1/license/activate", { key: value }));
  const refresh = useAction((c) => c.post<LicenseStatusResponse>("/v1/license/refresh"));
  const release = useAction((c) => c.post<LicenseStatusResponse>("/v1/license/deactivate"));
  const s = status.data;

  async function onActivate(event: FormEvent) {
    event.preventDefault();
    const result = await activate.execute(key);
    if (result) {
      setKey("");
      await status.refresh();
    }
  }

  return (
    <Card title="Lisans" testId="license">
      <ErrorBox error={status.error} what="Lisans durumu" />
      {s && (
        <div className="stack">
          <div className="row">
            <Badge tone={tone(s.state)} testId="license-state">
              {STATE_LABELS[s.state]}
            </Badge>
            <span data-testid="license-message">{s.message}</span>
          </div>
          {s.valid && (
            <dl className="kv" data-testid="license-details">
              <dt>Paket</dt>
              <dd>{s.plan_name}</dd>
              <dt>Anahtar</dt>
              <dd>
                <code>{s.key_hint}</code>
              </dd>
              <dt>Lisans bitişi</dt>
              <dd>{s.license_expires_at ? time(s.license_expires_at) : "Süresiz"}</dd>
              <dt>Telefon sınırı</dt>
              <dd>{s.companion_device_limit ?? "—"}</dd>
              <dt>Son yenileme</dt>
              <dd>{time(s.last_renewed_at)}</dd>
              <dt>Çevrim dışı çalışma sınırı</dt>
              <dd>{time(s.offline_until)}</dd>
            </dl>
          )}
          {s.last_error && s.valid && <div className="notice">{s.last_error}</div>}
          {!s.configured && (
            <div className="notice">
              Lisans sunucusu ({s.server_url}) henüz yayında değil. Bu sürümde lisans gerekmez; sunucu yayına alındığında
              (G5) etkinleştirme açılacak.
            </div>
          )}
          {s.configured && !s.valid && (
            <form className="row" onSubmit={onActivate} data-testid="license-form">
              <Field label="Lisans anahtarı" hint="Satın alma e-postanızda veya müşteri panelinde bulunur.">
                <input
                  value={key}
                  onChange={(e) => setKey(formatKeyInput(e.target.value))}
                  placeholder="ATI-XXXX-XXXX-XXXX-XXXX"
                  autoComplete="off"
                  spellCheck={false}
                  data-testid="license-key"
                />
              </Field>
              <button className="primary" type="submit" disabled={activate.pending || key.length < 23}>
                {activate.pending ? "Etkinleştiriliyor…" : "Etkinleştir"}
              </button>
            </form>
          )}
          {s.valid && (
            <div className="row">
              <button
                disabled={refresh.pending}
                onClick={async () => {
                  await refresh.execute();
                  await status.refresh();
                }}
              >
                Şimdi yenile
              </button>
              <button className="danger" onClick={() => setConfirmRelease(true)} data-testid="license-release">
                Bu bilgisayarı lisanstan çıkar
              </button>
            </div>
          )}
          <ErrorBox error={activate.error ?? refresh.error ?? release.error} />
          <p className="muted small">
            Lisans, bu bilgisayara bağlı ve imzalı bir "kira" ile doğrulanır; kira birkaç saatte bir yenilenir ve internet
            yokken 72 saate kadar geçerli kalır. Lisans geçersizken yeni işlem açılmaz; açık pozisyonlar ve stoplar
            yönetilmeye devam eder.{s.enforced ? "" : " Bu sürümde lisans işlemleri engellemez."}
          </p>
        </div>
      )}
      <Confirm
        open={confirmRelease}
        title="Bilgisayarı lisanstan çıkar"
        confirmLabel="Lisanstan çıkar"
        danger
        onCancel={() => setConfirmRelease(false)}
        onConfirm={async () => {
          setConfirmRelease(false);
          await release.execute();
          await status.refresh();
        }}
      >
        Bu bilgisayar lisanstan çıkarılır ve lisansı başka bir bilgisayarda etkinleştirebilirsiniz. Bu bilgisayarda
        tekrar kullanmak için anahtarı yeniden girmeniz gerekir.
      </Confirm>
    </Card>
  );
}
