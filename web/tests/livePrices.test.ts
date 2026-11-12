import { describe, expect, it } from "vitest";

import { totalBalance, withLivePrices } from "@/components/phone/PhoneDashboard";

describe("telefonda anlık fiyat", () => {
  const position = {
    market: "usdm_futures", symbol: "BTCUSDT", quantity: "0.004", entry_price: "96120.5", realized_pnl: "0", protected: true,
    mark_price: "96120.5", unrealized_pnl: "0", pnl_pct: 0,
  };

  it("her yeni fiyatta kâr/zarar ve bakiye anında değişir", () => {
    const [live] = withLivePrices([position], { "usdm_futures:BTCUSDT": 96120.6 })!;
    expect(Number(live!.unrealized_pnl)).toBeCloseTo(0.0004, 8); // 0,1 x 0,004
    expect(live!.mark_price).toBe("96120.6");
    const snap = {
      risk: { daily_loss_pct: 0, halted: false, equity: "100", wallets: [{ market: "usdm_futures", asset: "USDT", balance: "100", available: "90", unrealized_pnl: "5" }] },
    };
    expect(totalBalance(snap, null)).toBe(105);
    expect(totalBalance(snap, 7.5)).toBe(107.5);
  });

  it("anlık fiyat yoksa motorun son değeri kalır", () => {
    expect(withLivePrices([position], {})![0]).toBe(position);
  });
});
