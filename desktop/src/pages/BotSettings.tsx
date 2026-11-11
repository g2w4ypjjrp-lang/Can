import { SlidersHorizontal } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import { ModeSwitch } from "../components/ModeSwitch";
import { Badge, Card, ErrorBox, Field } from "../components/ui";
import { MARKET_LABELS } from "../lib/format";

interface BotSettings {
  markets: string[];
  min_score: number;
  risk_per_trade_pct: string;
  leverage: number;
  max_entries_per_hour: number;
  symbol_cooldown_s: number;
  trailing_runner: boolean;
  max_consecutive_losses: number;
  loss_pause_minutes: number;
}

interface AutoTradeStatus {
  enabled: boolean;
  environment?: "paper" | "testnet" | "live";
  settings: BotSettings;
  defaults: BotSettings;
  limits: { max_risk_per_trade_pct: string; max_leverage: number };
  loss_streak?: number;
  paused_until_ms?: number | null;
  results?: { wins: number; losses: number };
}

type Form = {
  min_score: string;
  risk: string;
  leverage: string;
  per_hour: string;
  cooldown_min: string;
  markets: string[];
  trailing: boolean;
  losses: string;
  pause_min: string;
};

function toForm(s: BotSettings): Form {
  return {
    min_score: String(s.min_score),
    risk: String(s.risk_per_trade_pct),
    leverage: String(s.leverage),
    per_hour: String(s.max_entries_per_hour),
    cooldown_min: String(Math.round(s.symbol_cooldown_s / 60)),
    markets: s.markets,
    trailing: s.trailing_runner,
    losses: String(s.max_consecutive_losses),
    pause_min: String(s.loss_pause_minutes),
  };
}

/** Bot (otomatik işlem) ayarları. Risk sınırları üst sınırdır; burada gevşetilemez. Değişiklik
 * denetim kaydına yazılır. Bot yalnızca Demo Trading'de işlem açar. */
