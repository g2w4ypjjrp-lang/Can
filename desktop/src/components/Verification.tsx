import { ShieldCheck } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { useClient } from "../api/hooks";
import type { VerificationRequest } from "../api/client";

/** Kritik işlemde doğrulama kodu penceresi (yönetim panelindeki lisans silme gibi): motor kod
 * isteyince (HTTP 428) açılır; kod ve onay kutusuyla aynı istek yinelenir. */
export function VerificationHost() {
  const client = useClient();
  const [pending, setPending] = useState<{ request: VerificationRequest; resolve: (code: string | null) => void } | null>(null);
  const [code, setCode] = useState("");
  const [sure, setSure] = useState(false);

  useEffect(() => {
    client.verifier = (request) =>
      new Promise((resolve) => {
        setCode("");
        setSure(false);
        setPending({ request, resolve });
      });
    return () => {
      client.verifier = null;
    };
  }, [client]);

  if (!pending) return null;
  const { request, resolve } = pending;
  const finish = (value: string | null) => {
    setPending(null);
    resolve(value);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (code.trim().length >= 6 && sure) finish(code.trim());
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="dogrulama-baslik" data-testid="verify-dialog">
      <form className="modal" onSubmit={submit}>
        <h3 id="dogrulama-baslik" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <ShieldCheck aria-hidden="true" size={18} /> Doğrulama gerekli
        </h3>
        <div className="modal-body stack" style={{ gap: 10 }}>
          <p>
            <b>{request.label}</b> için doğrulama uygulamanızdaki (Google / Microsoft Authenticator) 6 haneli kodu yazın.
            Telefonunuz yanınızda değilse kurtarma kodlarından birini kullanabilirsiniz.
          </p>
          {request.reason === "invalid" && (
            <p className="notice danger-notice" role="alert" data-testid="verify-error">
              {request.message}
            </p>
          )}
          <label className="field">
            <span>Doğrulama kodu</span>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={12}
              autoFocus
              data-testid="verify-code"
            />
          </label>
          <label className="check">
            <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} data-testid="verify-sure" />
            Bu işlemi ben yapıyorum, onaylıyorum
          </label>
        </div>
        <div className="modal-actions">
          <button type="button" onClick={() => finish(null)}>
            Vazgeç
          </button>
          <button type="submit" className="primary" disabled={code.trim().length < 6 || !sure} data-testid="verify-submit">
            Doğrula ve devam et
          </button>
        </div>
      </form>
    </div>
  );
}
