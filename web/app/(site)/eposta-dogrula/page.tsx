import type { Metadata } from "next";

import { VerifyEmail } from "@/components/auth/VerifyEmail";
import { FormCard } from "@/components/ui";
import { firstParam } from "@/lib/format";

export const metadata: Metadata = { title: "E-posta doğrulama", robots: { index: false, follow: false } };

export default async function VerifyEmailPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const token = firstParam((await searchParams).token);
  return (
    <FormCard title="E-posta doğrulama">
      <VerifyEmail token={token} />
    </FormCard>
  );
}
