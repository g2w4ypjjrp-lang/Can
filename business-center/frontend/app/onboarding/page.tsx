import { redirect } from "next/navigation";
import { api, type Me } from "@/lib/api";
import { session } from "@/lib/supabase/server";

async function create(form: FormData) {
  "use server";
  const s = await session();
  if (!s) redirect("/login");
  const name = String(form.get("name") ?? "").trim().slice(0, 120);
  if (name) await api("/api/organizations", s.token, { method: "POST", body: JSON.stringify({ name }) });
  redirect("/dashboard");
}

export default async function Onboarding() {
  const s = await session();
  if (!s) redirect("/login");
  const me = await api<Me>("/api/me", s.token);
  if (me.organizations.length) redirect("/dashboard");
  return (
    <main className="grid min-h-screen place-items-center p-4">
      <form action={create} className="w-full max-w-sm rounded-2xl border border-line bg-panel p-6">
        <h1 className="text-xl font-semibold">İşletmenizi oluşturun</h1>
        <p className="mt-1 text-sm text-muted">CEO, YouTube, Etsy ve Kalite Kontrol ekipleri (21 ajan) otomatik kurulur.</p>
        <input name="name" required maxLength={120} placeholder="İşletme adı"
          className="mt-4 w-full rounded-lg border border-line bg-transparent px-3 py-2" />
        <button className="mt-4 w-full rounded-lg bg-brand py-2 text-white">Oluştur</button>
      </form>
    </main>
  );
}
