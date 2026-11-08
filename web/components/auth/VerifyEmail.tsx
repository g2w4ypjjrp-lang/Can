"use client";

import { useEffect } from "react";

import { useApi } from "@/components/ApiContext";
import { ErrorBox } from "@/components/auth/ErrorBox";
import { useSubmit } from "@/components/auth/useSubmit";
import { Button, LinkButton, Notice } from "@/components/ui";
import type { Message } from "@/lib/api";

/** Doğrulama bağlantısı yalnızca düğmeye basılınca kullanılır (e-posta tarayıcılarının
 *  bağlantıyı önceden açması hesabı doğrulamaz). Belirteç adres çubuğundan silinir. */
export function VerifyEmail({ token }: { token: string | undefined }) {
  const api = useApi();
  const submit = useSubmit();

  useEffect(() => {
    if (token) window.history.replaceState(null, "", "/eposta-dogrula");
  }, [token]);

  if (!token) {
    return (
      <Notice tone="danger" role="alert">
        Doğrulama bağlantısı eksik. E-postanızdaki bağlantıyı tam olarak açın.
      </Notice>
    );
  }
  if (submit.done) {
    return (
      <div className="space-y-5">
        <Notice tone="success" role="status">
          {submit.done}
        </Notice>
        <LinkButton href="/giris" className="w-full">
          Giriş yap
        </LinkButton>
      </div>
    );
  }
  return (
    <div className="space-y-5">
      <p className="text-fg">Hesabınızı etkinleştirmek için e-posta adresinizi doğrulayın.</p>
      <ErrorBox error={submit.error} />
      <Button
        type="button"
        className="w-full"
        disabled={submit.pending}
        onClick={() =>
          void submit.run(async () => (await api.post<Message>("/v1/auth/verify-email", { token })).message ?? "Doğrulandı.")
        }
      >
        {submit.pending ? "Doğrulanıyor…" : "E-postamı doğrula"}
      </Button>
    </div>
  );
}
