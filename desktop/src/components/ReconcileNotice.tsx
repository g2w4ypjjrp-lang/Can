import { RefreshCw, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import { Confirm, ErrorBox } from "./ui";

interface Issue {
  rule: string;
  severity: string;
  symbol: string | null;
  action: string;
  details: Record<string, string>;
}
interface Report {
  ok: boolean;
  error: string | null;
  issues: Issue[];
  finished_ms?: number | null;
}
interface MarketStatus {
  last_reconcile?: Report | null;
}

const RULES: Record<string, string> = {
  position_mismatch: "Pozisyon farkı: uygulamanın kaydı ile Binance'teki miktar farklı",
  balance_shortfall: "Bakiye farkı: kayıttaki coin miktarı Binance'teki bakiyeden fazla",
  unprotected_position: "Korumasız pozisyon: zarar durdur emri kurulamadı",
  reconcile_failed: "Binance'e ulaşılamadı",
};

const MARKETS: Record<string, string> = { usdm_futures: "Futures", spot: "Spot" };

/** Mutabakat farkı yüzünden motor Güvenli moddaysa: nedeni Türkçe gösterir, tekrar denetir ve
 * kullanıcı onayıyla yerel kaydı Binance'teki duruma eşitler. */
export function ReconcileNotice({ conditions, onChange }: { conditions: { name: string; ready: boolean }[]; onChange: () => Promise<unknown> | void }) {
  const failing = conditions.filter((c) => !c.ready && c.name.endsWith(".reconciled"));
  const market = failing[0]?.name.split(".").slice(-2, -1)[0];
  const exec = usePoll((c) => (market ? c.get<{ markets: Record<string, MarketStatus> }>("/v1/execution/status") : Promise.resolve(null)), 5000, [market]);
  const [ask, setAsk] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const retry = useAction(async (c) => {
    await c.post("/v1/execution/reconcile", undefined, { market: market! });
    await exec.refresh();
    await onChange();
  });
  const adopt = useAction(async (c) => {
    const result = await c.post<{ changed: { symbol: string }[] }>("/v1/execution/reconcile/adopt", undefined, { market: market! });
    setDone(result.changed.length ? `Eşitlendi: ${result.changed.map((x) => x.symbol).join(", ")}` : "Eşitlenecek fark yoktu");
    await exec.refresh();
    await onChange();
  });
  if (!market) return null;
  const report = exec.data?.markets?.[market]?.last_reconcile ?? null;
  const critical = (report?.issues ?? []).filter((i) => i.severity === "critical");
  const mismatch = critical.some((i) => i.rule === "position_mismatch" || i.rule === "balance_shortfall");

  return (
    <div className="card reconcile-notice" role="alert" data-testid="reconcile-notice">
      <div className="card-body">
        <h3 className="row" style={{ gap: 8, margin: 0 }}>
          <ShieldAlert size={18} aria-hidden="true" /> Güvenli mod: Binance ile kayıtlar uyuşmuyor ({MARKETS[market] ?? market})
        </h3>
        <p className="muted small">
          Uygulama her dakika kendi kaydını Binance'teki gerçek durumla karşılaştırır. Fark bulunca, yanlış bilgiyle işlem açmamak için yeni işlem açmaz;
          açık pozisyonların Binance'teki stopları yerinde kalır.
        </p>
        <ul className="small" data-testid="reconcile-issues">
          {report?.error && <li>Binance'e ulaşılamadı: {report.error}</li>}
          {critical.map((i, n) => (
            <li key={n}>
              <b>{i.symbol ?? ""}</b> {RULES[i.rule] ?? i.rule}
              {i.details?.local !== undefined && (
                <span className="muted"> (uygulama: {i.details.local}, Binance: {i.details.exchange})</span>
              )}
            </li>
          ))}
          {!report && <li className="muted">Ayrıntı yükleniyor…</li>}
        </ul>
        {mismatch && (
          <p className="small">
            Pozisyonu Binance uygulamasından elle kapattıysanız bu normaldir: <b>Binance'e eşitle</b> ile uygulamanın kaydı Binance'teki duruma
            getirilir.
          </p>
        )}
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <button type="button" onClick={() => void retry.execute()} disabled={retry.pending} data-testid="reconcile-retry">
            <RefreshCw size={14} aria-hidden="true" /> Tekrar denetle
          </button>
          {mismatch && (
            <button type="button" className="primary" onClick={() => setAsk(true)} disabled={adopt.pending} data-testid="reconcile-adopt">
              Binance'e eşitle
            </button>
          )}
          {done && <span className="small" role="status">{done}</span>}
        </div>
        <ErrorBox error={retry.error ?? adopt.error} />
      </div>
      <Confirm
        open={ask}
        title="Kayıt Binance'e eşitlensin mi?"
        confirmLabel="Eşitle"
        onCancel={() => setAsk(false)}
        onConfirm={() => {
          setAsk(false);
          void adopt.execute();
        }}
      >
        Binance'te kapalı görünen pozisyonların uygulamadaki kaydı kapatılır ve bekleyen stop/hedef emirleri iptal edilir. Binance'teki pozisyonlarınıza
        ve bakiyenize dokunulmaz. Binance'te açık olan bir pozisyonu kapatmaz.
      </Confirm>
    </div>
  );
}
