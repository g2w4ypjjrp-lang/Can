// Forum görselleri: kategori renkleri ve simgeleri, coin jetonu, yazar rozeti. Resim dosyası ya da
// dış adres kullanılmaz (güvenlik politikası); görseller renk geçişleri ve simgelerle çizilir.
// Beyaz yazı her renk geçişinin iki ucuna da ≥ 4.5:1 karşıtlıktadır.

import { CircleHelp, LineChart, MessagesSquare, Newspaper, Rocket, type LucideIcon } from "lucide-react";

import { LogoMark } from "@/components/Logo";
import type { ForumCategory } from "@/lib/forum";

export const CATEGORY_META: Record<ForumCategory, { label: string; hint: string; icon: LucideIcon; gradient: string }> = {
  genel: {
    label: "Genel sohbet",
    hint: "Tanışma, deneyim ve fikirler",
    icon: MessagesSquare,
    gradient: "from-[#1d4ed8] to-[#0e7490]",
  },
  strateji: {
    label: "Strateji ve analiz",
    hint: "Grafik, gösterge ve risk yönetimi",
    icon: LineChart,
    gradient: "from-[#6d28d9] to-[#4338ca]",
  },
  soru: {
    label: "Soru ve yardım",
    hint: "Uygulama ve kurulum soruları",
    icon: CircleHelp,
    gradient: "from-[#b45309] to-[#c2410c]",
  },
  "yeni-coin": {
    label: "Yeni coinler",
    hint: "Listelemeler ve yeni projeler",
    icon: Rocket,
    gradient: "from-[#be123c] to-[#a21caf]",
  },
  haber: {
    label: "Haberler",
    hint: "Ekibin paylaştığı güncel haberler",
    icon: Newspaper,
    gradient: "from-[#047857] to-[#0f766e]",
  },
};

const TOKEN_GRADIENTS = [
  "from-[#f59e0b] to-[#b45309]",
  "from-[#6366f1] to-[#4338ca]",
  "from-[#ec4899] to-[#be185d]",
  "from-[#10b981] to-[#047857]",
  "from-[#06b6d4] to-[#0e7490]",
  "from-[#8b5cf6] to-[#6d28d9]",
  "from-[#ef4444] to-[#b91c1c]",
  "from-[#14b8a6] to-[#0f766e]",
];

function hash(text: string): number {
  let h = 7;
  for (let i = 0; i < text.length; i += 1) h = (h * 31 + text.charCodeAt(i)) >>> 0;
  return h;
}

/** Coin jetonu: sembolden türetilen renkli daire (resim yok). */
export function CoinToken({ symbol, size = "md" }: { symbol: string; size?: "xs" | "sm" | "md" | "lg" }) {
  // Uzun sembollerde yazı küçülür (ör. PREDICT); en çok 7 karakter.
  const tier = symbol.length <= 3 ? 0 : symbol.length <= 5 ? 1 : 2;
  const sizes = {
    xs: ["h-6 w-6 ring-1", "text-[8px]", "text-[6px]", "text-[5px]"],
    sm: ["h-9 w-9", "text-[10px]", "text-[8px]", "text-[7px]"],
    md: ["h-12 w-12", "text-xs", "text-[10px]", "text-[8px]"],
    lg: ["h-20 w-20", "text-base", "text-sm", "text-[11px]"],
  }[size];
  return (
    <span
      aria-hidden="true"
      className={`relative grid shrink-0 place-items-center rounded-full bg-gradient-to-br font-extrabold tracking-tight text-white shadow-lg ring-2 ring-white/30 ${TOKEN_GRADIENTS[hash(symbol) % TOKEN_GRADIENTS.length]} ${sizes[0]} ${sizes[tier + 1]}`}
    >
      {size === "xs" ? null : <span className="absolute inset-1 rounded-full border border-white/35" />}
      {size === "xs" ? symbol.slice(0, 4) : symbol.slice(0, 7)}
    </span>
  );
}

/** Yazar rozeti: ekip için logo, müşteri için baş harfler. */
export function AuthorAvatar({ name, team, size = "md" }: { name: string; team: boolean; size?: "sm" | "md" | "lg" }) {
  const box = size === "sm" ? "h-8 w-8 text-xs" : size === "lg" ? "h-16 w-16 text-xl" : "h-10 w-10 text-sm";
  if (team) {
    return (
      <span aria-hidden="true" className={`grid shrink-0 place-items-center rounded-full bg-surface-2 ring-1 ring-border ${box}`}>
        <LogoMark className={size === "lg" ? "h-9 w-9" : "h-5 w-5"} />
      </span>
    );
  }
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toLocaleUpperCase("tr-TR"))
    .join("");
  return (
    <span
      aria-hidden="true"
      className={`grid shrink-0 place-items-center rounded-full bg-gradient-to-br font-semibold text-white ${TOKEN_GRADIENTS[hash(name) % TOKEN_GRADIENTS.length]} ${box}`}
    >
      {initials || "?"}
    </span>
  );
}

export function CategoryChip({ category, solid = false }: { category: ForumCategory; solid?: boolean }) {
  const meta = CATEGORY_META[category];
  const Icon = meta.icon;
  if (solid) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-white/25 bg-black/25 px-2.5 py-1 text-xs font-semibold text-white backdrop-blur">
        <Icon aria-hidden="true" className="h-3.5 w-3.5" />
        {meta.label}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 py-0.5 pl-0.5 pr-2.5 text-xs font-semibold text-fg">
      <span aria-hidden="true" className={`grid h-5 w-5 place-items-center rounded-full bg-gradient-to-br text-white ${meta.gradient}`}>
        <Icon className="h-3 w-3" />
      </span>
      {meta.label}
    </span>
  );
}

/** Süs: mum grafiği ve hareketli ortalama (sabit tohumla üretilir; her çizimde aynı). */
export function CandleBackdrop({ className = "" }: { className?: string }) {
  let seed = 11;
  const rnd = () => {
    seed = (seed * 9301 + 49297) % 233280;
    return seed / 233280;
  };
  const candles: { x: number; open: number; close: number; high: number; low: number }[] = [];
  let price = 200;
  for (let i = 0; i < 46; i += 1) {
    const open = price;
    const close = Math.max(40, Math.min(330, open + (rnd() - 0.46) * 34));
    const high = Math.max(open, close) + rnd() * 16;
    const low = Math.min(open, close) - rnd() * 16;
    candles.push({ x: 12 + i * 26, open, close, high, low });
    price = close;
  }
  const line = candles.map((c, i) => `${i ? "L" : "M"}${c.x + 5},${380 - (c.open + c.close) / 2}`).join(" ");
  return (
    <svg aria-hidden="true" viewBox="0 0 1210 400" preserveAspectRatio="xMidYMid slice" className={className}>
      {candles.map((c) => {
        const up = c.close >= c.open;
        const color = up ? "#34d399" : "#fb7185";
        return (
          <g key={c.x} opacity={0.32}>
            <line x1={c.x + 5} x2={c.x + 5} y1={380 - c.high} y2={380 - c.low} stroke={color} strokeWidth={1.5} />
            <rect x={c.x} y={380 - Math.max(c.open, c.close)} width={10} height={Math.max(2, Math.abs(c.close - c.open))} rx={1.5} fill={color} />
          </g>
        );
      })}
      <path d={line} fill="none" stroke="#8fb0ff" strokeWidth={2} opacity={0.45} />
    </svg>
  );
}
