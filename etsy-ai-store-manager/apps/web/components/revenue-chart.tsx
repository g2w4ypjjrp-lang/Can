import { formatMoney } from '@/lib/format';

/**
 * Dependency-free bar chart (SVG) of daily revenue. Renders an explicit empty
 * state when every value is zero, instead of drawing a misleading flat line.
 */
export function RevenueChart({
  data,
  currency,
}: {
  data: Array<{ date: string; revenue: string; orders: number }>;
  currency: string;
}) {
  const values = data.map((d) => Number(d.revenue));
  const max = Math.max(0, ...values);
  if (max === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-line text-sm text-slate-500">
        Bu dönemde kayıtlı satış yok
      </div>
    );
  }
  const w = 100 / data.length;
  return (
    <figure>
      <svg
        viewBox="0 0 100 50"
        preserveAspectRatio="none"
        className="h-48 w-full"
        role="img"
        aria-label="Günlük ciro grafiği"
      >
        {data.map((d, i) => {
          const h = (Number(d.revenue) / max) * 46;
          return (
            <rect
              key={d.date}
              x={i * w + w * 0.15}
              y={50 - h}
              width={w * 0.7}
              height={h}
              rx={0.4}
              className="fill-brand-500"
            >
              <title>{`${d.date}: ${formatMoney(d.revenue, currency)} · ${d.orders} sipariş`}</title>
            </rect>
          );
        })}
      </svg>
      <figcaption className="mt-2 flex justify-between text-xs text-slate-500">
        <span>{data[0]?.date}</span>
        <span>En yüksek gün: {formatMoney(String(max), currency)}</span>
        <span>{data[data.length - 1]?.date}</span>
      </figcaption>
    </figure>
  );
}
