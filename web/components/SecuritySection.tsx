"use client";

import { ShieldCheck, ShieldOff } from "lucide-react";
import { toDataURL } from "qrcode";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { ErrorBox } from "@/components/auth/ErrorBox";
import { formValue, useSubmit } from "@/components/auth/useSubmit";
import { Badge, Button, Card, Field, Notice } from "@/components/ui";
import { formatDate } from "@/lib/format";

interface MfaStatus {
  enabled: boolean;
  enabled_at: string | null;
  recovery_left: number;
  available: boolean;
}

interface Setup {
  secret: string;
  otpauth_uri: string;
}

type Step = "idle" | "password" | "scan" | "codes" | "disable";

/** Müşteri panelinde iki adımlı doğrulama (TOTP): aç, kurtarma kodlarını göster, kapat. */
export function SecuritySection() {
  const api = useApi();
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("idle");
  const [setup, setSetup] = useState<Setup | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [saved, setSaved] = useState(false);
  const action = useSubmit();

  const load = useCallback(() => {
    api
      .get<MfaStatus>("/v1/me/2fa")
      .then(setStatus)
      .catch((err: unknown) => setLoadError(err instanceof Error ? err.message : "Güvenlik ayarları yüklenemedi"));
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  function begin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    void action.run(async () => {
      const result = await api.post<Setup>("/v1/me/2fa/setup", { password: formValue(form, "mfa-password") });
      setSetup(result);
      setQr(await toDataURL(result.otpauth_uri, { margin: 1, width: 200 }));
      setStep("scan");
    });
  }

  function enable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    void action.run(async () => {
      const result = await api.post<{ recovery_codes: string[] }>("/v1/me/2fa/enable", {
        code: formValue(form, "mfa-code").trim(),
      });
      setCodes(result.recovery_codes);
      setSetup(null);
      setQr(null);
      setStep("codes");
      load();
    });
  }

  function disable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    void action.run(async () => {
      await api.post("/v1/me/2fa/disable", {
        password: formValue(form, "mfa-off-password"),
        code: formValue(form, "mfa-off-code").trim(),
      });
      setStep("idle");
      load();
    });
  }

  function cancel() {
    setStep("idle");
    setSetup(null);
    setQr(null);
  }

  return (
    <section aria-labelledby="guvenlik" className="mt-10">
      <h2 id="guvenlik" className="text-xl font-semibold text-fg">
        Güvenlik
      </h2>
      <Card className="mt-4 space-y-4" as="div">
        {loadError ? (
          <Notice tone="danger" role="alert">
            {loadError}
          </Notice>
        ) : status === null ? (
          <p role="status" className="text-sm text-muted">
            Güvenlik ayarları yükleniyor…
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="flex items-start gap-3">
                {status.enabled ? (
                  <ShieldCheck aria-hidden="true" className="mt-0.5 h-5 w-5 text-success-fg" />
                ) : (
                  <ShieldOff aria-hidden="true" className="mt-0.5 h-5 w-5 text-muted" />
                )}
                <div>
                  <p className="font-medium text-fg">
                    İki adımlı doğrulama{" "}
                    <Badge tone={status.enabled ? "success" : "neutral"}>
                      <span data-testid="mfa-state">{status.enabled ? "Açık" : "Kapalı"}</span>
                    </Badge>
                  </p>
                  <p className="mt-1 text-sm text-muted">
                    {status.enabled
                      ? `${status.enabled_at ? formatDate(status.enabled_at) + " tarihinden beri açık. " : ""}Kalan kurtarma kodu: ${status.recovery_left}.`
                      : "Girişte parolanıza ek olarak telefonunuzdaki doğrulama uygulamasının kodu istenir. Parolanız ele geçse bile hesabınız ve lisans anahtarlarınız korunur."}
                  </p>
                </div>
              </div>
              {step === "idle" && status.available ? (
                status.enabled ? (
                  <Button variant="secondary" size="sm" className="px-4 py-2" onClick={() => setStep("disable")}>
                    Kapat
                  </Button>
                ) : (
                  <Button size="sm" className="px-4 py-2" onClick={() => setStep("password")} data-testid="mfa-start">
                    Aç
                  </Button>
                )
              ) : null}
            </div>
            {!status.available ? (
              <Notice tone="warning">İki adımlı doğrulama şu an sunucuda yapılandırılmamış.</Notice>
            ) : null}

            {step === "password" ? (
              <form onSubmit={begin} className="space-y-4 border-t border-border pt-4">
                <Field id="mfa-password" name="mfa-password" type="password" label="Parolanız" autoComplete="current-password" required />
                <ErrorBox error={action.error} />
                <div className="flex gap-2">
                  <Button type="submit" disabled={action.pending}>
                    Devam
                  </Button>
                  <Button type="button" variant="secondary" onClick={cancel}>
                    Vazgeç
                  </Button>
                </div>
              </form>
            ) : null}

            {step === "scan" && setup ? (
              <form onSubmit={enable} className="space-y-4 border-t border-border pt-4">
                <ol className="list-decimal space-y-1.5 pl-5 text-sm text-fg">
                  <li>Telefonunuzda bir doğrulama uygulaması açın (Google Authenticator, Microsoft Authenticator, 1Password…).</li>
                  <li>QR kodu okutun veya anahtarı elle girin.</li>
                  <li>Uygulamada görünen 6 haneli kodu aşağıya yazın.</li>
                </ol>
                <div className="flex flex-col items-center gap-2 sm:flex-row sm:items-center sm:gap-6">
                  {qr ? <img src={qr} width={200} height={200} alt="Doğrulama uygulaması için QR kod" className="rounded-xl bg-white p-1" /> : null}
                  <div className="text-center sm:text-left">
                    <p className="text-xs text-muted">Anahtar (elle giriş):</p>
                    <code className="mt-1 inline-block break-all rounded bg-surface-2 px-2 py-1 font-mono text-xs text-fg" data-testid="mfa-secret">
                      {setup.secret}
                    </code>
                  </div>
                </div>
                <Field id="mfa-code" name="mfa-code" label="Doğrulama kodu" inputMode="numeric" autoComplete="one-time-code" required maxLength={6} />
                <ErrorBox error={action.error} />
                <div className="flex gap-2">
                  <Button type="submit" disabled={action.pending}>
                    Etkinleştir
                  </Button>
                  <Button type="button" variant="secondary" onClick={cancel}>
                    Vazgeç
                  </Button>
                </div>
              </form>
            ) : null}

            {step === "codes" && codes ? (
              <div className="space-y-4 border-t border-border pt-4">
                <Notice tone="success" role="status" title="İki adımlı doğrulama açıldı">
                  Telefonunuza erişemezseniz bu kurtarma kodlarıyla giriş yapabilirsiniz. Her kod bir kez kullanılır ve
                  bir daha gösterilmez; güvenli bir yere (ör. parola yöneticisi) kaydedin.
                </Notice>
                <ul className="grid grid-cols-2 gap-2 font-mono text-sm sm:grid-cols-5" data-testid="mfa-recovery-codes">
                  {codes.map((code) => (
                    <li key={code} className="rounded-lg bg-surface-2 px-3 py-2 text-center text-fg">
                      {code}
                    </li>
                  ))}
                </ul>
                <label className="flex items-center gap-2 text-sm text-fg">
                  <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} className="h-4 w-4" />
                  Kodları güvenli bir yere kaydettim
                </label>
                <Button
                  disabled={!saved}
                  onClick={() => {
                    setCodes(null);
                    setSaved(false);
                    setStep("idle");
                  }}
                >
                  Tamam
                </Button>
              </div>
            ) : null}

            {step === "disable" ? (
              <form onSubmit={disable} className="space-y-4 border-t border-border pt-4">
                <p className="text-sm text-muted">Kapatmak için parolanızı ve güncel doğrulama kodunu (veya bir kurtarma kodunu) girin.</p>
                <Field id="mfa-off-password" name="mfa-off-password" type="password" label="Parolanız" autoComplete="current-password" required />
                <Field id="mfa-off-code" name="mfa-off-code" label="Doğrulama kodu" autoComplete="one-time-code" required maxLength={20} />
                <ErrorBox error={action.error} />
                <div className="flex gap-2">
                  <Button type="submit" variant="secondary" disabled={action.pending}>
                    İki adımlı doğrulamayı kapat
                  </Button>
                  <Button type="button" variant="secondary" onClick={cancel}>
                    Vazgeç
                  </Button>
                </div>
              </form>
            ) : null}
          </>
        )}
      </Card>
    </section>
  );
}
