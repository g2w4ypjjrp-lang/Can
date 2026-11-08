"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { ErrorBox } from "@/components/auth/ErrorBox";
import { formValue, useSubmit } from "@/components/auth/useSubmit";
import { Button, Field, Notice } from "@/components/ui";
import type { Message } from "@/lib/api";

export function LoginForm({ next }: { next: string }) {
  const api = useApi();
  const router = useRouter();
  const login = useSubmit();
  const resend = useSubmit();
  const [email, setEmail] = useState("");
  const unverified = login.error?.status === 403 && login.error.message.includes("doğrulayın");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    void login.run(async () => {
      await api.post("/v1/auth/login", { email: formValue(form, "email"), password: formValue(form, "password") });
      router.push(next);
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate={false}>
      <Field id="email" name="email" type="email" label="E-posta" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      <Field id="password" name="password" type="password" label="Parola" autoComplete="current-password" required />
      <ErrorBox error={login.error} />
      {unverified ? (
        <div className="space-y-2">
          {resend.done ? (
            <Notice tone="success" role="status">
              {resend.done}
            </Notice>
          ) : (
            <Button
              type="button"
              variant="secondary"
              className="w-full"
              disabled={resend.pending || !email}
              onClick={() =>
                void resend.run(async () => (await api.post<Message>("/v1/auth/resend-verification", { email })).message ?? null)
              }
            >
              Doğrulama e-postasını yeniden gönder
            </Button>
          )}
          <ErrorBox error={resend.error} />
        </div>
      ) : null}
      <Button type="submit" className="w-full" disabled={login.pending}>
        {login.pending ? "Giriş yapılıyor…" : "Giriş yap"}
      </Button>
    </form>
  );
}
