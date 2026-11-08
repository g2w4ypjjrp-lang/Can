import { describe, expect, it } from "vitest";
import { compact, duration, num, pct, price, toNumber, tone, usd } from "./format";

describe("biçimlendirme", () => {
  it("motorun metin ondalıklarını sayıya çevirir", () => {
    expect(toNumber("116.279")).toBe(116.279);
    expect(toNumber("")).toBeNull();
    expect(toNumber("abc")).toBeNull();
    expect(toNumber(undefined)).toBeNull();
  });
  it("Türkçe ondalık ve binlik ayırıcı kullanır", () => {
    expect(num(1234.5, 2)).toBe("1.234,50");
    expect(num(null)).toBe("—");
    expect(pct(2.5)).toBe("+2,50%");
    expect(pct(-1)).toBe("-1,00%");
    expect(pct(3, 1, false)).toBe("3,0%");
    expect(usd(-12.5)).toBe("-$12,50");
  });
  it("fiyatı büyüklüğe göre basamaklar", () => {
    expect(price(75628.5)).toBe("75.628,5");
    expect(price("0.00001234")).toBe("0,00001234");
  });
  it("büyük sayıları kısaltır", () => {
    expect(compact(1_234_567)).toBe("1,23 Mn");
    expect(compact(2_500_000_000)).toBe("2,50 Mr");
    expect(compact(950)).toBe("950");
  });
  it("süre ve yön", () => {
    expect(duration(3725)).toBe("1 sa 2 dk");
    expect(duration(42)).toBe("42 sn");
    expect(tone("-0.1")).toBe("down");
    expect(tone(0)).toBe("flat");
  });
});
