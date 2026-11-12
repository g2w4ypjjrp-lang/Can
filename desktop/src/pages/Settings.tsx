import { type FormEvent, useEffect, useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import type { AuditEntry, Market, TestnetKeyResponse } from "../api/types.gen";
import { ModeSwitch } from "../components/ModeSwitch";
import { Badge, Card, DataTable, ErrorBox, Field } from "../components/ui";
import { MARKET_LABELS, time } from "../lib/format";
import { CrashReportsSection } from "./CrashReports";
import { LicenseSection } from "./License";
import { TelegramSection } from "./Telegram";

interface ExecutionStatus {
  live_locked: boolean;
  markets: Record<string, { key_stored: boolean; key_hint: string | null; connected: boolean; error: string | null }>;
}

export function Settings() {
  const execution = usePoll((c) => c.get<ExecutionStatus>("/v1/execution/status", { environment: "testnet" }), 5000);
  const live = usePoll((c) => c.get<ExecutionStatus>("/v1/execution/status", { environment: "live" }), 5000);
  const audit = usePoll((c) => c.get<AuditEntry[]>("/v1/audit", { limit: 30 }), 10000);
  const liveKeyed = Object.values(live.data?.markets ?? {}).some((m) => m?.key_stored);
  return (
    <div className="page" data-testid="page-settings">
      <LicenseSection />

      <Card title="İşlem modu" testId="trading-mode-card">
        <ModeSwitch onChanged={() => void execution.refresh()} />
        <p className="muted small">
          <b>Sanal</b> emir göndermez. <b>Demo para</b>, Binance'in sahte bakiyeyle ve gerçek fiyatlarla çalışan Demo Trading
          ortamıdır. <b>Gerçek para</b> gerçek Binance hesabınızda işlem yapar: para çekme yetkisi kapalı gerçek hesap anahtarı,
          geçerli lisans ve onay ifadesi gerekir; uygulama yeniden başladığında güvenlik için sanal moda döner.
        </p>
      </Card>

      <h3 className="section-title">Binance hesap anahtarları (gerçek para)</h3>
      <div className="grid-2">
        {(["usdm_futures", "spot"] as Market[]).map((market) => (
          <KeyForm key={market} environment="live" market={market} info={live.data?.markets[market]} onChange={live.refresh} />
        ))}
      </div>
      {/* Gerçek hesap anahtarı varsa deneme (Demo Trading) anahtarları katlanır. */}
      <details className="card system-details" open={!liveKeyed}>
        <summary>Deneme hesabı anahtarları (Binance Demo Trading, sahte bakiye)</summary>
        <div className="card-body">
          <div className="grid-2">
            {(["usdm_futures", "spot"] as Market[]).map((market) => (
              <KeyForm key={market} environment="testnet" market={market} info={execution.data?.markets[market]} onChange={execution.refresh} />
            ))}
          </div>
        </div>
      </details>

      <TelegramSection />

      <CrashReportsSection />

      <Card title="Denetim kaydı (son işlemler)">
        <ErrorBox error={audit.error} />
        <DataTable
          testId="audit"
          rows={audit.data}
          rowKey={(r) => String(r.id)}
          columns={[
            { key: "t", label: "Zaman", render: (r) => time(r.ts) },
            { key: "a", label: "Eylem", render: (r) => <code>{r.action}</code> },
            { key: "who", label: "Kim", render: (r) => r.actor },
          ]}
        />
      </Card>
    </div>
  );
}

function KeyForm({
  environment,
  market,
  info,
  onChange,
}: {
  environment: "testnet" | "live";
  market: Market;
  info: ExecutionStatus["markets"][string] | undefined;
  onChange: () => Promise<void>;
}) {
  const live = environment === "live";
  const [apiKey, setApiKey] = useState("");
  const [secret, setSecret] = useState("");
  const [result, setResult] = useState<TestnetKeyResponse | null>(null);
  const path = live ? "/v1/execution/live-key" : "/v1/execution/testnet-key";
  const save = useAction((c) => c.post<TestnetKeyResponse>(path, { market, api_key: apiKey, secret }));
  const remove = useAction((c) => c.post(`${path}/delete`, undefined, { market }));
  const testId = `${live ? "live-key" : "key"}-${market}`;
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!save.pending) {
      setElapsed(0);
      return;
    }
    const started = Date.now();
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [save.pending]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const response = await save.execute();
    setSecret(""); // gizli anahtar ekranda tutulmaz
    if (response) {
      setResult(response);
      if (response.stored) setApiKey("");
    }
    await onChange();
  };

  return (
    <Card title={`${live ? "Gerçek hesap" : "Demo Trading"} anahtarı — ${MARKET_LABELS[market]}`} testId={testId}>
      {live ? (
        <div className="muted small stack" style={{ gap: 6 }}>
          <span>
            <b>binance.com</b> → Profil → <b>API Yönetimi</b> → <b>API Oluştur</b>. Yetkiler: <b>Okuma</b> ve{" "}
            {market === "spot" ? <b>Spot ve Marjin işlemi</b> : <b>Vadeli işlemler (Futures)</b>}.
          </span>
          <span className="down">
            <b>Para çekme yetkisini KESİNLİKLE açmayın.</b> Para çekme veya transfer yetkisi açık anahtar uygulama
            tarafından reddedilir ve saklanmaz.
          </span>
          <span>Güvenlik için "Güvenilir IP'lerle kısıtla" seçeneğiyle yalnızca bu bilgisayarın IP adresine izin verin.</span>
          <span>Anahtar bu bilgisayarda şifreli saklanır; sunucularımıza gönderilmez. Ekranda yalnızca son 4 karakter görünür.</span>
        </div>
      ) : (
        <p className="muted small">
          Sahte bakiyeyle, gerçek piyasa fiyatlarında çalışan Binance Demo Trading anahtarı. Oluşturmak için:{" "}
          <b>demo.binance.com</b> → Binance hesabınızla giriş → <b>API Management</b> → <b>Create API</b>. Gerçek hesap
          anahtarı burada çalışmaz. Anahtar doğrulanır ve bu bilgisayarda şifreli saklanır; ekranda yalnızca son 4
          karakter görünür.
        </p>
      )}
      <div className="row">
        <Badge tone={info?.connected ? "ok" : info?.key_stored ? "warn" : "neutral"} testId={`${testId}-state`}>
          {info?.connected ? `Bağlı ${info.key_hint ?? ""}` : info?.key_stored ? `Kayıtlı ${info.key_hint ?? ""}` : "Anahtar yok"}
        </Badge>
        {info?.key_stored && (
          <button
            onClick={async () => {
              await remove.execute();
              setResult(null);
              await onChange();
            }}
          >
            Anahtarı sil
          </button>
        )}
      </div>
      {info?.error && <div className="notice">{info.error}</div>}
      <form className="form" onSubmit={onSubmit} autoComplete="off">
        <Field label="API anahtarı">
          <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} required minLength={16} data-testid={`${testId}-api`} />
        </Field>
        <Field label="Gizli anahtar">
          <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} required minLength={16} data-testid={`${testId}-secret`} />
        </Field>
        <button className="primary" type="submit" disabled={save.pending} data-testid={`${testId}-save`}>
          {save.pending ? `Binance'te doğrulanıyor… ${elapsed} sn` : "Doğrula ve kaydet"}
        </button>
        {save.pending && elapsed >= 10 && (
          <p className="muted small" data-testid={`${testId}-wait`}>
            Binance yanıtı bekleniyor (en çok 45 sn). Uzarsa internet bağlantınızı ve Windows saatinin otomatik olduğunu kontrol
            edin.
          </p>
        )}
      </form>
      <ErrorBox error={save.error ?? remove.error} />
      {result && (
        <div className={result.stored ? "ok" : "error"} data-testid={`${testId}-result`}>
          {result.message}
        </div>
      )}
    </Card>
  );
}
