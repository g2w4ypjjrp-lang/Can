import { describe, expect, it } from "vitest";
import { applyPriceTick, resetLivePrices, withLivePrices } from "./livePrices";

describe("anlık fiyat", () => {
  const long = { market: "usdm_futures", symbol: "BTCUSDT", quantity: "0.004", entry_price: "96120.5", unrealized_pnl: "1" as string | number | null, pnl_pct: 0 as number | null };
  const short = { market: "usdm_futures", symbol: "SOLUSDT", quantity: "-3", entry_price: "182.4", unrealized_pnl: null as string | number | null, pnl_pct: null as number | null };

  it("her yeni fiyatta kâr/zararı yeniden hesaplar (long ve short)", () => {
    const [l, s] = withLivePrices([long, short], { "usdm_futures:BTCUSDT": 96220.5, "usdm_futures:SOLUSDT": 182.3 })!;
    expect(Number(l!.unrealized_pnl)).toBeCloseTo(0.4, 6); // 100 x 0,004
    expect(l!.pnl_pct).toBeCloseTo(0.104, 3);
    expect(Number(s!.unrealized_pnl)).toBeCloseTo(0.3, 6); // short: fiyat 0,1 düştü x 3
    expect(s!.pnl_pct).toBeGreaterThan(0);
  });

  it("anlık fiyat yoksa motorun değeri kalır; geçersiz fiyat yok sayılır", () => {
    resetLivePrices();
    applyPriceTick({ "usdm_futures:BTCUSDT": "yok" });
    expect(withLivePrices([long], {})![0]).toBe(long);
    expect(withLivePrices(undefined, {})).toBeUndefined();
  });
});
