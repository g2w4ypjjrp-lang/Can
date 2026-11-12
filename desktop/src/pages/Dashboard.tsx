import { Briefcase, Gauge, RefreshCw, Wallet } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useAction } from "../api/hooks";
import { usePoll } from "../api/hooks";
import type { ExecutionPositionInfo, OpportunitySummary, StatusResponse } from "../api/types.gen";
import { BotPanel } from "../components/BotPanel";
import { GettingStarted } from "../components/GettingStarted";
import { LivePnl } from "../components/LivePnl";
import { Badge, Card, Confirm, DataTable, Disclaimer, ErrorBox } from "../components/ui";
import { duration, MARKET_LABELS, MODE_LABELS, num, pct, price, STATE_LABELS } from "../lib/format";
import { useNavigate } from "../lib/nav";
import { TradeHistory } from "../components/TradeHistory";

export function stateTone(state?: string): "ok" | "warn" | "bad" | "neutral" {
  if (state === "running") return "ok";
  if (state === "safe_mode" || state === "starting") return "warn";
  if (state === "halted") return "bad";
  return "neutral";
}

/** Motorun hazırlık koşullarının anlaşılır adları (kod adı ipucunda kalır). */
const CONDITION_LABELS: Record<string, string> = {
  "market_data.spot": "Spot piyasa verisi",
  "market_data.usdm_futures": "Futures piyasa verisi",
  "risk.daily_loss": "Günlük zarar sınırı",
  "live.risk.daily_loss": "Günlük zarar sınırı (gerçek hesap)",
  "license.valid": "Lisans",
};

function Kpi({ icon, label, value, hint, tone, testId }: { icon: ReactNode; label: string; value: ReactNode; hint?: ReactNode; tone?: string; testId?: string }) {
  return (
    <div className={`kpi ${tone ?? ""}`} data-testid={testId}>
      <span className="kpi-icon" aria-hidden="true">
        {icon}
      </span>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {hint && <span className="kpi-hint">{hint}</span>}
    </div>
  );
}

interface WalletInfo {
  market: string;
  asset: string;
  balance: string;
  available: string;
  unrealized_pnl: string;
}

const usdt = (v: number) => v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Binance cüzdanı: toplam (bakiye + açık pozisyonların gerçekleşmemiş kâr/zararı), piyasa başına
 * bakiye ve kullanılabilir tutar. Anahtar yoksa nereden ekleneceği yazılır. */
const RELEASE_DAY_PHRASE = "KILIDI KALDIR";

