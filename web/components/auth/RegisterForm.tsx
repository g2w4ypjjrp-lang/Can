"use client";

import Link from "next/link";
import type { FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { ErrorBox } from "@/components/auth/ErrorBox";
import { formValue, useSubmit } from "@/components/auth/useSubmit";
import { Button, Field, Notice } from "@/components/ui";
import type { Message } from "@/lib/api";

export const PASSWORD_HINT =
  "En az 10 karakter. E-posta adresinizi içermemeli. Birkaç kelimeden oluşan uzun bir parola cümlesi en güvenlisidir.";

export function RegisterForm() {
  const api = useApi();
  const submit = useSubmit();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    void submit.run(async () => {
      const result = await api.post<Message>("/v1/auth/register", {
        full_name: formValue(form, "full_name").trim() || null,
        email: formValue(form, "email"),
        password: formValue(form, "password"),
        accept_terms: data.get("accept_terms") === "on",
        marketing_consent: data.get("marketing_consent") === "on",
      });
      return result.message ?? "Kayıt alındı.";
    });
  }

  if (submit.done) {
    return (
      <Notice tone="success" title="E-postanızı kontrol edin" role="status">
        {submit.done} Bağlantı 24 saat geçerlidir; gelen kutunuzda yoksa istenmeyen e-posta klasörüne bakın.
      </Notice>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <Field id="full_name" name="full_name" label="Ad soyad" autoComplete="name" maxLength={120} />
      <Field id="email" name="email" type="email" label="E-posta" autoComplete="email" required />
      <Field
        id="password"
        name="password"
        type="password"
        label="Parola"
        autoComplete="new-password"
        minLength={10}
        maxLength={256}
        required
        hint={PASSWORD_HINT}
      />
      <div className="space-y-3">
        <div className="flex items-start gap-3">
          <input id="accept_terms" name="accept_terms" type="checkbox" required className="mt-1 h-4 w-4 accent-accent" />
          <label htmlFor="accept_terms" className="text-sm text-fg">
            <Link href="/yasal/kullanim-kosullari" className="text-link underline underline-offset-2">
              Kullanım koşullarını
            </Link>{" "}
            ve{" "}
            <Link href="/yasal/risk-bildirimi" className="text-link underline underline-offset-2">
              risk bildirimini
            </Link>{" "}
            okudum, kabul ediyorum. Kişisel verilerimin{" "}
            <Link href="/yasal/gizlilik" className="text-link underline underline-offset-2">
              aydınlatma metninde
            </Link>{" "}
            anlatıldığı şekilde işleneceğini biliyorum.
          </label>
        </div>
        <div className="flex items-start gap-3">
          <input id="marketing_consent" name="marketing_consent" type="checkbox" className="mt-1 h-4 w-4 accent-accent" />
          <label htmlFor="marketing_consent" className="text-sm text-fg">
            Yeni sürümler ve kampanyalar hakkında e-posta almak istiyorum (isteğe bağlı; istediğiniz zaman geri
            alabilirsiniz).
          </label>
        </div>
      </div>
      <ErrorBox error={submit.error} />
      <Button type="submit" className="w-full" disabled={submit.pending}>
        {submit.pending ? "Hesap oluşturuluyor…" : "Hesap oluştur"}
      </Button>
    </form>
  );
}
