// Forum rütbeleri: yayımlanan (onaylı) mesaj sayısıyla yükselinir. Seviye 10'dan (Sui) başlanır,
// en üst seviye 1'dir (Bitcoin). Adlar piyasa değeri sıralamasından esinlenmiştir; coin logoları
// kullanılmaz (kendi amblemlerimiz). Ekip üyeleri ayrı "Ekip" rütbesi taşır.

export interface Rank {
  level: number; // 1 en yüksek
  name: string;
  symbol: string;
  title: string;
  min: number; // gereken en az yayımlanmış mesaj
}

export const RANKS: Rank[] = [
  { level: 1, name: "Bitcoin", symbol: "BTC", title: "Değer saklayan efsane", min: 200 },
  { level: 2, name: "Ethereum", symbol: "ETH", title: "Akıllı sözleşme ustası", min: 120 },
  { level: 3, name: "Solana", symbol: "SOL", title: "Yüksek performans", min: 80 },
  { level: 4, name: "XRP", symbol: "XRP", title: "Hızlı transfer", min: 55 },
  { level: 5, name: "BNB", symbol: "BNB", title: "Borsa kurdu", min: 35 },
  { level: 6, name: "Cardano", symbol: "ADA", title: "Araştırmacı", min: 20 },
  { level: 7, name: "Chainlink", symbol: "LINK", title: "Bilgi köprüsü", min: 12 },
  { level: 8, name: "Toncoin", symbol: "TON", title: "Topluluk sesi", min: 7 },
  { level: 9, name: "Avalanche", symbol: "AVAX", title: "Çığ başlıyor", min: 3 },
  { level: 10, name: "Sui", symbol: "SUI", title: "Yeni dalga", min: 0 },
];

export const TEAM_RANK: Rank = { level: 0, name: "Ekip", symbol: "EKİP", title: "AI Trading ekibi", min: 0 };

export function rankFor(posts: number, team: boolean): Rank {
  if (team) return TEAM_RANK;
  return RANKS.find((r) => posts >= r.min) ?? RANKS[RANKS.length - 1]!;
}

/** Bir üst rütbe ve kalan mesaj sayısı (en üstte ya da ekipte null). */
export function nextRank(posts: number, team: boolean): { rank: Rank; remaining: number; progress: number } | null {
  if (team) return null;
  const current = rankFor(posts, false);
  const next = RANKS.find((r) => r.level === current.level - 1);
  if (!next) return null;
  const span = next.min - current.min;
  return { rank: next, remaining: next.min - posts, progress: span > 0 ? Math.min(1, Math.max(0, (posts - current.min) / span)) : 1 };
}
