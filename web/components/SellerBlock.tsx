import type { Seller } from "@/lib/seller";

/** Satıcı kimlik bilgileri (yasal metinlerde). */
export function SellerBlock({ seller }: { seller: Seller }) {
  const rows: [string, string][] = [
    ["Unvan", seller.legal_name],
    ["Adres", seller.address],
    ["Vergi dairesi / no", `${seller.tax_office} / ${seller.tax_number}`],
    ["MERSİS no", seller.mersis],
    ["KEP adresi", seller.kep],
    ["E-posta", seller.email],
    ["Telefon", seller.phone],
  ];
  return (
    <dl className="not-prose grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[11rem_1fr]">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted">{label}</dt>
          <dd className="text-fg">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
