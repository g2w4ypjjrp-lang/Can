import type { Metadata } from "next";

import { ResetForm } from "@/components/auth/ResetForm";
import { FormCard, TextLink } from "@/components/ui";
import { firstParam } from "@/lib/format";

export const metadata: Metadata = { title: "Yeni parola", robots: { index: false, follow: false } };

export default async function ResetPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const token = firstParam((await searchParams).token);
  return (
    <FormCard title="Yeni parola belirleyin" footer={<TextLink href="/sifremi-unuttum">Yeni bağlantı iste</TextLink>}>
      <ResetForm token={token} />
    </FormCard>
  );
}
