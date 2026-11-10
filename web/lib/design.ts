// Site tasarım modu (yönetim paneli → Ayarlar → Site görünümü). Kaynak: GET /v1/site/appearance.
// Sunucu tarafında kısa önbellekle okunur ve <html data-design> olarak eklenir; API'ye
// ulaşılamazsa varsayılan tasarımla açılır (site hiçbir zaman bu yüzden çökmez).

import { runtimeConfig } from "@/lib/config";

export const DESIGNS = ["okyanus", "zumrut", "gunbatimi", "altin", "grafit"] as const;
export type Design = (typeof DESIGNS)[number];
export const DEFAULT_DESIGN: Design = "okyanus";

export const DESIGN_LABELS: Record<Design, { name: string; hint: string }> = {
  okyanus: { name: "Okyanus", hint: "Mavi ve mor; varsayılan, teknolojik" },
  zumrut: { name: "Zümrüt", hint: "Yeşil ve turkuaz; ferah, güven veren" },
  gunbatimi: { name: "Gün batımı", hint: "Turuncu ve pembe; enerjik, sıcak" },
  altin: { name: "Altın", hint: "Kehribar ve bronz; premium, ağırbaşlı" },
  grafit: { name: "Grafit", hint: "Sade, tek renk; kurumsal, minimal" },
};

export function isDesign(value: unknown): value is Design {
  return typeof value === "string" && (DESIGNS as readonly string[]).includes(value);
}

export async function fetchDesign(fetcher: typeof fetch = fetch): Promise<Design> {
  const cfg = runtimeConfig();
  try {
    const response = await fetcher(`${cfg.serverApiUrl}/v1/site/appearance`, {
      signal: AbortSignal.timeout(1500),
      ...(cfg.plansRevalidateS > 0
        ? { next: { revalidate: Math.min(cfg.plansRevalidateS, 30) } }
        : { cache: "no-store" as const }),
    });
    if (!response.ok) return DEFAULT_DESIGN;
    const body = (await response.json()) as { design?: unknown } | null;
    return isDesign(body?.design) ? body.design : DEFAULT_DESIGN;
  } catch {
    return DEFAULT_DESIGN;
  }
}
