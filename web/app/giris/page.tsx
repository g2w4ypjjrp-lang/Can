import type { Metadata } from "next";

import { LoginForm } from "@/components/auth/LoginForm";
import { FormCard, TextLink } from "@/components/ui";
import { safeNext } from "@/lib/format";

export const metadata: Metadata = { title: "Giriş yap", description: "Müşteri paneline giriş." };

export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const next = safeNext((await searchParams).sonra);
  return (
    <FormCard
      title="Giriş yap"
      footer={
        <>
          <TextLink href="/sifremi-unuttum">Parolamı unuttum</TextLink>
          <span aria-hidden="true"> · </span>
          Hesabınız yok mu? <TextLink href="/kayit">Hesap oluşturun</TextLink>
        </>
      }
    >
      <LoginForm next={next} />
    </FormCard>
  );
}
