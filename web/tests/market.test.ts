import { describe, expect, it } from "vitest";

import { formatChange, formatQuote, parseQuotes } from "@/lib/market";

describe("canlı piyasa verisi", () => {
  it("Binance 24 saatlik özetinden fiyat ve yüzde değişim", () => {
    const quotes = parseQuotes([
      { symbol: "BTCUSDT", openPrice: "70000", lastPrice: "71400" },
      { symbol: "ETHUSDT", openPrice: "2000", lastPrice: "1950" },
      { symbol: "KOTU", openPrice: "1", lastPrice: "2" },
      { symbol: "XUSDT", openPrice: "1", lastPrice: "bozuk" },
      null,
    ]);
    expect(quotes.map((q) => q.base)).toEqual(["BTC", "ETH"]);
    expect(quotes[0]!.changePct).toBeCloseTo(2);
    expect(quotes[1]!.changePct).toBeCloseTo(-2.5);
    expect(parseQuotes({ code: -1121 })).toEqual([]);
  });

  it("biçimler", () => {
    expect(formatQuote(68764.01)).toBe("68.764,01");
    expect(formatQuote(1.23456)).toBe("1,235");
    expect(formatQuote(0.000012345)).toBe("0,00001235");
    expect(formatChange(2.5)).toBe("+2,50%");
    expect(formatChange(-0.456)).toBe("−0,46%");
  });
});
