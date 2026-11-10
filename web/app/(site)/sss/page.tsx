import type { Metadata } from "next";

import { ChevronDown, MessageCircleQuestion } from "lucide-react";

import { RiskNotice } from "@/components/RiskNotice";
import { Card, Container, IconTile, LinkButton, PageHeader } from "@/components/ui";
import { FAQ } from "@/lib/faq";

export const metadata: Metadata = {
  title: "Sık sorulan sorular",
  description: "Kazanç, güvenlik, API anahtarları, iPhone uygulaması, lisanslar ve kişisel veriler hakkında sorular.",
};


export default function FaqPage() {
  return (
    <>
      <PageHeader eyebrow="Destek" title="Sık sorulan sorular" />
      <Container className="grid gap-10 py-14 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-3">
          {FAQ.map((item) => (
            <details key={item.q} className="group rounded-2xl border border-border bg-surface px-6 py-5 shadow-sm transition-colors open:bg-surface-2">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-lg font-semibold text-fg focus-visible:outline-2 focus-visible:outline-accent-text">
                <span>{item.q}</span>
                <ChevronDown aria-hidden="true" className="h-5 w-5 shrink-0 text-muted transition-transform group-open:rotate-180" />
              </summary>
              {item.a.map((paragraph) => (
                <p key={paragraph} className="mt-3 leading-relaxed text-fg">
                  {paragraph}
                </p>
              ))}
            </details>
          ))}
          <div className="pt-8">
            <RiskNotice />
          </div>
        </div>
        <aside aria-label="Destek" className="lg:sticky lg:top-24 lg:self-start">
          <Card className="shadow-lift">
            <IconTile icon={MessageCircleQuestion} tone="violet" />
            <h2 className="mt-4 text-lg font-semibold text-fg">Cevabını bulamadınız mı?</h2>
            <p className="mt-2 text-sm text-muted">Sorunuzu yazın; e-postayla yanıtlayalım.</p>
            <LinkButton href="/iletisim" className="mt-5 w-full">
              Başka bir sorunuz mu var?
            </LinkButton>
          </Card>
        </aside>
      </Container>
    </>
  );
}
