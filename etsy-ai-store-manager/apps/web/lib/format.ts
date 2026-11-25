/** Formats a decimal string for display only. Calculations never use these values. */
export function formatMoney(value: string | null | undefined, currency: string): string {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return new Intl.NumberFormat('tr-TR', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(n);
}

export function formatPercent(rate: string | null | undefined): string {
  if (rate === null || rate === undefined) return '—';
  return new Intl.NumberFormat('tr-TR', { style: 'percent', maximumFractionDigits: 2 }).format(
    Number(rate),
  );
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('tr-TR', { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(iso),
  );
}
