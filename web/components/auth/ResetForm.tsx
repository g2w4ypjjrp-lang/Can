"use client";

import { useEffect, useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { ErrorBox } from "@/components/auth/ErrorBox";
import { PASSWORD_HINT } from "@/components/auth/RegisterForm";
import { formValue, useSubmit } from "@/components/auth/useSubmit";
import { Button, Field, LinkButton, Notice } from "@/components/ui";
import type { Message } from "@/lib/api";

export function ResetForm({ token }: { token: string | undefined }) {
  const api = useApi();
  const submit = useSubmit();
  const [mismatch, setMismatch] = useState(false);

  useEffect(() => {
    if (token) window.history.replaceState(null, "", "/sifre-sifirla");
  }, [token]);

  if (!token) {
    return (
      <Notice tone="danger" role="alert">
        Sıfırlama bağlantısı eksik veya hatalı. Yeni bir bağlantı isteyin.
      </Notice>
    );
  }
  if (submit.done) {
    return (
      <div className="space-y-5">
        <Notice tone="success" role="status">
          {submit.done} Diğer cihazlardaki oturumlarınız kapatıldı.
        </Notice>
        <LinkButton href="/giris" className="w-full">
          Giriş yap
        </LinkButton>
      </div>
    );
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const password = formValue(form, "password");
    if (password !== formValue(form, "password2")) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    void submit.run(
      async () => (await api.post<Message>("/v1/auth/password-reset/confirm", { token, password })).message ?? "Parolanız değiştirildi.",
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <Field id="password" name="password" type="password" label="Yeni parola" autoComplete="new-password" minLength={10} required hint={PASSWORD_HINT} />
      <Field
        id="password2"
        name="password2"
        type="password"
        label="Yeni parola (tekrar)"
        autoComplete="new-password"
        required
        error={mismatch ? "Parolalar eşleşmiyor" : undefined}
      />
      <ErrorBox error={submit.error} />
      <Button type="submit" className="w-full" disabled={submit.pending}>
        {submit.pending ? "Kaydediliyor…" : "Parolayı değiştir"}
      </Button>
    </form>
  );
}
