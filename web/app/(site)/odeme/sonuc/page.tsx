import type { Metadata } from "next";

import { OrderResult } from "@/components/purchase/OrderResult";
import { Container, PageHeader } from "@/components/ui";
import { firstParam } from "@/lib/format";

export const metadata: Metadata = {
  title: "Ödeme sonucu",
  robots: { index: false, follow: false },
};

export default async function ResultPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = firstParam((await searchParams).siparis) ?? "";
  const orderNo = /^\d{6,12}$/.test(raw) ? Number(raw) : null;
  return (
    <>
      <PageHeader title="Ödeme sonucu" />
      <Container className="py-12">
        <div className="max-w-2xl">
          <OrderResult orderNo={orderNo} />
        </div>
      </Container>
    </>
  );
}
