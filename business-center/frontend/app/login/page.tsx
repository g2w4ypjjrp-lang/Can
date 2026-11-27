"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { isConfigured } from "@/lib/env";
import { supabaseBrowser } from "@/lib/supabase/client";
import { SetupRequired } from "@/components/SetupRequired";

export default function Login() {
  const router = useRouter();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!isConfigured()) return <SetupRequired />;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    const sb = supabaseBrowser();
    const { error, data } = mode === "in"
      ? await sb.auth.signInWithPassword({ email, password })
      : await sb.auth.signUp({ email, password });
    setBusy(false);
    if (error) return setMsg(error.message);
    if (mode === "up" && !data.session) return setMsg("E-postanıza gelen doğrulama bağlantısına tıklayın.");
    router.replace("/dashboard"); router.refresh();
  }

  return (
    <main className="grid min-h-screen place-items-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-line bg-panel p-6 shadow-sm">
        <p className="text-xs font-semibold tracking-[.25em] text-muted">AI BUSINESS CENTER</p>
        <h1 className="mt-2 text-xl font-semibold">{mode === "in" ? "Giriş yap" : "Hesap oluştur"}</h1>
        <label className="mt-5 block text-sm">E-posta
          <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-transparent px-3 py-2" />
        </label>
        <label className="mt-3 block text-sm">Parola
          <input type="password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "in" ? "current-password" : "new-password"}
            className="mt-1 w-full rounded-lg border border-line bg-transparent px-3 py-2" />
        </label>
        {msg && <p role="alert" className="mt-3 text-sm text-yt">{msg}</p>}
        <button disabled={busy} className="mt-5 w-full rounded-lg bg-brand py-2 font-medium text-white disabled:opacity-60">
          {busy ? "Bekleyin…" : mode === "in" ? "Giriş yap" : "Kaydol"}
        </button>
        <button type="button" onClick={() => setMode(mode === "in" ? "up" : "in")} className="mt-3 w-full text-sm text-muted">
          {mode === "in" ? "Hesabın yok mu? Kaydol" : "Zaten hesabın var mı? Giriş yap"}
        </button>
      </form>
    </main>
  );
}