function BalanceHero({
  wallets,
  live,
  halted,
  haltReason,
  age,
  accountError,
  onKeys,
  onReleased,
}: {
  wallets: WalletInfo[] | null;
  live: boolean;
  halted: boolean;
  haltReason?: string | null;
  age?: number;
  accountError?: string | null;
  onKeys: () => void;
  onReleased: () => Promise<unknown>;
}) {
  const [ask, setAsk] = useState(false);
  const release = useAction((c) => c.post("/v1/risk/release-day", { confirmation: RELEASE_DAY_PHRASE }));
  const total = (wallets ?? []).reduce((sum, w) => sum + Number(w.balance) + Number(w.unrealized_pnl), 0);
  const unrealized = (wallets ?? []).reduce((sum, w) => sum + Number(w.unrealized_pnl), 0);
  return (
    <section className={`balance-hero ${live ? "live" : ""}`} data-testid="balance-hero" aria-labelledby="bakiye-baslik">
      <div className="balance-main">
        <span id="bakiye-baslik" className="balance-label">
          <Wallet size={16} aria-hidden="true" /> Binance bakiyesi {live ? "· gerçek hesap" : ""}
        </span>
        {wallets && wallets.length > 0 ? (
          <>
            <span className="balance-value" data-testid="balance-total">
              {usdt(total)} <small>USDT</small>
            </span>
            <span className={`balance-sub ${unrealized > 0 ? "up" : unrealized < 0 ? "down" : ""}`}>
              Açık pozisyonlarda {unrealized >= 0 ? "+" : ""}
              {usdt(unrealized)} USDT
              {age !== undefined ? <span className="muted"> · {Math.round(age)} sn önce</span> : null}
            </span>
          </>
        ) : (
          <>
            <span className="balance-value muted">—</span>
            <span className="balance-sub">
              Bakiye için Binance anahtarı gerekli.{" "}
              <button type="button" className="ghost link" onClick={onKeys}>
                Anahtar ekle
              </button>
            </span>
          </>
        )}
      </div>
      {wallets && wallets.length > 0 && (
        <ul className="balance-wallets" data-testid="balance-wallets">
          {wallets.map((w) => (
            <li key={w.market}>
              <span className="muted small">{MARKET_LABELS[w.market] ?? w.market} cüzdanı</span>
              <b>
                {usdt(Number(w.balance))} {w.asset}
              </b>
              <span className="muted small">kullanılabilir {usdt(Number(w.available))}</span>
            </li>
          ))}
        </ul>
      )}
      {accountError && (
        <div className="balance-halt" role="alert" data-testid="balance-error">
          <span>
            <b>Binance hesabı şu an okunamıyor:</b> {accountError}. Gösterilen bakiye son okumadır. İnternet bağlantınızı ve
            Windows saatinin otomatik olduğunu kontrol edin (Ayarlar → Saat ve dil → Şimdi eşitle).
          </span>
        </div>
      )}
      {halted && (
        <div className="balance-halt" role="status" data-testid="balance-halt">
          <span>
            <b>Bugün yeni işlem kilitli.</b> {haltReason ?? "Günlük zarar sınırı"}. Kilit UTC gün başında (03:00) kendiliğinden
            açılır. Zarar şu an sınırın altındaysa (ör. aktarım ya da anlık hatalı okuma) kaldırabilirsiniz.
          </span>
          <button type="button" onClick={() => setAsk(true)} data-testid="release-day">
            Kilidi kaldır
          </button>
          <ErrorBox error={release.error} />
        </div>
      )}
      <Confirm
        open={ask}
        title="Günlük kilidi kaldır"
        phrase={RELEASE_DAY_PHRASE}
        confirmLabel="Kaldır"
        onCancel={() => setAsk(false)}
        onConfirm={async () => {
          setAsk(false);
          await release.execute();
          await onReleased();
        }}
      >
        Yalnızca güncel günlük zarar sınırın altındaysa kaldırılır; gün başı bakiye şimdiki bakiyeye çekilir ve risk sınırları
        aynen geçerli kalır. Kayda geçer.
      </Confirm>
      <RefreshCw size={14} className="balance-live-dot" aria-hidden="true" />
    </section>
  );
}

