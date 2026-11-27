import { redirect } from "next/navigation";
import { api, type Me } from "./api";
import { session } from "./supabase/server";

/** Korumalı sayfalar için: oturum, kullanıcı ve aktif organizasyon. */
export async function appContext() {
  const s = await session();
  if (!s) redirect("/login");
  const me = await api<Me>("/api/me", s.token);
  const org = me.organizations[0];
  if (!org) redirect("/onboarding");
  return { token: s.token, me, org };
}
