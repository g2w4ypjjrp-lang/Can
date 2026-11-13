import type { Metadata } from "next";

import { ChevronRight, MessageSquarePlus, ShieldCheck, TrendingUp } from "lucide-react";
import Link from "next/link";

import { RankBanner } from "@/components/forum/Ranks";
import { CandleBackdrop } from "@/components/forum/Visuals";
import { Container } from "@/components/ui";
import { RANKS, TEAM_RANK } from "@/lib/ranks";

export const metadata: Metadata = {
  title: "Rütbe sistemi · Forum",
  description: "Forum rütbeleri: yayımlanan mesajlarınızla Seviye 10 Sui'den Seviye 1 Bitcoin'e yükselin.",
};

const STEPS = [
  { icon: MessageSquarePlus, title: "Yazın", text: "Konu açın ya da yanıt yazın. Her gönderi ekip onayından sonra yayımlanır." },
  { icon: TrendingUp, title: "Yükselin", text: "Yayımlanan her konu ve yanıt bir mesaj sayılır; eşiği geçince rütbeniz kendiliğinden yükselir." },
  { icon: ShieldCheck, title: "Kurallara uyun", text: "Reddedilen ya da gizlenen gönderiler sayılmaz. Kazanç vaadi ve reklam yayımlanmaz." },
];

export default function RanksPage() {
  return (
    <div className="stage">
      <header className="relative overflow-hidden border-b border-border">
        <CandleBackdrop className="pointer-events-none absolute inset-0 h-full w-full" />
        <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-r from-bg/90 via-bg/60 to-transparent" />
        <div aria-hidden="true" className="absolute inset-0 bg-[radial-gradient(60%_80%_at_80%_0%,rgba(251,191,36,0.22),transparent_60%)]" />
        <Container className="relative py-12 sm:py-16">
          <nav aria-label="Konum" className="flex items-center gap-1.5 text-sm text-muted">
            <Link href="/forum" className="underline-offset-4 hover:text-fg hover:underline">
              Forum
            </Link>
            <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" />
            <span className="text-fg">Rütbe sistemi</span>
          </nav>
          <h1 className="mt-4 text-4xl font-black uppercase tracking-tight text-fg sm:text-6xl">
            Zirveye <span className="text-gradient">tırman</span>
          </h1>
          <p className="mt-4 max-w-2xl text-lg text-muted">
            Forumdaki her yayımlanmış mesajınız sizi bir üst rütbeye taşır. Seviye 10 Sui ile başlarsınız; zirve Seviye 1 Bitcoin.
          </p>
        </Container>
      </header>

      <Container className="py-12">
        <ol className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-5" aria-label="Rütbeler (en yüksekten başlayarak)">
          {RANKS.map((rank) => (
            <li key={rank.level}>
              <RankBanner rank={rank} />
            </li>
          ))}
        </ol>

        <div className="mt-12 grid gap-6 lg:grid-cols-[1fr_16rem]">
          <section aria-labelledby="nasil" className="rounded-2xl border border-border bg-surface p-6">
            <h2 id="nasil" className="text-lg font-semibold text-fg">
              Nasıl yükselirim?
            </h2>
            <ul className="mt-4 grid gap-4 sm:grid-cols-3">
              {STEPS.map(({ icon: Icon, title, text }) => (
                <li key={title} className="rounded-xl border border-border bg-surface-2 p-4">
                  <Icon aria-hidden="true" className="h-5 w-5 text-accent-text" />
                  <p className="mt-2 font-semibold text-fg">{title}</p>
                  <p className="mt-1 text-sm text-muted">{text}</p>
                </li>
              ))}
            </ul>
            <p className="mt-5 text-xs text-muted">
              Rütbe adları en büyük kripto paralardan esinlenmiştir; yalnızca forum etkinliğini gösterir, yatırım önerisi değildir.
            </p>
          </section>
          <div className="max-w-[16rem]">
            <RankBanner rank={TEAM_RANK} />
          </div>
        </div>
      </Container>
    </div>
  );
}
