// Satıcı bilgileri (sunucu tarafı): ön bilgilendirme formu ve mesafeli satış sözleşmesinde
// yasal olarak yer alır. Yönetim panelindeki "Şirket bilgileri"nden gelir; boş alanlar köşeli
// parantezli yer tutucuyla gösterilir.

import { runtimeConfig } from "@/lib/config";

export interface Seller {
  legal_name: string;
  address: string;
  tax_office: string;
  tax_number: string;
  mersis: string;
  kep: string;
  email: string;
  phone: string;
}

export const SELLER_PLACEHOLDERS: Seller = {
  legal_name: "[Şirket unvanı]",
  address: "[Adres]",
  tax_office: "[Vergi dairesi]",
  tax_number: "[Vergi kimlik no]",
  mersis: "[MERSİS no]",
  kep: "[KEP adresi]",
  email: "[E-posta]",
  phone: "[Telefon]",
};

/** Boş alanları yer tutucuyla doldurur. */
export function withPlaceholders(seller: Partial<Seller> | null): Seller {
  const out = { ...SELLER_PLACEHOLDERS };
  for (const key of Object.keys(out) as (keyof Seller)[]) {
    const value = seller?.[key];
    if (typeof value === "string" && value.trim()) out[key] = value.trim();
  }
  return out;
}

export async function fetchSeller(fetcher: typeof fetch = fetch): Promise<Seller> {
  const cfg = runtimeConfig();
  try {
    const response = await fetcher(`${cfg.serverApiUrl}/v1/legal/seller`, {
      signal: AbortSignal.timeout(3000),
      cache: "no-store",
    });
    if (!response.ok) return withPlaceholders(null);
    return withPlaceholders((await response.json()) as Partial<Seller>);
  } catch {
    return withPlaceholders(null);
  }
}
