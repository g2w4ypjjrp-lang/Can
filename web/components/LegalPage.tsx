import type { ReactNode } from "react";

import { Container, Notice, PageHeader } from "@/components/ui";

/** Yasal metin şablonu. Hukukçu onayı gelene kadar her metin "taslak" olarak işaretlenir. */
export function LegalPage({ title, updated, children }: { title: string; updated: string; children: ReactNode }) {
  return (
    <>
      <PageHeader eyebrow="Yasal" title={title} lead={`Son güncelleme: ${updated}`} />
      <Container className="py-12">
        <div className="mx-auto max-w-3xl rounded-[2rem] border border-border bg-surface p-7 shadow-sm sm:p-12">
          <Notice tone="warning" title="Taslak — hukukçu onayı bekliyor" role="note">
            Bu metin bir taslaktır, henüz yürürlükte değildir ve hukuki danışmanlık yerine geçmez. Köşeli
            parantez içindeki alanlar (ör. [Şirket unvanı]) şirket bilgileri kesinleştiğinde doldurulacaktır.
          </Notice>
          <div className="legal mt-8">{children}</div>
        </div>
      </Container>
    </>
  );
}
