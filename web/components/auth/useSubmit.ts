"use client";

import { useState } from "react";

import { ApiError, NETWORK_ERROR } from "@/lib/api";

/** Form gönderimi durumu: bekleniyor, hata (API mesajı), başarı mesajı. */
export function useSubmit() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function run(action: () => Promise<string | null | void>) {
    setPending(true);
    setError(null);
    try {
      const message = await action();
      if (typeof message === "string") setDone(message);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, NETWORK_ERROR));
    } finally {
      setPending(false);
    }
  }

  return { pending, error, done, run, setDone };
}

export function formValue(form: HTMLFormElement, name: string): string {
  const value = new FormData(form).get(name);
  return typeof value === "string" ? value : "";
}
