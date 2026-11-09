import { type FormEvent, useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import type { AuditEntry, Market, StatusResponse, TestnetKeyResponse, TradingModeResponse } from "../api/types.gen";
import { Badge, Card, DataTable, ErrorBox, Field } from "../components/ui";
import { MARKET_LABELS, MODE_LABELS, time } from "../lib/format";
import { LicenseSection } from "./License";
import { PhoneSection } from "./Phone";

interface ExecutionStatus {
  live_locked: boolean;
  markets: Record<string, { key_stored: boolean; key_hint: string | null; connected: boolean; error: string | null }>;
}

export function Settings() {
  const status = usePoll((c) => c.get<StatusResponse>("/v1/status"), 3000);
  const execution = usePoll((c) => c.get<ExecutionStatus>("/v1/execution/status"), 5000);
  const audit = usePoll((c) => c.get<AuditEntry[]>("/v1/audit", { limit: 30 }), 10000);
  const [modeResult, setModeResult] = useState<TradingModeResponse | null>(null);
  const setMode = useAction(async (c, mode: string) => {
    try {
      return await c.post<TradingModeResponse>("/v1/trading-mode", { mode });
    } catch (e) {
      // 409: kontrol(ler) geçmedi; gövdede ayrıntı var
      const detail = (e as { detail?: unknown }).detail;
      if (detail && typeof detail === "object" && "checks" in (detail as object)) return detail as TradingModeResponse;
      throw e;
    }
  });

  const current = status.data?.trading_mode;
  return (
    <div className="page" data-testid="page-settings">
      <LicenseSection />

      <Card title="İşlem modu">
        <div className="row">
          <span>Şu an:</span>
          <Badge tone={current === "testnet" ? "info" : "neutral"} testId="settings-mode">
            {MODE_LABELS[current ?? ""] ?? "—"}
          </Badge>
          {(["paper", "testnet"] as const).map((mode) => (
            <button
              key={mode}
              disabled={setMode.pending || current === mode}
              onClick={async () => {
                setModeResult((await setMode.execute(mode)) ?? null);
                await status.refresh();
              }}
              data-testid={`mode-${mode}`}
            >
              {MODE_LABELS[mode]}
            </button>
          ))}
          <button disabled title="Kullanıcı onayı (G1/G2) olmadan açılamaz" data-testid="mode-live">
            Gerçek hesap (kilitli)
          </button>
        </div>
        <ErrorBox error={setMode.error} />
        {modeResult && !modeResult.accepted && (
          <ul className="reasons">
            {modeResult.checks
              .filter((c) => !c.passed)
              .map((c) => (
                <li key={c.name} className="down">
                  {c.message}
                </li>
              ))}
          </ul>
        )}
        <p className="muted small">
          Sanal işlem gerçek emir göndermez. Test ağı Binance'in sahte parayla çalışan ortamıdır. Gerçek hesapla işlem bu sürümde
          kilitlidir: işlem yetkili canlı anahtar (G1) ve ilk gerçek işlem (G2) için açık onayınız gerekir.
        </p>
      </Card>

      <div className="grid-2">
        {(["usdm_futures", "spot"] as Market[]).map((market) => (
          <KeyForm key={market} market={market} info={execution.data?.markets[market]} onChange={execution.refresh} />
        ))}
      </div>

      <PhoneSection />

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
  market,
  info,
  onChange,
}: {
  market: Market;
  info: ExecutionStatus["markets"][string] | undefined;
  onChange: () => Promise<void>;
}) {
  const [apiKey, setApiKey] = useState("");
  const [secret, setSecret] = useState("");
  const [result, setResult] = useState<TestnetKeyResponse | null>(null);
  const save = useAction((c) => c.post<TestnetKeyResponse>("/v1/execution/testnet-key", { market, api_key: apiKey, secret }));
  const remove = useAction((c) => c.post("/v1/execution/testnet-key/delete", undefined, { market }));
  const testId = `key-${market}`;

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
    <Card title={`Binance test ağı anahtarı — ${MARKET_LABELS[market]}`} testId={testId}>
      <p className="muted small">
        {market === "usdm_futures" ? "testnet.binancefuture.com" : "testnet.binance.vision"} üzerinden oluşturulan test ağı
        anahtarı. Anahtar doğrulanır ve bu bilgisayarda şifreli saklanır; ekranda yalnızca son 4 karakter görünür.
      </p>
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
          {save.pending ? "Doğrulanıyor…" : "Doğrula ve kaydet"}
        </button>
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
