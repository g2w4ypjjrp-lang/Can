export type Money = { currency: string; amount: string };
export type Metric<T> = { value: T | null; status: "ok" | "no_data" | "not_connected"; as_of?: string | null };

export const STATUS_TEXT: Record<Metric<unknown>["status"], string> = {
  ok: "",
  no_data: "Henüz veri yok",
  not_connected: "Bağlı değil",
};

export function formatNumber(n: number | string, locale = "tr-TR"): string {
  return new Intl.NumberFormat(locale).format(Number(n));
}

export function formatMoney(list: Money[], locale = "tr-TR"): string[] {
  return list.map((m) =>
    new Intl.NumberFormat(locale, { style: "currency", currency: m.currency }).format(Number(m.amount)));
}

/** Metrik gösterimi: veri yoksa asla 0 veya örnek sayı göstermez. */
export function metricText(m: Metric<number | string>): string {
  return m.status === "ok" && m.value !== null ? formatNumber(m.value) : STATUS_TEXT[m.status];
}
