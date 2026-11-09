"use client";

import { useRouter } from "next/navigation";
import { toDataURL } from "qrcode";
import { useEffect, useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { Feedback, useAdminAction } from "@/components/admin/kit";
import { Button, Card, Field, Notice } from "@/components/ui";

interface Setup {
  email: string;
  otpauth_uri: string;
  secret: string;
}

/** Davet: doğrulama uygulaması kurulumu + parola → kurtarma kodları (bir kez gösterilir). */
export function AdminInvite({ token }: { token: string | undefined }) {
  const api = useApi();
  const router = useRouter();
  const action = useAdminAction();
  const [setup, setSetup] = useState<Setup | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [saved, setSaved] = useState(false);
  const [mismatch, setMismatch] = useState(false);

  useEffect(() => {
    if (!token) return;
    window.history.replaceState(null, "", "/yonetim/davet");
    void action.run(async () => {
      const result = await api.post<Setup>("/admin/v1/auth/invite/start", { token });
      setSetup(result);
      setQr(await toDataURL(result.otpauth_uri, { margin: 1, width: 220 }));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca açılışta
  }, [token]);

  async function onComplete(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    if (data.get("password") !== data.get("password2")) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    const result = await action.run(() =>
      api.post<{ recovery_codes: string[] }>("/admin/v1/auth/invite/complete", {
        token,
        password: data.get("password"),
        code: data.get("code"),
      }),
    );
    if (result) setCodes(result.recovery_codes);
  }

  if (!token) {
    return (
      <Notice tone="danger" role="alert">
        Davet bağlantısı eksik.
      </Notice>
    );
  }
  if (codes) {
    return (
      <Card className="space-y-4 shadow-soft">
        <h1 className="text-xl font-semibold text-fg">Kurtarma kodlarınız</h1>
        <p className="text-sm text-muted">
          Telefonunuza erişemediğinizde bu kodlarla giriş yapabilirsiniz. Her kod bir kez kullanılır. Bu kodlar bir daha
          gösterilmeyecek; güvenli bir yere (ör. parola yöneticisi) kaydedin.
        </p>
        <ul className="grid grid-cols-2 gap-2 font-mono text-sm" data-testid="recovery-codes">
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
        <Button className="w-full" disabled={!saved} onClick={() => router.replace("/yonetim")}>
          Panele geç
        </Button>
      </Card>
    );
  }
  return (
    <Card className="space-y-5 shadow-soft">
      <h1 className="text-xl font-semibold text-fg">Yönetici hesabını etkinleştir</h1>
      <Feedback error={action.error} />
      {setup ? (
        <>
          <ol className="list-decimal space-y-2 pl-5 text-sm text-fg">
            <li>Telefonunuzda bir doğrulama uygulaması açın (Google Authenticator, Microsoft Authenticator, 1Password…).</li>
            <li>QR kodu okutun veya anahtarı elle girin.</li>
            <li>Parolanızı belirleyip uygulamadaki 6 haneli kodu girin.</li>
          </ol>
          <div className="flex flex-col items-center gap-2">
            {qr ? <img src={qr} width={220} height={220} alt="Doğrulama uygulaması için QR kod" /> : null}
            <p className="text-xs text-muted">Anahtar (elle giriş):</p>
            <code className="break-all rounded bg-surface-2 px-2 py-1 font-mono text-xs text-fg" data-testid="totp-secret">
              {setup.secret}
            </code>
          </div>
          <form onSubmit={onComplete} className="space-y-4">
            <p className="text-sm text-fg">
              Hesap: <strong>{setup.email}</strong>
            </p>
            <Field id="password" name="password" type="password" label="Parola" autoComplete="new-password" minLength={12} required hint="En az 12 karakter." />
            <Field
              id="password2"
              name="password2"
              type="password"
              label="Parola (tekrar)"
              autoComplete="new-password"
              required
              error={mismatch ? "Parolalar eşleşmiyor" : undefined}
            />
            <Field id="code" name="code" label="Doğrulama kodu" inputMode="numeric" autoComplete="one-time-code" required />
            <Button type="submit" className="w-full" disabled={action.pending}>
              Hesabı etkinleştir
            </Button>
          </form>
        </>
      ) : action.pending ? (
        <p role="status" className="text-sm text-muted">
          Davet denetleniyor…
        </p>
      ) : null}
    </Card>
  );
}
