import type { Metadata } from "next";

import { MessageSquarePlus, ShieldCheck, TrendingUp, Trophy } from "lucide-react";

import { ForumHeader } from "@/components/forum/ForumHeader";
import { Leaderboard } from "@/components/forum/Leaderboard";
import { RankBanner } from "@/components/forum/Ranks";
import { Container } from "@/components/ui";
import { fetchLeaderboard } from "@/lib/forum";
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

export default async function RanksPage() {
  const leaders = await fetchLeaderboard();
  return (
    <div className="stage pb-12">
      <ForumHeader
        title="Rütbe sistemi"
        subtitle="Yayımlanan her mesajınız sizi bir üst rütbeye taşır: Seviye 10 Sui ile başlarsınız, zirve Seviye 1 Bitcoin."
        active="ranks"
        crumbs={[{ label: "Rütbeler ve liderlik" }]}
      />
      <Container className="fb mt-4 space-y-4">
        <section aria-labelledby="rutbeler" className="fb-box">
          <h2 id="rutbeler" className="fb-thead">
            Rütbeler (en yüksekten)
          </h2>
          <ol className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 md:grid-cols-5" aria-label="Rütbeler (en yüksekten başlayarak)">
            {RANKS.map((rank) => (
              <li key={rank.level}>
                <RankBanner rank={rank} />
              </li>
            ))}
          </ol>
        </section>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_14rem]">
          <section aria-labelledby="liderler-baslik" id="liderler" className="fb-box">
            <h2 id="liderler-baslik" className="fb-thead">
              <Trophy aria-hidden="true" className="h-4 w-4" /> Liderlik tablosu
              <span className="ml-auto text-[12px] font-normal text-white/85">mesaj · faydalı</span>
            </h2>
            <div className="[&_ol]:rounded-none [&_ol]:border-0">
              <Leaderboard entries={leaders} />
            </div>
          </section>
          <div className="space-y-4">
            <section aria-labelledby="ekip-rutbe" className="fb-box">
              <h2 id="ekip-rutbe" className="fb-thead">
                Ekip rütbesi
              </h2>
              <div className="p-3">
                <RankBanner rank={TEAM_RANK} />
              </div>
            </section>
          </div>
        </div>

        <section aria-labelledby="nasil" className="fb-box">
          <h2 id="nasil" className="fb-thead">
            Nasıl yükselirim?
          </h2>
          <ul className="grid gap-3 p-4 sm:grid-cols-3">
            {STEPS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="rounded-lg border border-border bg-surface-2 p-3.5">
                <Icon aria-hidden="true" className="h-4 w-4 text-accent-text" />
                <p className="mt-1.5 text-[14px] font-semibold text-fg">{title}</p>
                <p className="mt-1 text-[13px] text-muted">{text}</p>
              </li>
            ))}
          </ul>
          <p className="border-t border-border px-4 py-2.5 text-[12px] text-muted">
            Rütbe adları en büyük kripto paralardan esinlenmiştir; yalnızca forum etkinliğini gösterir, yatırım önerisi değildir.
          </p>
        </section>
      </Container>
    </div>
  );
}
