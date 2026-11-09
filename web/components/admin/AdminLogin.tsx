"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { Feedback, useAdminAction } from "@/components/admin/kit";
import { Button, Card, Field } from "@/components/ui";

function safeAdminNext(value: string | undefined): string {
  return value && value.startsWith("/yonetim") && !value.startsWith("//") ? value : "/yonetim";
}

export function AdminLogin({ next }: { next?: string }) {
  const api = useApi();
  const router = useRouter();
  const action = useAdminAction();
  const [challenge, setChallenge] = useState<string | null>(null);
  const [useRecovery, setUseRecovery] = useState(false);

  async function onPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const result = await action.run(() =>
      api.post<{ challenge: string }>("/admin/v1/auth/login", { email: data.get("email"), password: data.get("password") }),
    );
    if (result) setChallenge(result.challenge);
  }

  async function onCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const value = String(data.get("code") ?? "");
    const ok = await action.run(() =>
      api.post("/admin/v1/auth/verify", useRecovery ? { challenge, recovery_code: value } : { challenge, code: value }),
    );
    if (ok) router.replace(safeAdminNext(next));
  }

  return (
    <Card className="shadow-soft">
      <h1 className="text-xl font-semibold text-fg">Yönetici girişi</h1>
      {challenge === null ? (
        <form onSubmit={onPassword} className="mt-5 space-y-4">
          <Field id="email" name="email" type="email" label="E-posta" autoComplete="username" required />
          <Field id="password" name="password" type="password" label="Parola" autoComplete="current-password" required />
          <Feedback error={action.error} />
          <Button type="submit" className="w-full" disabled={action.pending}>
            Devam
          </Button>
        </form>
      ) : (
        <form onSubmit={onCode} className="mt-5 space-y-4">
          <p className="text-sm text-muted">
            {useRecovery
              ? "Kurtarma kodlarınızdan birini girin. Her kod yalnızca bir kez kullanılabilir."
              : "Doğrulama uygulamanızdaki 6 haneli kodu girin."}
          </p>
          <Field
            id="code"
            name="code"
            label={useRecovery ? "Kurtarma kodu" : "Doğrulama kodu"}
            autoComplete="one-time-code"
            inputMode={useRecovery ? "text" : "numeric"}
            required
          />
          <Feedback error={action.error} />
          <Button type="submit" className="w-full" disabled={action.pending}>
            Giriş yap
          </Button>
          <button type="button" className="text-sm text-link underline underline-offset-2" onClick={() => setUseRecovery(!useRecovery)}>
            {useRecovery ? "Doğrulama kodu kullan" : "Telefonuma erişemiyorum (kurtarma kodu)"}
          </button>
        </form>
      )}
    </Card>
  );
}
