"use client";

import type { FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { ErrorBox } from "@/components/auth/ErrorBox";
import { formValue, useSubmit } from "@/components/auth/useSubmit";
import { Button, Field, Notice } from "@/components/ui";
import type { Message } from "@/lib/api";

export function ForgotForm() {
  const api = useApi();
  const submit = useSubmit();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    void submit.run(
      async () => (await api.post<Message>("/v1/auth/password-reset", { email: formValue(form, "email") })).message ?? null,
    );
  }

  if (submit.done) {
    return (
      <Notice tone="success" role="status">
        {submit.done} Bağlantı 1 saat geçerlidir.
      </Notice>
    );
  }
  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <p className="text-sm text-muted">Hesabınızın e-posta adresini girin; parola sıfırlama bağlantısı gönderelim.</p>
      <Field id="email" name="email" type="email" label="E-posta" autoComplete="email" required />
      <ErrorBox error={submit.error} />
      <Button type="submit" className="w-full" disabled={submit.pending}>
        {submit.pending ? "Gönderiliyor…" : "Sıfırlama bağlantısı gönder"}
      </Button>
    </form>
  );
}
