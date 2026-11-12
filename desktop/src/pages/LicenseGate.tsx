import { KeyRound, OctagonX, RefreshCw, ShieldCheck } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useAction } from "../api/hooks";
import type { LicenseStatusResponse } from "../api/types.gen";
import { Confirm, ErrorBox } from "../components/ui";
import { formatKeyInput } from "./License";
import { LogoMark, Wordmark } from "../components/Logo";

const TITLES: Partial<Record<LicenseStatusResponse["state"], string>> = {
  unlicensed: "Lisansınızı etkinleştirin",
  license_expired: "Lisansınızın süresi doldu",
  lease_expired: "Lisansı yenilemek gerekiyor",
  clock_error: "Bilgisayar saati hatalı",
  revoked: "Lisans bu bilgisayarda geçersiz",
};

/**
 * Lisans kapısı: lisans zorunluyken (kurulum paketinde her zaman) geçerli lisans yoksa uygulamanın
 * yerine bu ekran açılır. Asıl kapı motordadır (lisanssız yeni işlem açılmaz); bu ekran arayüzü
 * kapatır. Güvenlik için acil durdurma burada da kullanılabilir; açık pozisyonların borsadaki
 * stopları motor tarafından yönetilmeye devam eder.
 */
export function LicenseGate({ status, onChange }: { status: LicenseStatusResponse; onChange: () => Promise<void> }) {
  const [key, setKey] = useState("");
  const [askStop, setAskStop] = useState(false);
  const activate = useAction((c, value: string) => c.post<LicenseStatusResponse>("/v1/license/activate", { key: value }));
  const refresh = useAction((c) => c.post<LicenseStatusResponse>("/v1/license/refresh"));
  const stop = useAction((c) => c.post("/v1/kill-switch/engage", { reason: "Lisans ekranından acil durdurma" }));
  const [stopped, setStopped] = useState(false);
  const canRefresh = status.state !== "unlicensed" && status.state !== "not_configured";

  async function onActivate(event: FormEvent) {
    event.preventDefault();
    if (await activate.execute(key)) {
      setKey("");
      await onChange();
    }
  }

  return (
    <div className="gate" data-testid="license-gate">
      <div className="gate-card">
        <div className="gate-brand">
          <LogoMark size={48} />
          <Wordmark large />
        </div>
        <span className="gate-icon" aria-hidden="true">
          <KeyRound />
        </span>
        <h1>{TITLES[status.state] ?? "Lisans gerekli"}</h1>
        <p className="gate-lead" data-testid="license-gate-message">
          {status.message}
        </p>

        <form className="gate-form" onSubmit={onActivate}>
          <label className="field">
            <span>Lisans anahtarı</span>
            <input
              value={key}
              onChange={(e) => setKey(formatKeyInput(e.target.value))}
              placeholder="ATI-XXXX-XXXX-XXXX-XXXX"
              autoComplete="off"
              spellCheck={false}
              autoFocus
              data-testid="license-gate-key"
            />
          </label>
          <button className="primary big" type="submit" disabled={activate.pending || key.length < 23} data-testid="license-gate-activate">
            {activate.pending ? "Etkinleştiriliyor…" : "Etkinleştir"}
          </button>
        </form>
        {canRefresh && (
          <button
            type="button"
            disabled={refresh.pending}
            onClick={async () => {
              await refresh.execute();
              await onChange();
            }}
          >
            <RefreshCw aria-hidden="true" size={16} /> Lisansı şimdi yenile
          </button>
        )}
        <ErrorBox error={activate.error ?? refresh.error ?? stop.error} />

        <ul className="gate-help">
          <li>
            Anahtarınız satın almadan sonra <b>canarslan.net.tr/panel</b> adresindeki müşteri panelinizde görünür.
          </li>
          <li>
            Paket satın almak için: <b>canarslan.net.tr/paketler</b>
          </li>
          <li>Lisans bu bilgisayara bağlanır; başka bilgisayara geçmek için önce buradan çıkarabilirsiniz.</li>
        </ul>

        <div className="gate-safety">
          <ShieldCheck aria-hidden="true" size={18} />
          <span>
            Lisans yokken yeni işlem açılmaz. Açık pozisyonlarınızın borsadaki stopları korunur.
            {stopped ? " Acil durdurma devrede." : ""}
          </span>
          <button type="button" className="danger" onClick={() => setAskStop(true)} disabled={stopped} data-testid="license-gate-stop">
            <OctagonX aria-hidden="true" size={16} /> Acil durdur
          </button>
        </div>
      </div>
      <Confirm
        open={askStop}
        title="Acil durdurma"
        confirmLabel="Acil durdur"
        danger
        onCancel={() => setAskStop(false)}
        onConfirm={async () => {
          setAskStop(false);
          if ((await stop.execute()) !== undefined) setStopped(true);
        }}
      >
        Motor tüm yeni işlemleri hemen durdurur. Açık pozisyonların borsadaki stopları yerinde kalır.
      </Confirm>
    </div>
  );
}