/** Kontrol paneli: Binance bakiyesi, bot, açık pozisyonlar ve en iyi fırsatlar. Teknik ayrıntılar en altta. */
export function Dashboard() {
  const navigate = useNavigate();
  const status = usePoll((c) => c.get<StatusResponse>("/v1/status"), 2000);
  const risk = usePoll((c) => c.get<Record<string, unknown>>("/v1/risk/status"), 5000);
  const positions = usePoll((c) => c.get<ExecutionPositionInfo[]>("/v1/execution/positions"), 2000);
  const opportunities = usePoll((c) => c.get<OpportunitySummary[]>("/v1/opportunities", { limit: 6, min_score: 50 }), 15000);

  const s = status.data;
  const account = (risk.data?.account ?? null) as Record<string, unknown> | null;
  const live = s?.trading_mode === "live";
  const open = (positions.data ?? []).filter((p) => Number(p.quantity) !== 0);
  const openPnl = open.some((p) => p.unrealized_pnl != null)
    ? open.reduce((sum, p) => sum + Number(p.unrealized_pnl ?? 0), 0)
    : null;

  return (
    <div className="page" data-testid="page-dashboard">
      <ErrorBox error={status.error} what="Motor" />
      <GettingStarted mode={s?.trading_mode} />
      <BalanceHero
        wallets={(account?.wallets as WalletInfo[] | undefined) ?? null}
        live={live}
        halted={Boolean(account?.halted)}
        haltReason={account?.halt_reason as string | null | undefined}
        accountError={risk.data?.account_error as string | null | undefined}
        onReleased={async () => {
          await risk.refresh();
          await status.refresh();
        }}
        age={account?.ts_age_s as number | undefined}
        onKeys={() => navigate("settings")}
      />
      <div className="kpis">
        <Kpi
          icon={<Wallet size={18} />}
          label="Hesap"
          tone={live ? "live" : undefined}
          value={<span data-testid="trading-mode">{MODE_LABELS[s?.trading_mode ?? ""] ?? "—"}</span>}
          hint={s?.can_open_positions ? "Yeni işlem açılabilir" : "Şu an yeni işlem açılamaz"}
        />
        <Kpi
          icon={<Gauge size={18} />}
          label="Günlük zarar"
          value={account ? pct(account.daily_loss_pct as number, 2, false) : "—"}
          hint="Sınır aşılınca bot o gün durur"
        />
        <Kpi
          icon={<Briefcase size={18} />}
          label="Açık pozisyon"
          value={open.length}
          hint={open.length ? <LivePnl value={openPnl} testId="open-pnl-total" /> : "Pozisyon yok"}
        />
      </div>

      <BotPanel />

      <div className="grid-2">
        <Card title="Açık pozisyonlar" actions={<button type="button" className="ghost" onClick={() => navigate("trading")}>Tümü</button>}>
          <DataTable
            rows={open}
            rowKey={(r) => `${r.market}-${r.symbol}`}
            empty="Açık pozisyon yok. Bot uygun sinyalde risk kapısından geçerek açar."
            columns={[
              { key: "s", label: "Coin", render: (r) => <b>{r.symbol}</b> },
              { key: "m", label: "Piyasa", render: (r) => MARKET_LABELS[r.market] ?? r.market },
              {
                key: "d",
                label: "Yön",
                render: (r) => <Badge tone={Number(r.quantity) > 0 ? "up" : "down"}>{Number(r.quantity) > 0 ? "Long" : "Short"}</Badge>,
              },
              { key: "e", label: "Giriş", align: "right", render: (r) => price(r.entry_price) },
              { key: "mk", label: "Fiyat", align: "right", render: (r) => (r.mark_price ? price(r.mark_price) : "—") },
              {
                key: "upnl",
                label: "Anlık K/Z",
                align: "right",
                render: (r) => <LivePnl value={r.unrealized_pnl} pct={r.pnl_pct} testId={`dash-pnl-${r.symbol}`} />,
              },
              { key: "p", label: "Stop", render: (r) => (r.protected ? <Badge tone="ok">Var</Badge> : <Badge tone="bad">Yok</Badge>) },
            ]}
          />
        </Card>
        <Card title="En iyi fırsatlar" actions={<button type="button" className="ghost" onClick={() => navigate("opportunities")}>Tümü</button>}>
          <ErrorBox error={opportunities.error} what="Fırsat taraması" />
          <DataTable
            rows={opportunities.data}
            rowKey={(r) => `${r.market}-${r.symbol}`}
            empty="Tarama sürüyor ya da şu an 50 puan üstü fırsat yok"
            columns={[
              { key: "symbol", label: "Coin", render: (r) => <b>{r.symbol}</b> },
              { key: "market", label: "Piyasa", render: (r) => MARKET_LABELS[r.market] },
              { key: "dir", label: "Yön", render: (r) => <Badge tone={r.direction === "long" ? "up" : "down"}>{r.direction === "long" ? "Long" : "Short"}</Badge> },
              { key: "score", label: "Puan", align: "right", render: (r) => <b>{num(r.score, 0)}</b> },
              { key: "rr", label: "Ödül/Risk", align: "right", render: (r) => num(r.reward_risk, 2) },
            ]}
          />
        </Card>
      </div>

      <TradeHistory compact limit={50} onMore={() => navigate("trading")} />

      <details className="card system-details" open={s ? s.engine_state !== "running" : false}>
        <summary>
          Sistem durumu · <Badge tone={stateTone(s?.engine_state)} testId="engine-state">{STATE_LABELS[s?.engine_state ?? ""] ?? "—"}</Badge>
          <span className="muted small"> · çalışma {duration(s?.uptime_s)} · gecikme {num(s?.loop_lag.p99_ms, 1)} ms · sürüm {s?.version ?? "—"}</span>
        </summary>
        <div className="card-body">
          {s && s.engine_state !== "running" && <p className="muted small">{s.state_reason}</p>}
          <ul className="conditions" data-testid="conditions">
            {(s?.readiness ?? [])
              // Gerçek parada deneme hesabının, denemede gerçek hesabın koşulu gösterilmez.
              .filter((c) => (live ? c.name !== "risk.daily_loss" : !c.name.startsWith("live.")))
              .map((c) => (
              <li key={c.name}>
                <Badge tone={c.ready ? "ok" : "warn"}>{c.ready ? "Hazır" : "Bekliyor"}</Badge>{" "}
                <b title={c.name}>{CONDITION_LABELS[c.name] ?? c.name}</b> <span className="muted">{c.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      </details>
      <Disclaimer />
    </div>
  );
}
