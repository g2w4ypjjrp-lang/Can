// Rütbe görselleri: numaralı sancak kartı (rütbe sayfası), küçük sancak (mesaj yazar sütunu),
// rozet (konu listesi). Satır içi stil yok (güvenlik politikası): renkler sınıf olarak verilir.

import { Atom, Crown, Droplet, Gem, Hexagon, Link2, MessageCircle, Mountain, Send, ShieldCheck, Zap, type LucideIcon } from "lucide-react";

import { nextRank, rankFor, type Rank } from "@/lib/ranks";

interface Look {
  icon: LucideIcon;
  banner: string; // sancak zemini (beyaz yazıya ≥ 4.5:1)
  ring: string; // çerçeve
  medal: string; // madalyon
  glow: string;
}

const LOOKS: Record<number, Look> = {
  0: { icon: ShieldCheck, banner: "from-[#065f46] via-[#064e3b] to-[#022c22]", ring: "border-[#34d399]", medal: "from-[#a7f3d0] to-[#047857]", glow: "shadow-[0_0_30px_-6px_rgba(52,211,153,0.6)]" },
  1: { icon: Crown, banner: "from-[#a16207] via-[#854d0e] to-[#713f12]", ring: "border-[#fbbf24]", medal: "from-[#fde68a] to-[#b45309]", glow: "shadow-[0_0_40px_-4px_rgba(251,191,36,0.7)]" },
  2: { icon: Gem, banner: "from-[#475569] via-[#334155] to-[#1e293b]", ring: "border-[#cbd5e1]", medal: "from-[#f1f5f9] to-[#64748b]", glow: "shadow-[0_0_34px_-6px_rgba(203,213,225,0.55)]" },
  3: { icon: Zap, banner: "from-[#047857] via-[#065f46] to-[#064e3b]", ring: "border-[#34d399]", medal: "from-[#a7f3d0] to-[#7c3aed]", glow: "shadow-[0_0_34px_-6px_rgba(52,211,153,0.55)]" },
  4: { icon: Send, banner: "from-[#374151] via-[#1f2937] to-[#111827]", ring: "border-[#9ca3af]", medal: "from-[#e5e7eb] to-[#374151]", glow: "shadow-[0_0_28px_-8px_rgba(156,163,175,0.5)]" },
  5: { icon: Hexagon, banner: "from-[#a16207] via-[#92400e] to-[#78350f]", ring: "border-[#facc15]", medal: "from-[#fef08a] to-[#ca8a04]", glow: "shadow-[0_0_28px_-8px_rgba(250,204,21,0.5)]" },
  6: { icon: Atom, banner: "from-[#1e40af] via-[#1e3a8a] to-[#172554]", ring: "border-[#60a5fa]", medal: "from-[#bfdbfe] to-[#1d4ed8]", glow: "shadow-[0_0_28px_-8px_rgba(96,165,250,0.5)]" },
  7: { icon: Link2, banner: "from-[#3730a3] via-[#312e81] to-[#1e1b4b]", ring: "border-[#818cf8]", medal: "from-[#c7d2fe] to-[#4338ca]", glow: "shadow-[0_0_28px_-8px_rgba(129,140,248,0.5)]" },
  8: { icon: MessageCircle, banner: "from-[#0369a1] via-[#075985] to-[#0c4a6e]", ring: "border-[#38bdf8]", medal: "from-[#bae6fd] to-[#0284c7]", glow: "shadow-[0_0_28px_-8px_rgba(56,189,248,0.5)]" },
  9: { icon: Mountain, banner: "from-[#b91c1c] via-[#991b1b] to-[#7f1d1d]", ring: "border-[#f87171]", medal: "from-[#fecaca] to-[#dc2626]", glow: "shadow-[0_0_28px_-8px_rgba(248,113,113,0.5)]" },
  10: { icon: Droplet, banner: "from-[#0e7490] via-[#155e75] to-[#164e63]", ring: "border-[#67e8f9]", medal: "from-[#cffafe] to-[#0891b2]", glow: "shadow-[0_0_28px_-8px_rgba(103,232,249,0.5)]" },
};

function look(rank: Rank): Look {
  return LOOKS[rank.level] ?? LOOKS[10]!;
}

function Medal({ rank, size }: { rank: Rank; size: "sm" | "md" | "lg" }) {
  const l = look(rank);
  const Icon = l.icon;
  const box = { sm: "h-7 w-7 border-2", md: "h-14 w-14 border-[3px]", lg: "h-20 w-20 border-4" }[size];
  const icon = { sm: "h-3.5 w-3.5", md: "h-7 w-7", lg: "h-10 w-10" }[size];
  return (
    <span aria-hidden="true" className={`relative grid shrink-0 place-items-center rounded-full bg-gradient-to-br ${l.medal} ${l.ring} ${box}`}>
      <span className="absolute inset-[3px] rounded-full bg-gradient-to-br from-black/0 via-black/10 to-black/35" />
      <Icon className={`relative text-white drop-shadow-[0_2px_3px_rgba(0,0,0,0.55)] ${icon}`} strokeWidth={2.4} />
    </span>
  );
}

