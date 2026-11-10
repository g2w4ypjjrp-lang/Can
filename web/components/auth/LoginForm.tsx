"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { ErrorBox } from "@/components/auth/ErrorBox";
import { formValue, useSubmit } from "@/components/auth/useSubmit";
import { Button, Field, Notice } from "@/components/ui";
import type { Message } from "@/lib/api";

type LoginResult = { status: "ok" } | { status: "mfa_required"; challenge: string };

export function LoginForm({ next }: { next: string }) {
  const api = useApi();
  const router = useRouter();
  const login = useSubmit();
  const resend = useSubmit();
  const [email, setEmail] = useState("");
  const [challenge, setChallenge] = useState<string | null>(null);
  const unverified = login.error?.status === 403 && login.error.message.includes("doğrulayın");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    void login.run(async () => {
      const result = await api.post<LoginResult>("/v1/auth/login", {
        email: formValue(form, "email"),
        password: formValue(form, "password"),
      });
      if (result.status === "mfa_required") {
        setChallenge(result.challenge);
        return;
      }
      router.push(next);
    });
  }

  if (challenge) {
    return <SecondStep key={challenge} challenge={challenge} onDone={() => router.push(next)} onRestart={() => setChallenge(null)} />;
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

/** Giriş ikinci adımı: doğrulama uygulaması kodu veya kurtarma kodu. Her giriş denemesi için yeni durum. */
function SecondStep({ challenge, onDone, onRestart }: { challenge: string; onDone: () => void; onRestart: () => void }) {
  const api = useApi();
  const second = useSubmit();
  const expired = second.error?.status === 401 && second.error.message.includes("yeniden giriş");

  function onCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    void second.run(async () => {
      await api.post("/v1/auth/login/2fa", { challenge, code: formValue(form, "code").trim() });
      onDone();
    });
  }

  return (
    <form onSubmit={onCode} className="space-y-5" data-testid="login-2fa">
      <p className="text-sm text-muted">
        Hesabınızda iki adımlı doğrulama açık. Doğrulama uygulamanızdaki 6 haneli kodu veya kurtarma kodlarınızdan birini
        girin.
      </p>
      <Field
        id="code"
        name="code"
        label="Doğrulama kodu"
        autoComplete="one-time-code"
        autoFocus
        required
        maxLength={20}
        hint="Kurtarma kodu her kullanımda geçersiz olur."
      />
      <ErrorBox error={second.error} />
      {expired ? (
        <Button type="button" variant="secondary" className="w-full" onClick={onRestart}>
          Yeniden giriş yap
        </Button>
      ) : (
        <Button type="submit" className="w-full" disabled={second.pending}>
          {second.pending ? "Doğrulanıyor…" : "Doğrula ve giriş yap"}
        </Button>
      )}
    </form>
  );
}
