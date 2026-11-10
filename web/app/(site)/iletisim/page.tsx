import type { Metadata } from "next";

import { BookOpen, ShieldAlert } from "lucide-react";

import { ContactForm } from "@/components/ContactForm";
import { Card, Container, IconTile, PageHeader, TextLink } from "@/components/ui";

export const metadata: Metadata = { title: "İletişim", description: "Destek, lisans, satış ve kişisel veri talepleri için bize yazın." };

export default function ContactPage() {
  return (
    <>
      <PageHeader eyebrow="Destek" title="İletişim" lead="Sorularınız, destek talepleriniz ve geri bildirimleriniz için bize yazın. Yanıtımızı e-postayla iletiriz." />
      <Container className="py-14">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Card className="p-7 shadow-lift sm:p-9">
            <ContactForm />
          </Card>
          <aside className="space-y-6" aria-label="Yardım">
            <Card>
              <IconTile icon={BookOpen} />
              <h2 className="mt-4 font-semibold text-fg">Önce bakmak isteyebilirsiniz</h2>
              <ul className="mt-3 space-y-2 text-sm">
                <li>
                  <TextLink href="/sss">Sık sorulan sorular</TextLink>
                </li>
                <li>
                  <TextLink href="/ozellikler">Özellikler ve sistem gereksinimleri</TextLink>
                </li>
                <li>
                  <TextLink href="/yasal/risk-bildirimi">Risk bildirimi</TextLink>
                </li>
              </ul>
            </Card>
            <Card>
              <IconTile icon={ShieldAlert} tone="danger" />
              <h2 className="mt-4 font-semibold text-fg">Güvenlik uyarısı</h2>
              <p className="mt-2 text-sm text-muted">
                Ekibimiz sizden asla parola, API anahtarı veya uzak masaüstü erişimi istemez. Böyle bir talep alırsanız
                yanıt vermeyin ve bize bildirin.
              </p>
            </Card>
          </aside>
        </div>
      </Container>
    </>
  );
}
