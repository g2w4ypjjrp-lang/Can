import type { Metadata } from "next";

import { ForgotForm } from "@/components/auth/ForgotForm";
import { FormCard, TextLink } from "@/components/ui";

export const metadata: Metadata = { title: "Parolamı unuttum", robots: { index: false, follow: true } };

export default function ForgotPage() {
  return (
    <FormCard title="Parolamı unuttum" footer={<TextLink href="/giris">Giriş sayfasına dön</TextLink>}>
      <ForgotForm />
    </FormCard>
  );
}
