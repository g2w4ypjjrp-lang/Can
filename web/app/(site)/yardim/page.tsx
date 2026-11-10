import type { Metadata } from "next";

import { BookOpenCheck, CircleHelp, LifeBuoy } from "lucide-react";

import { RiskNotice } from "@/components/RiskNotice";
import { Card, Container, IconTile, LinkButton, PageHeader } from "@/components/ui";
import { HELP_TOPICS, PROBLEMS } from "@/lib/help";

export const metadata: Metadata = {
  title: "Yardım merkezi",
  description:
    "Kurulum, lisans etkinleştirme, Binance Demo Trading anahtarı, iPhone eşleştirme, Telegram bildirimleri, backtest ve sık hataların çözümleri.",
};

export default function HelpPage() {
  return (
    <>
      <PageHeader
        eyebrow="Destek"
        title="Yardım merkezi"
        lead="Kurulumdan ilk işleme kadar adım adım rehberler ve sık görülen hataların çözümleri."
      />
      <Container className="grid gap-10 py-14 lg:grid-cols-[16rem_1fr]">
        <nav aria-label="Yardım konuları" className="lg:sticky lg:top-24 lg:self-start">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">Konular</p>
          <ul className="mt-3 space-y-1 text-sm">
            {HELP_TOPICS.map((topic) => (
              <li key={topic.id}>
                <a href={`#${topic.id}`} className="block rounded-lg px-3 py-1.5 text-fg hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent-text">
                  {topic.title}
                </a>
              </li>
            ))}
            <li>
              <a href="#sik-hatalar" className="block rounded-lg px-3 py-1.5 font-medium text-accent-text hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent-text">
                Sık hatalar ve çözümleri
              </a>
            </li>
          </ul>
        </nav>
        <div className="min-w-0 space-y-6">
          {HELP_TOPICS.map((topic, index) => (
            <section key={topic.id} id={topic.id} aria-labelledby={`${topic.id}-baslik`} className="scroll-mt-24">
              <Card>
                <div className="flex items-start gap-4">
                  <IconTile icon={BookOpenCheck} tone={index % 2 ? "violet" : "accent"} />
                  <div className="min-w-0">
                    <h2 id={`${topic.id}-baslik`} className="text-xl font-semibold text-fg">
                      {topic.title}
                    </h2>
                    <p className="mt-1 text-muted">{topic.lead}</p>
                  </div>
                </div>
                {topic.steps ? (
                  <ol className="mt-5 space-y-3">
                    {topic.steps.map((step, i) => (
                      <li key={step} className="flex gap-3 text-fg">
                        <span aria-hidden="true" className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-sm font-semibold text-accent-text">
                          {i + 1}
                        </span>
                        <span className="pt-0.5 leading-relaxed">{step}</span>
                      </li>
                    ))}
                  </ol>
                ) : null}
                {topic.notes ? (
                  <ul className="mt-4 space-y-2 border-t border-border pt-4 text-sm text-muted">
                    {topic.notes.map((note) => (
                      <li key={note} className="leading-relaxed">
                        {note}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </Card>
            </section>
          ))}

          <section id="sik-hatalar" aria-labelledby="sik-hatalar-baslik" className="scroll-mt-24">
            <h2 id="sik-hatalar-baslik" className="flex items-center gap-2 text-2xl font-semibold text-fg">
              <CircleHelp aria-hidden="true" className="h-6 w-6 text-accent-text" /> Sık hatalar ve çözümleri
            </h2>
            <div className="mt-4 space-y-3">
              {PROBLEMS.map((problem) => (
                <details key={problem.q} className="group rounded-2xl border border-border bg-surface px-6 py-4 shadow-sm open:bg-surface-2">
                  <summary className="cursor-pointer list-none font-semibold text-fg focus-visible:outline-2 focus-visible:outline-accent-text">
                    {problem.q}
                  </summary>
                  <p className="mt-2 leading-relaxed text-fg">{problem.a}</p>
                </details>
              ))}
            </div>
          </section>

          <Card className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <IconTile icon={LifeBuoy} tone="cyan" />
              <div>
                <h2 className="font-semibold text-fg">Çözüm bulamadınız mı?</h2>
                <p className="text-sm text-muted">Hata mesajını ve ekran görüntüsünü ekleyerek yazın.</p>
              </div>
            </div>
            <LinkButton href="/iletisim">Destek talebi gönder</LinkButton>
          </Card>
          <RiskNotice />
        </div>
      </Container>
    </>
  );
}
