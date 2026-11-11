import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import type { StatusResponse, TradingModeResponse } from "../api/types.gen";
import { MODE_LABELS } from "../lib/format";
import { Confirm, ErrorBox } from "./ui";

export const LIVE_PHRASE = "GERCEK PARA ILE ISLEM YAPILMASINI ONAYLIYORUM";

const OPTIONS: { mode: "paper" | "testnet" | "live"; label: string; hint: string }[] = [
  { mode: "paper", label: "Sanal", hint: "Emir gönderilmez" },
  { mode: "testnet", label: "Demo para", hint: "Binance Demo Trading, sahte bakiye" },
  { mode: "live", label: "Gerçek para", hint: "Gerçek Binance hesabı" },
];

/** İşlem modu seçici: Sanal / Demo para / Gerçek para. Gerçek para için onay ifadesi yazılır;
 * motor ayrıca gerçek hesap anahtarını (para çekme yetkisi kapalı), lisansı ve acil durdurmayı
 * denetler. ``compact`` botta kullanılır (yalnızca Demo / Gerçek). */
export function ModeSwitch({ compact = false, onChanged }: { compact?: boolean; onChanged?: () => void }) {
  const status = usePoll((c) => c.get<StatusResponse>("/v1/status"), 3000);
  const [askLive, setAskLive] = useState(false);
  const [result, setResult] = useState<TradingModeResponse | null>(null);
  const setMode = useAction(async (c, mode: string, acknowledgement?: string) => {
    try {
      return await c.post<TradingModeResponse>("/v1/trading-mode", { mode, acknowledgement: acknowledgement ?? null });
    } catch (e) {
      const detail = (e as { detail?: unknown }).detail;
      if (detail && typeof detail === "object" && "checks" in (detail as object)) return detail as TradingModeResponse;
      throw e;
    }
  });
  const current = status.data?.trading_mode;

  async function choose(mode: string, acknowledgement?: string) {
    setResult((await setMode.execute(mode, acknowledgement)) ?? null);
    await status.refresh();
    onChanged?.();
  }

  const options = compact ? OPTIONS.filter((o) => o.mode !== "paper") : OPTIONS;
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="mode-switch" role="radiogroup" aria-label="İşlem modu" data-testid={compact ? "bot-mode" : "mode-switch"}>
        {options.map((o) => (
          <button
            key={o.mode}
            type="button"
            role="radio"
            aria-checked={current === o.mode}
            className={`${current === o.mode ? "active" : ""} ${o.mode === "live" ? "live" : ""}`}
            disabled={setMode.pending || current === o.mode}
            onClick={() => (o.mode === "live" ? setAskLive(true) : void choose(o.mode))}
            data-testid={`${compact ? "bot-" : ""}mode-${o.mode}`}
          >
            <b>{o.label}</b>
            <small>{o.hint}</small>
          </button>
        ))}
      </div>
      {current === "live" && (
        <div className="notice danger-notice" data-testid="live-banner">
          <AlertTriangle aria-hidden="true" size={16} /> <b>GERÇEK PARA modu açık.</b> İşlemler gerçek Binance hesabınızda yapılır;
          kayıp riski vardır. Uygulama yeniden başlarsa güvenlik için sanal moda döner.
        </div>
      )}
      <ErrorBox error={setMode.error} />
      {result && !result.accepted && (
        <ul className="reasons" data-testid="mode-checks">
          {result.checks
            .filter((c) => !c.passed)
            .map((c) => (
              <li key={c.name} className="down">
                {c.message}
              </li>
            ))}
        </ul>
      )}
      <Confirm
        open={askLive}
        title="Gerçek para ile işlem"
        confirmLabel="Gerçek parayı aç"
        danger
        phrase={LIVE_PHRASE}
        onCancel={() => setAskLive(false)}
        onConfirm={() => {
          setAskLive(false);
          void choose("live", LIVE_PHRASE);
        }}
      >
        <ul className="small">
          <li>İşlemler (bot dahil) gerçek Binance hesabınızda gerçek parayla yapılır. Kâr garantisi yoktur; kaybedebilirsiniz.</li>
          <li>Gerekenler: para çekme yetkisi KAPALI gerçek hesap anahtarı (Ayarlar), geçerli lisans, acil durdurmanın kapalı olması.</li>
          <li>Risk sınırları aynen uygulanır: zarar durdur zorunlu, işlem başına risk, günlük zarar ve kaldıraç sınırları.</li>
          <li>Uygulama yeniden başladığında güvenlik için sanal moda döner; gerçek parayı her seferinde yeniden onaylarsınız.</li>
        </ul>
      </Confirm>
      {!compact && current && <span className="muted small">Şu an: {MODE_LABELS[current] ?? current}</span>}
    </div>
  );
}
