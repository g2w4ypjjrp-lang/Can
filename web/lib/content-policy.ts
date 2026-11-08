// Pazarlama metni kuralı: hiçbir sayfada kazanç vaadi bulunamaz. Testler (birim + uçtan uca)
// tüm sayfa metinlerini bu denetimden geçirir.

const FORBIDDEN: RegExp[] = [
  /garantili\s+(kazanç|kâr|kar|getiri|gelir)/iu,
  /garanti\s+(edilen|edilmiş)\s+(kazanç|kâr|kar|getiri|gelir)/iu,
  /(kazanç|kâr|kar|getiri)\s+garantisi(?!\s+(sunmaz|vermez|verilmez|yoktur|değildir|sunulmaz|içermez))/iu,
  /(kesin|sabit|risksiz|riskten\s+arındırılmış)\s+(kazanç|kâr|kar|getiri|gelir)/iu,
  /%\s?\d+\s+(kazanç|kâr|getiri)\s+(garanti|kesin)/iu,
  /(kaybetme(z|niz\s+imkânsız)|zarar\s+etmezsiniz|asla\s+kaybetmezsiniz)/iu,
  /(pasif\s+gelir|zengin\s+ol|para\s+basan|kazandıran\s+bot)/iu,
];

export function findForbiddenClaims(text: string): string[] {
  const hits: string[] = [];
  for (const pattern of FORBIDDEN) {
    const match = text.match(pattern);
    if (match) hits.push(match[0]);
  }
  return hits;
}

/** Her sayfanın altında bulunması gereken risk uyarısının ayırt edici ifadesi. */
export const RISK_NOTICE_MARKER = "yatırım tavsiyesi vermez";