function label(rank: Rank): string {
  return rank.level === 0 ? "Ekip" : `Seviye ${rank.level} · ${rank.name}`;
}

/** Rütbe sayfasındaki büyük numaralı sancak (görseldeki kart düzeni). */
export function RankBanner({ rank, current = false }: { rank: Rank; current?: boolean }) {
  const l = look(rank);
  const top = rank.level >= 1 && rank.level <= 3;
  return (
    <div
      className={`rank-pennant relative flex flex-col items-center border-2 bg-gradient-to-b px-3 pb-10 pt-3 text-center text-white ${l.banner} ${l.ring} ${top ? `${l.glow} rank-shine` : ""} ${current ? "ring-4 ring-white/70" : ""}`}
      data-testid={`rank-${rank.level}`}
    >
      <span className={`grid h-11 w-11 place-items-center rounded-lg border-2 bg-black/30 text-2xl font-black tabular ${l.ring}`}>
        {rank.level === 0 ? "★" : rank.level}
      </span>
      <span className="mt-4">
        <Medal rank={rank} size="lg" />
      </span>
      {/* Coin adları İngilizce büyük harfle yazılır (Türkçede "i" → "İ" olurdu). */}
      <p className="mt-4 text-sm font-extrabold uppercase tracking-wide" lang={rank.level === 0 ? undefined : "en"}>
        {rank.name} <span className="font-semibold text-white/85">({rank.symbol})</span>
      </p>
      <p className="mt-1 text-xs leading-snug text-white/90">{rank.title}</p>
      <p className="mt-3 rounded-full border border-white/25 bg-black/30 px-2.5 py-0.5 text-[11px] font-semibold">
        {rank.level === 0 ? "Yönetim" : rank.min === 0 ? "Başlangıç" : `${rank.min}+ mesaj`}
      </p>
      {current ? <p className="mt-2 text-[11px] font-bold uppercase tracking-wider">Şu an buradasınız</p> : null}
    </div>
  );
}

/** Mesajın yazar sütunu: küçük sancak ve bir üst rütbeye ilerleme. */
export function AuthorRank({ posts, team }: { posts: number; team: boolean }) {
  const rank = rankFor(posts, team);
  const l = look(rank);
  const next = nextRank(posts, team);
  return (
    <div className="flex flex-col items-center gap-1.5" data-testid="author-rank">
      <div className={`rank-pennant flex w-24 flex-col items-center border-2 bg-gradient-to-b px-2 pb-5 pt-2 text-white ${l.banner} ${l.ring}`}>
        <span className="text-[11px] font-black tabular">{rank.level === 0 ? "★" : `SV ${rank.level}`}</span>
        <span className="mt-1.5">
          <Medal rank={rank} size="md" />
        </span>
        <span className="mt-1.5 text-[11px] font-extrabold uppercase" lang={rank.level === 0 ? undefined : "en"}>
          {rank.name}
        </span>
      </div>
      <p className="text-[11px] font-semibold text-fg">{label(rank)}</p>
      {next ? (
        <div className="w-24">
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
            <div className={`h-full rounded-full bg-gradient-to-r ${look(next.rank).medal} ${progressWidth(next.progress)}`} />
          </div>
          <p className="mt-1 text-[10px] leading-tight text-muted">
            {next.rank.name} için {next.remaining} mesaj
          </p>
        </div>
      ) : null}
    </div>
  );
}

// Satır içi stil kullanılamadığından ilerleme genişliği onda bir adımlarla sınıf olarak verilir.
const WIDTHS = ["w-[4%]", "w-[10%]", "w-[20%]", "w-[30%]", "w-[40%]", "w-[50%]", "w-[60%]", "w-[70%]", "w-[80%]", "w-[90%]", "w-full"];
function progressWidth(progress: number): string {
  return WIDTHS[Math.round(progress * 10)] ?? "w-full";
}

/** Konu listesinde yazarın yanında küçük rozet. */
export function RankPill({ posts, team }: { posts: number; team: boolean }) {
  const rank = rankFor(posts, team);
  const l = look(rank);
  return (
    <span
      lang={rank.level === 0 ? undefined : "en"}
      className={`inline-flex items-center gap-1 rounded-full border bg-gradient-to-r py-0.5 pl-0.5 pr-2 text-[10px] font-bold uppercase text-white ${l.banner} ${l.ring}`}
    >
      <Medal rank={rank} size="sm" />
      {rank.level === 0 ? "Ekip" : `SV${rank.level} ${rank.name}`}
    </span>
  );
}

/** Kenar çubuğu: bütün rütbelerin kısa listesi. */
export function RankLadder({ ranks }: { ranks: Rank[] }) {
  return (
    <ol className="space-y-1.5">
      {ranks.map((rank) => (
        <li key={rank.level} className="flex items-center justify-between gap-2 text-xs">
          <span className="flex items-center gap-2">
            <Medal rank={rank} size="sm" />
            <span className="font-semibold text-fg">
              {rank.level}. {rank.name}
            </span>
          </span>
          <span className="text-muted">{rank.min === 0 ? "başlangıç" : `${rank.min}+`}</span>
        </li>
      ))}
    </ol>
  );
}
