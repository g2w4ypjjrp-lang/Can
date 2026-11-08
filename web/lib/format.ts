// Biçimlendirme ve güvenli yönlendirme yardımcıları (sunucu ve tarayıcı ortak).

export function formatPrice(minor: number, currency: string): string {
  if (minor === 0) return "Ücretsiz";
  let format: Intl.NumberFormat;
  try {
    format = new Intl.NumberFormat("tr-TR", { style: "currency", currency });
  } catch {
    return `${(minor / 100).toFixed(2)} ${currency}`;
  }
  const digits = format.resolvedOptions().maximumFractionDigits ?? 2;
  return format.format(minor / 10 ** digits);
}

export function durationLabel(days: number | null): string {
  if (days === null) return "Süresiz";
  return `${days} gün`;
}

export function deviceLabel(count: number): string {
  return `${count} bilgisayar`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("tr-TR", { dateStyle: "long", timeZone: "Europe/Istanbul" }).format(date);
}

const LICENSE_STATUS: Record<string, string> = {
  generated: "Hazırlanıyor",
  ready_for_sale: "Hazırlanıyor",
  sold: "Etkinleştirilmeyi bekliyor",
  active: "Etkin",
  expired: "Süresi doldu",
  cancelled: "İptal edildi",
  frozen: "Donduruldu",
};

export function licenseStatusLabel(status: string): string {
  return LICENSE_STATUS[status] ?? status;
}

/**
 * Giriş sonrası dönüş adresi. Yalnızca site içi göreli yol kabul edilir; "//kotu.site",
 * "/\\kotu.site", "https://…" gibi açık yönlendirme denemeleri panele düşer.
 */
export function safeNext(value: string | string[] | null | undefined, fallback = "/panel"): string {
  const next = Array.isArray(value) ? value[0] : value;
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  if (/[\u0000-\u001f\\]/.test(next)) return fallback;
  return next;
}

export function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
