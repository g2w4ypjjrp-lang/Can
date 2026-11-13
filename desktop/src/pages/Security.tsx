import { toDataURL } from "qrcode";
import { useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import { Badge, Card, ErrorBox } from "../components/ui";

interface TwoFactorStatus {
  enabled: boolean;
  recovery_left: number;
  protected: { key: string; label: string }[];
}

/** Ayarlar → Doğrulama: isteğe bağlı iki adımlı doğrulama. Açıkken kritik işlemler (gerçek para,
 * gerçek hesap anahtarı, acil durdurmayı kaldırma, lisansı kaldırma, telefon eşleme) kod ister. */
export function TwoFactorSection() {
  const status = usePoll((c) => c.get<TwoFactorStatus>("/v1/security/2fa"), 15000);
  const [setup, setSetup] = useState<{ secret: string; qr: string } | null>(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [saved, setSaved] = useState(false);
  const begin = useAction(async (c) => {
    const result = await c.post<{ secret: string; uri: string }>("/v1/security/2fa/setup");
    const qr = await toDataURL(result.uri, { margin: 1, width: 320, errorCorrectionLevel: "M" });
    setSetup({ secret: result.secret, qr });
  });
  const enable = useAction(async (c) => {
    const result = await c.post<{ recovery_codes: string[] }>("/v1/security/2fa/enable", { code: code.trim() });
    setRecovery(result.recovery_codes);
    setSetup(null);
    setCode("");
    await status.refresh();
  });
  const disable = useAction(async (c) => {
    await c.post("/v1/security/2fa/disable");
    await status.refresh();
  });
  const s = status.data;

  return (
    <Card
      title="Doğrulama (iki adımlı)"
      testId="two-factor"
      actions={s ? <Badge tone={s.enabled ? "ok" : "neutral"}>{s.enabled ? "Açık" : "Kapalı"}</Badge> : null}
    >
      <ErrorBox error={status.error ?? begin.error ?? enable.error ?? disable.error} />
      {recovery ? (
        <div className="stack" style={{ gap: 10 }} data-testid="two-factor-recovery">
          <p>
            <b>Kurtarma kodları</b> (yalnızca şimdi gösterilir). Telefonunuz yanınızda olmadığında her biri bir kez kullanılabilir;
            güvenli bir yere kaydedin.
          </p>
          <ul className="recovery-codes">
            {recovery.map((r) => (
              <li key={r}>
                <code>{r}</code>
              </li>
            ))}
          </ul>
          <label className="check">
            <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /> Kodları güvenli bir yere kaydettim
          </label>
          <button type="button" className="primary" disabled={!saved} onClick={() => setRecovery(null)}>
            Tamam
          </button>
        </div>
      ) : s?.enabled ? (
        <div className="stack" style={{ gap: 10 }}>
          <p className="small">Aşağıdaki işlemler doğrulama uygulamanızdaki 6 haneli kodu ve onayınızı ister:</p>
          <ul className="small" data-testid="two-factor-actions">
            {s.protected.map((a) => (
              <li key={a.key}>{a.label}</li>
            ))}
          </ul>
          <p className="muted small">Kalan kurtarma kodu: {s.recovery_left}</p>
          <div>
            <button type="button" className="danger" disabled={disable.pending} onClick={() => void disable.execute()} data-testid="two-factor-disable">
              Doğrulamayı kapat
            </button>
          </div>
        </div>
      ) : setup ? (
        <div className="stack" style={{ gap: 10 }} data-testid="two-factor-setup">
          <p className="small">
            1. Telefonunuzdaki doğrulama uygulamasıyla (Google Authenticator, Microsoft Authenticator…) QR kodu okutun. Okutamazsanız
            anahtarı elle girin.
          </p>
          <img src={setup.qr} alt="Doğrulama uygulaması için QR kod" width={200} height={200} style={{ background: "#fff", borderRadius: 12 }} />
          <p className="small">
            Anahtar: <code data-testid="two-factor-secret">{setup.secret}</code>
          </p>
          <label className="field">
            <span>2. Uygulamadaki 6 haneli kodu yazın</span>
            <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={6} data-testid="two-factor-code" />
          </label>
          <div>
            <button type="button" className="primary" disabled={code.trim().length !== 6 || enable.pending} onClick={() => void enable.execute()}>
              Etkinleştir
            </button>
          </div>
        </div>
      ) : (
        <div className="stack" style={{ gap: 10 }}>
          <p className="small">
            Açarsanız gerçek para moduna geçiş, gerçek hesap anahtarı ekleme/silme, acil durdurmayı kaldırma, lisansı bu bilgisayardan
            kaldırma ve telefon eşleme gibi işlemler, yönetim panelindeki lisans silmede olduğu gibi doğrulama kodu ve onay ister.
            Bilgisayarınıza başkası erişse de bu işlemleri kodsuz yapamaz.
          </p>
          <div>
            <button type="button" className="primary" disabled={begin.pending} onClick={() => void begin.execute()} data-testid="two-factor-begin">
              Doğrulamayı aç
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
