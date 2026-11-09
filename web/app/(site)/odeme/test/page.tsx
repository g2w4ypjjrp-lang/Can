import type { Metadata } from "next";

import { PaymentSimulator } from "@/components/purchase/PaymentSimulator";
import { Container, PageHeader } from "@/components/ui";
import { firstParam } from "@/lib/format";

export const metadata: Metadata = {
  title: "Test ödemesi",
  robots: { index: false, follow: false },
};

export default async function SimulatorPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const token = firstParam((await searchParams).oturum) ?? "";
  return (
    <>
      <PageHeader title="Test ödemesi" lead="Yalnızca geliştirme ve test ortamında: gerçek tahsilat yapılmaz." />
      <Container className="py-12">
        <div className="max-w-xl">
          <PaymentSimulator token={token} />
        </div>
      </Container>
    </>
  );
}
