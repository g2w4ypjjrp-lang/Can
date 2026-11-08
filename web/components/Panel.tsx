"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useApi } from "@/components/ApiContext";
import { Button, Card, Container, LinkButton, Notice } from "@/components/ui";
import { ApiError, type Me } from "@/lib/api";
import { formatDate, licenseStatusLabel } from "@/lib/format";

type State = { kind: "loading" } | { kind: "ready"; me: Me } | { kind: "error"; message: string };

export function Panel() {
  const api = useApi();
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .get<Me>("/v1/me")
      .then((me) => {
        if (!cancelled) setState({ kind: "ready", me });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/giris?sonra=/panel");
          return;
        }
        setState({ kind: "error", message: err instanceof Error ? err.message : "Bilgiler yüklenemedi" });
      });
    return () => {
      cancelled = true;
    };
  }, [api, router]);

  async function logout() {
    setLeaving(true);
    try {
      await api.post("/v1/auth/logout");
    } catch {
      // Oturum zaten geçersizse de giriş sayfasına dönülür.
    }
    router.replace("/giris");
  }

  if (state.kind === "loading") {
    return (
      <Container className="py-16">
        <p role="status" className="text-muted">
          Hesap bilgileriniz yükleniyor…
        </p>
      </Container>
    );
  }
  if (state.kind === "error") {
    return (
      <Container className="py-16">
        <Notice tone="danger" role="alert">
          {state.message}
        </Notice>
      </Container>
    );
  }

  const { me } = state;
  return (
    <Container className="py-12">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-fg">Müşteri paneli</h1>
          <p className="mt-2 text-muted">
            {me.full_name ? `${me.full_name} · ` : ""}
            <span data-testid="panel-email">{me.email}</span>
          </p>
        </div>
        <Button variant="secondary" onClick={() => void logout()} disabled={leaving}>
          {leaving ? "Çıkış yapılıyor…" : "Çıkış yap"}
        </Button>
      </div>

      <section aria-labelledby="lisanslar" className="mt-10">
        <h2 id="lisanslar" className="text-xl font-semibold text-fg">
          Lisanslarım
        </h2>
        {me.licenses.length === 0 ? (
          <Card className="mt-4">
            <p className="text-fg">Henüz bir lisansınız yok.</p>
            <p className="mt-1 text-sm text-muted">Satın aldığınız lisanslar burada, cihaz kullanımıyla birlikte görünür.</p>
            <LinkButton href="/paketler" className="mt-4">
              Paketleri inceleyin
            </LinkButton>
          </Card>
        ) : (
          <div className="mt-4 overflow-x-auto rounded-xl border border-border bg-surface">
            <table className="w-full min-w-[640px] text-left text-sm">
              <caption className="visually-hidden">Lisanslarınız</caption>
              <thead className="bg-surface-2 text-fg">
                <tr>
                  <th scope="col" className="px-4 py-3 font-semibold">Paket</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Anahtar</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Durum</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Cihaz</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Bitiş</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {me.licenses.map((license) => (
                  <tr key={license.id}>
                    <td className="px-4 py-3 text-fg">{license.plan_name}</td>
                    <td className="px-4 py-3 font-mono text-fg">{license.key_hint}</td>
                    <td className="px-4 py-3 text-fg">{licenseStatusLabel(license.status)}</td>
                    <td className="px-4 py-3 text-fg">
                      {license.active_devices} / {license.device_limit}
                    </td>
                    <td className="px-4 py-3 text-fg">
                      {license.expires_at ? formatDate(license.expires_at) : license.activated_at ? "Süresiz" : "Etkinleştirmeden başlar"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-sm text-muted">
          Güvenliğiniz için lisans anahtarının tamamı panelde gösterilmez; satın alma sonrasında e-postayla iletilir.
        </p>
      </section>

      <section aria-labelledby="hesap" className="mt-10">
        <h2 id="hesap" className="text-xl font-semibold text-fg">
          Hesap
        </h2>
        <Card className="mt-4">
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-[12rem_1fr]">
            <dt className="text-muted">E-posta</dt>
            <dd className="text-fg">{me.email} {me.email_verified ? "(doğrulandı)" : "(doğrulanmadı)"}</dd>
            <dt className="text-muted">Üyelik tarihi</dt>
            <dd className="text-fg">{formatDate(me.created_at)}</dd>
          </dl>
          <p className="mt-4 text-sm text-muted">
            Parolanızı değiştirmek için çıkış yapıp “Parolamı unuttum” adımını kullanabilirsiniz. Kişisel verilerinizle
            ilgili talepler için iletişim formunda “Kişisel veriler” konusunu seçin.
          </p>
        </Card>
      </section>
    </Container>
  );
}
