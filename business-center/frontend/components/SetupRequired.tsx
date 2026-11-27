export function SetupRequired() {
  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="text-xl font-semibold">Kurulum gerekli</h1>
      <p className="mt-3 text-muted">
        Supabase bağlantısı yapılandırılmadı. <code>frontend/.env.local</code> dosyasına
        <code> NEXT_PUBLIC_SUPABASE_URL</code> ve <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> değerlerini girin.
        Ayrıntılar: <code>business-center/README.md</code>.
      </p>
    </main>
  );
}
