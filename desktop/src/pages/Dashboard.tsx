import { useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import type { OpportunitySummary, StatusResponse, WhaleAlertInfo } from "../api/types.gen";
import { BotPanel } from "../components/BotPanel";
import { GettingStarted } from "../components/GettingStarted";
import { Badge, Card, Confirm, DataTable, Disclaimer, ErrorBox, Stat } from "../components/ui";
import { duration, MARKET_LABELS, MODE_LABELS, num, pct, price, STATE_LABELS, time } from "../lib/format";

const RELEASE_PHRASE = "SERBEST BIRAK";

export function stateTone(state?: string): "ok" | "warn" | "bad" | "neutral" {
  if (state === "running") return "ok";
  if (state === "safe_mode" || state === "starting") return "warn";
  if (state === "halted") return "bad";
  return "neutral";
}

export function Dashboard() {
  const status = usePoll((c) => c.get<StatusResponse>("/v1/status"), 2000);
  const risk = usePoll((c) => c.get<Record<string, unknown>>("/v1/risk/status"), 5000);
  const opportunities = usePoll((c) => c.get<OpportunitySummary[]>("/v1/opportunities", { limit: 8, min_score: 50 }), 15000);
  const whales = usePoll((c) => c.get<WhaleAlertInfo[]>("/v1/whales/alerts", { limit: 8 }), 10000);
  const [askEngage, setAskEngage] = useState(false);
  const [askRelease, setAskRelease] = useState(false);

  const engage = useAction((c) => c.post("/v1/kill-switch/engage", { reason: "Kullanıcı arayüzden durdurdu" }));
  const release = useAction((c) => c.post("/v1/kill-switch/release", { confirmation: RELEASE_PHRASE }));

  const s = status.data;
  const account = (risk.data?.account ?? null) as Record<string, unknown> | null;
  const engaged = s?.kill_switch.engaged ?? false;

  return (
    <div className="page" data-testid="page-dashboard">
      <ErrorBox error={status.error} what="Motor durumu" />
      <GettingStarted />
      <BotPanel />
      <div className="stats">
        <Stat
          label="Motor"
          value={<Badge tone={stateTone(s?.engine_state)} testId="engine-state">{STATE_LABELS[s?.engine_state ?? ""] ?? "—"}</Badge>}
          hint={s?.state_reason}
        />
        <Stat label="İşlem modu" value={<span data-testid="trading-mode">{MODE_LABELS[s?.trading_mode ?? ""] ?? "—"}</span>} hint={s?.can_open_positions ? "Yeni işlem açılabilir" : "Yeni işlem açılamaz"} />
        <Stat label="Çalışma süresi" value={duration(s?.uptime_s)} hint={`Sürüm ${s?.version ?? "—"}`} />
        <Stat label="Döngü gecikmesi (p99)" value={`${num(s?.loop_lag.p99_ms, 1)} ms`} tone={(s?.loop_lag.p99_ms ?? 0) > 250 ? "warn" : undefined} />
        <Stat
          label="Günlük zarar"
          value={account ? pct(account.daily_loss_pct as number, 2, false) : "—"}
          hint={account ? (account.halted ? "Gün kilitli" : `Özsermaye ${price(account.equity as string)}`) : "Demo anahtarı bağlı değil"}
          tone={account?.halted ? "down" : undefined}
        />
      </div>

      <div className="grid-2">
        <Card title="Acil durdurma" testId="controls">
          <p className="muted">
            Acil durdurma yeni işlemleri hemen durdurur; açık pozisyonların borsadaki stopları yerinde kalır.
          </p>
          <div className="row">
            {engaged ? (
              <button className="primary" onClick={() => setAskRelease(true)} data-testid="kill-release">
                Acil durdurmayı kaldır
              </button>
            ) : (
              <button className="danger big" onClick={() => setAskEngage(true)} data-testid="kill-engage">
                ACİL DURDUR
              </button>
            )}
            {engaged && <Badge tone="bad">Devrede: {s?.kill_switch.reason}</Badge>}
          </div>
          <ErrorBox error={engage.error ?? release.error} />
        </Card>

        <Card title="Hazırlık koşulları">
          <ul className="conditions" data-testid="conditions">
            {(s?.readiness ?? []).map((c) => (
              <li key={c.name}>
                <Badge tone={c.ready ? "ok" : "warn"}>{c.ready ? "Hazır" : "Bekliyor"}</Badge> <code>{c.name}</code>{" "}
                <span className="muted">{c.detail}</span>
              </li>
            ))}
            {s && s.readiness.length === 0 && <li className="muted">Kayıtlı koşul yok</li>}
          </ul>
        </Card>
      </div>

      <div className="grid-2">
        <Card title="En iyi fırsatlar">
          <ErrorBox error={opportunities.error} what="Fırsat motoru" />
          <DataTable
            rows={opportunities.data}
            rowKey={(r) => `${r.market}-${r.symbol}`}
            empty="Henüz eşik üstü fırsat yok"
            columns={[
              { key: "symbol", label: "Sembol", render: (r) => <b>{r.symbol}</b> },
              { key: "market", label: "Piyasa", render: (r) => MARKET_LABELS[r.market] },
              { key: "dir", label: "Yön", render: (r) => <Badge tone={r.direction === "long" ? "up" : "down"}>{r.direction === "long" ? "Long" : "Short"}</Badge> },
              { key: "score", label: "Puan", align: "right", render: (r) => num(r.score, 0) },
              { key: "rr", label: "Ödül/Risk", align: "right", render: (r) => num(r.reward_risk, 2) },
            ]}
          />
        </Card>
        <Card title="Son balina uyarıları">
          <ErrorBox error={whales.error} what="Balina radarı" />
          <DataTable
            rows={whales.data}
            rowKey={(r, i) => `${r.ts_ms}-${i}`}
            empty="Uyarı yok"
            columns={[
              { key: "t", label: "Zaman", render: (r) => time(r.ts_ms) },
              { key: "s", label: "Sembol", render: (r) => r.symbol },
              { key: "m", label: "Olay", render: (r) => r.message },
            ]}
          />
        </Card>
      </div>
      <Disclaimer />

      <Confirm
        open={askEngage}
        title="Acil durdurma"
        danger
        confirmLabel="Durdur"
        onCancel={() => setAskEngage(false)}
        onConfirm={async () => {
          setAskEngage(false);
          await engage.execute();
          await status.refresh();
        }}
      >
        Yeni işlem açılması hemen durdurulacak. Devam edilsin mi?
      </Confirm>
      <Confirm
        open={askRelease}
        title="Acil durdurmayı kaldır"
        phrase={RELEASE_PHRASE}
        confirmLabel="Kaldır"
        onCancel={() => setAskRelease(false)}
        onConfirm={async () => {
          setAskRelease(false);
          await release.execute();
          await status.refresh();
        }}
      >
        Motor güvenlik koşulları sağlanınca yeniden işlem açabilir hâle gelir.
      </Confirm>
    </div>
  );
}
