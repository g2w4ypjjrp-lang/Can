// Paket fiyatı: kampanya varsa indirimsiz fiyat üstü çizili ve "%X indirim" rozetiyle.
// Sunucu ve tarayıcı bileşenlerinde kullanılabilir (durum tutmaz).

import { formatPrice } from "@/lib/format";

export function PriceTag({
  minor,
  currency,
  listMinor,
  percent,
  className = "",
  priceClassName = "text-xl font-semibold tracking-tight text-fg",
  testId,
}: {
  minor: number;
  currency: string;
  listMinor?: number | null;
  percent?: number | null;
  className?: string;
  priceClassName?: string;
  testId?: string;
}) {
  const discounted = Boolean(percent && listMinor && listMinor > minor);
  return (
    <span className={`inline-flex flex-wrap items-baseline gap-x-2 gap-y-1 ${className}`} data-testid={testId}>
      {discounted ? (
        <s className="tabular text-sm font-medium text-muted" data-testid={testId ? `${testId}-list` : undefined}>
          <span className="visually-hidden">İndirimsiz fiyat: </span>
          {formatPrice(listMinor as number, currency)}
        </s>
      ) : null}
      <span className={`tabular ${priceClassName}`}>
        {discounted ? <span className="visually-hidden">Kampanyalı fiyat: </span> : null}
        {formatPrice(minor, currency)}
      </span>
      {discounted ? (
        <span className="rounded-full border border-success-border bg-success-bg px-2 py-0.5 text-xs font-semibold text-success-fg">
          %{percent} indirim
        </span>
      ) : null}
    </span>
  );
}
