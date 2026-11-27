"use client";
import { API_URL } from "./env";
import { supabaseBrowser } from "./supabase/client";

/** Tarayıcıdan backend'e kullanıcının oturum tokenıyla istek. Hata metnini döndürür. */
export async function clientApi(path: string, init?: RequestInit): Promise<{ ok: boolean; data: any; error?: string }> {
  const { data } = await supabaseBrowser().auth.getSession();
  const r = await fetch(API_URL + path, {
    ...init,
    headers: { ...init?.headers, authorization: `Bearer ${data.session?.access_token ?? ""}`, "content-type": "application/json" },
  });
  const body = r.status === 204 ? null : await r.json().catch(() => null);
  if (r.ok) return { ok: true, data: body };
  const detail = body?.detail;
  const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d: any) => d.msg).join(", ") : `HTTP ${r.status}`;
  return { ok: false, data: null, error: msg };
}
