import type { Metadata } from "next";

import { RegisterForm } from "@/components/auth/RegisterForm";
import { FormCard, TextLink } from "@/components/ui";

export const metadata: Metadata = { title: "Hesap oluştur", description: "AI Trading Intelligence müşteri hesabı oluşturun." };

export default function RegisterPage() {
  return (
    <FormCard
      title="Hesap oluştur"
      footer={
        <>
          Zaten hesabınız var mı? <TextLink href="/giris">Giriş yapın</TextLink>
        </>
      }
    >
      <RegisterForm />
    </FormCard>
  );
}