export function BotSettingsCard() {
  const auto = usePoll((c) => c.get<AutoTradeStatus>("/v1/autotrade"), 15_000);
  const save = useAction((c, body: unknown) => c.post<AutoTradeStatus>("/v1/autotrade/settings", body));
  const reset = useAction((c) => c.post<AutoTradeStatus>("/v1/autotrade/settings/reset"));
  const [form, setForm] = useState<Form | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const s = auto.data;

  useEffect(() => {
    if (s && form === null) setForm(toForm(s.settings));
  }, [s, form]);

  if (!s || !form) {
    return (
      <Card title="Bot ayarları" testId="bot-settings">
        <ErrorBox error={auto.error} what="Bot ayarları" />
      </Card>
    );
  }

  const set = (key: keyof Form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    setMessage(null);
    const result = await save.execute({
      min_score: Number(form.min_score),
      risk_per_trade_pct: form.risk.replace(",", "."),
      leverage: Number(form.leverage),
      max_entries_per_hour: Number(form.per_hour),
      symbol_cooldown_s: Number(form.cooldown_min) * 60,
      markets: form.markets,
      trailing_runner: form.trailing,
      max_consecutive_losses: Number(form.losses),
      loss_pause_minutes: Number(form.pause_min),
    });
    if (result) {
      setForm(toForm(result.settings));
      setMessage("Kaydedildi. Yeni ayarlar bir sonraki sinyalden itibaren geçerli.");
      await auto.refresh();
    }
  }

  return (
    <Card
      title="Bot ayarları"
      testId="bot-settings"
      actions={
        <div className="row">
          {s.environment === "live" && <Badge tone="bad">GERÇEK PARA</Badge>}
          <Badge tone={s.enabled ? "ok" : "neutral"} testId="bot-settings-state">
            Bot {s.enabled ? "çalışıyor" : "durdu"}
          </Badge>
        </div>
      }
    >
      <div className="stack" style={{ gap: 6, marginBottom: 12 }}>
        <span className="small">
          <b>Bot hangi hesapla işlem yapsın?</b>{" "}
          {s.environment === "paper" && <span className="muted">(şu an Sanal: bot işlem açmaz)</span>}
        </span>
        <ModeSwitch compact onChanged={() => void auto.refresh()} />
      </div>
      <form className="stack" onSubmit={submit}>
        <p className="muted small" style={{ display: "flex", gap: 8 }}>
          <SlidersHorizontal aria-hidden="true" size={16} style={{ flexShrink: 0, marginTop: 2 }} />
          Bot, puanı eşik üstündeki fırsatlarda seçili hesapta (Demo para ya da Gerçek para) işlem açar. Her işlem yine
          risk kapısından geçer; zarar durdur zorunludur. Sonuçlar garanti değildir.
        </p>
        <div className="grid-2">
          <Field label="En düşük fırsat puanı" hint="50–100. Yükseldikçe daha az ama daha seçici işlem.">
            <input type="number" min={50} max={100} step={1} value={form.min_score} onChange={set("min_score")} data-testid="bot-min-score" />
          </Field>
          <Field label="İşlem başına risk (%)" hint={`Zarar durdurda kaybedilecek pay. Üst sınır %${s.limits.max_risk_per_trade_pct}.`}>
            <input inputMode="decimal" value={form.risk} onChange={set("risk")} data-testid="bot-risk" />
          </Field>
          <Field label="Kaldıraç (futures)" hint={`Üst sınır ${s.limits.max_leverage}x.`}>
            <input type="number" min={1} max={s.limits.max_leverage} step={1} value={form.leverage} onChange={set("leverage")} data-testid="bot-leverage" />
          </Field>
          <Field label="Saatte en fazla giriş" hint="1–20">
            <input type="number" min={1} max={20} step={1} value={form.per_hour} onChange={set("per_hour")} data-testid="bot-per-hour" />
          </Field>
          <Field label="Aynı sembolde bekleme (dakika)" hint="Bir sembolde işlemden sonra yeniden girmeden önce. 1–1440">
            <input type="number" min={1} max={1440} step={1} value={form.cooldown_min} onChange={set("cooldown_min")} data-testid="bot-cooldown" />
          </Field>
          <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
            <span>Piyasalar</span>
            <div className="row">
              {(["usdm_futures", "spot"] as const).map((m) => (
                <label key={m} className="row" style={{ gap: 6 }}>
                  <input
                    type="checkbox"
                    checked={form.markets.includes(m)}
                    onChange={(e) =>
                      setForm({ ...form, markets: e.target.checked ? [...form.markets, m] : form.markets.filter((x) => x !== m) })
                    }
                    data-testid={`bot-market-${m}`}
                  />
                  {MARKET_LABELS[m]}
                </label>
              ))}
            </div>
            <small>Spot'ta yalnızca alış (long) yapılır.</small>
          </fieldset>
        </div>
        <h4>Pozisyon yönetimi</h4>
        <label className="row" style={{ gap: 8 }}>
          <input
            type="checkbox"
            checked={form.trailing}
            onChange={(e) => setForm({ ...form, trailing: e.target.checked })}
            data-testid="bot-trailing"
          />
          <span>
            Kârı iz süren stopla koştur (Futures)
            <small className="muted" style={{ display: "block" }}>
              Pozisyonun yarısı 1R'de alınır, zarar durdur girişe çekilir; kalan yarı sabit hedef yerine fiyatı izleyen stopla
              taşınır. Kapalıysa ikinci yarı sabit hedefte kapanır.
            </small>
          </span>
        </label>
        <div className="grid-2">
          <Field label="Art arda kayıp sınırı" hint="Bu kadar zararlı pozisyondan sonra bot yeni işleme mola verir. 0 = kapalı.">
            <input type="number" min={0} max={10} step={1} value={form.losses} onChange={set("losses")} data-testid="bot-losses" />
          </Field>
          <Field label="Mola süresi (dakika)" hint="15–2880">
            <input type="number" min={15} max={2880} step={15} value={form.pause_min} onChange={set("pause_min")} data-testid="bot-pause" />
          </Field>
        </div>
        {(s.loss_streak ?? 0) > 0 || s.paused_until_ms ? (
          <p className={s.paused_until_ms ? "notice" : "muted small"} data-testid="bot-streak">
            Art arda kayıp: {s.loss_streak ?? 0}
            {s.paused_until_ms ? ` · bot ${new Date(s.paused_until_ms).toLocaleTimeString("tr-TR")} saatine kadar molada` : ""}
          </p>
        ) : null}
        {s.results && s.results.wins + s.results.losses > 0 ? (
          <p className="muted small" data-testid="bot-results">
            Bu oturumda bot pozisyonları: {s.results.wins} kârlı, {s.results.losses} zararlı kapandı.
          </p>
        ) : null}
        <div className="row">
          <button type="submit" className="primary" disabled={save.pending} data-testid="bot-save">
            Kaydet
          </button>
          <button
            type="button"
            disabled={reset.pending}
            onClick={async () => {
              const result = await reset.execute();
              if (result) {
                setForm(toForm(result.settings));
                setMessage("Varsayılan ayarlara dönüldü.");
                await auto.refresh();
              }
            }}
            data-testid="bot-reset"
          >
            Varsayılana dön
          </button>
          {message && (
            <span className="muted small" role="status" data-testid="bot-message">
              {message}
            </span>
          )}
        </div>
        <ErrorBox error={save.error ?? reset.error} />
      </form>
    </Card>
  );
}
