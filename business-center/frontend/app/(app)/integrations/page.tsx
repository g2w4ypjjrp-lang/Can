import { PrintifyCard } from "@/components/PrintifyCard";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type I = { provider: string; status: string; display_name?: string | null; last_error?: string | null;
  last_synced_at?: string | null; product_count?: number };

const BADGE: Record<string, string> = { connected: "bg-emerald-100 text-emerald-800", error: "bg-rose-100 text-rose-800",
  disconnected: "bg-slate-100 text-slate-600", revoked: "bg-slate-100 text-slate-600" };
const LABEL: Record<string, string> = { connected: "Bağlı", error: "Hata", disconnected: "Bağlı değil", revoked: "İptal edildi" };

function Card({ title, tone, status, children }: { title: string; tone: string; status: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-panel p-5" style={{ borderTop: `3px solid ${tone}` }}>
      <div className="mb-3 flex items-center gap-2">
        <h2 className="font-semibold">{title}</h2>
        <span className={`ml-auto rounded-full px-2 py-0.5 text-[11px] font-medium ${BADGE[status] ?? BADGE.disconnected}`}>{LABEL[status] ?? status}</span>
      </div>
      {children}
    </section>
  );
}

export default async function Integrations() {
  const { token, org } = await appContext();
  const s = await api<Record<"youtube" | "etsy" | "printify", I>>(`/api/organizations/${org.id}/integrations`, token);
  const canEdit = org.role !== "viewer";
  return (
    <div className="max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">API Integrations</h1>
        <p className="text-sm text-muted">Bağlantı bilgileri sunucuda şifreli saklanır. Ajanlar bu hesaplarda hiçbir değişikliği onayınız olmadan yapamaz.</p>
      </header>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Printify" tone="#16a34a" status={s.printify.status}>
          <PrintifyCard orgId={org.id} state={s.printify} canEdit={canEdit} />
        </Card>
        <Card title="Etsy" tone="#ea580c" status={s.etsy.status}>
          <p className="text-sm text-muted">OAuth bağlantısı geliştiriliyor. Gerekecek: Etsy geliştirici hesabında onaylanmış bir uygulama (keystring) ve yönlendirme adresi.</p>
        </Card>
        <Card title="YouTube" tone="#e11d48" status={s.youtube.status}>
          <p className="text-sm text-muted">OAuth bağlantısı geliştiriliyor. Gerekecek: Google Cloud projesinde YouTube Data + Analytics API'leri ve OAuth istemcisi.</p>
        </Card>
      </div>
    </div>
  );
}
