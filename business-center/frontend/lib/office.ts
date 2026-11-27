export type Agent = { id: string; code: string; name: string; description: string; enabled: boolean;
  department: string; department_name: string; active_tasks: number };

export type Room = { key: string; label: string; tone: string; codes: string[]; col: number; row: number };

// Ofis yerleşimi: 4 x 2 oda. Kodlar veritabanındaki ajan kodlarıdır.
export const ROOMS: Room[] = [
  { key: "ideas", label: "BEYİN TAKIMI", tone: "#e11d48", col: 0, row: 0,
    codes: ["yt_trend_research", "yt_channel_strategist", "yt_script_writer"] },
  { key: "studio", label: "PRODÜKSİYON STÜDYOSU", tone: "#e11d48", col: 1, row: 0,
    codes: ["yt_video_production", "yt_thumbnail_designer"] },
  { key: "growth", label: "YOUTUBE BÜYÜME", tone: "#e11d48", col: 2, row: 0, codes: ["yt_seo", "yt_analytics"] },
  { key: "ceo", label: "YÖNETİM", tone: "#4f46e5", col: 3, row: 0, codes: ["ceo"] },
  { key: "product", label: "ÜRÜN & TASARIM", tone: "#ea580c", col: 0, row: 1,
    codes: ["etsy_product_research", "etsy_competitor_analysis", "etsy_design"] },
  { key: "store", label: "MAĞAZA OPERASYONU", tone: "#ea580c", col: 1, row: 1,
    codes: ["etsy_seo", "etsy_listing_manager", "printify"] },
  { key: "finance", label: "FİNANS & SATIŞ", tone: "#ea580c", col: 2, row: 1,
    codes: ["etsy_profit_analyst", "etsy_sales_analyst"] },
  { key: "qc", label: "KALİTE KONTROL", tone: "#059669", col: 3, row: 1,
    codes: ["qc_content", "qc_copyright", "qc_seo", "qc_financial", "qc_technical"] },
];

/** "Trend Research Agent" -> "Trend Research" (etiketler kısa kalsın). */
export const shortName = (n: string) => n.replace(/ Agent$/, "");
