import { describe, expect, it } from "vitest";

import { phraseMatches } from "./ui";

describe("onay ifadesi", () => {
  it("Türkçe klavyeyle yazılan büyük/küçük harf ve noktalı/noktasız i farkını kabul eder", () => {
    expect(phraseMatches("SERBEST BIRAK", "SERBEST BIRAK")).toBe(true);
    expect(phraseMatches("SERBEST BİRAK", "SERBEST BIRAK")).toBe(true);
    expect(phraseMatches("serbest bırak", "SERBEST BIRAK")).toBe(true);
    expect(phraseMatches("  serbest   birak ", "SERBEST BIRAK")).toBe(true);
    expect(phraseMatches("KİLİDİ KALDIR", "KILIDI KALDIR")).toBe(true);
    expect(phraseMatches("Gerçek para ile işlem yapılmasını onaylıyorum", "GERCEK PARA ILE ISLEM YAPILMASINI ONAYLIYORUM")).toBe(true);
  });

  it("farklı ya da eksik ifadeyi reddeder", () => {
    expect(phraseMatches("SERBEST", "SERBEST BIRAK")).toBe(false);
    expect(phraseMatches("SERBEST BIRAKMA", "SERBEST BIRAK")).toBe(false);
    expect(phraseMatches("", "SERBEST BIRAK")).toBe(false);
  });
});
