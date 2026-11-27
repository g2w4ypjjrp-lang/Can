import { ApprovalActions } from "@/components/ApprovalActions";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type Approval = { id: string; platform: string; action: string; reason: string; expected_outcome: string;
  risk_level: string; cost_amount: string | null; cost_currency: string | null; before_state: unknown;
  after_state: unknown; status: string; decision_note: string | null; expires_at: string; created_at: string };

const STATUS_TR: Record<string, string> = { pending: "Bekliyor", approved: "Onaylandı", rejected: "Reddedildi",
  expired: "Süresi doldu", executed: "Uygulandı", failed: "Başarısız" };
const RISK: Record<string, string> = { low: "Düşük", medium: "Orta", high: "Yüksek", critical: "Kritik" };

export default async function Approvals() {
  const { token, org } = await appContext();
  const list = await api<Approval[]>(`/api/organizations/${org.id}/approvals`, token);
  const canDecide = org.role === "owner" || org.role === "admin";
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Approval Center</h1>
        <p className="text-sm text-muted">Kritik işlemler onayınız olmadan yapılmaz. Süresi dolan onaylar otomatik reddedilir.</p>
      </header>
      {list.length === 0 && <p className="rounded-xl border border-line bg-panel p-6 text-sm text-muted">Onay bekleyen işlem yok.</p>}
      {list.map((a) => {
        const pending = a.status === "pending" && new Date(a.expires_at) > new Date();
        return (
          <article key={a.id} className="rounded-2xl border border-line bg-panel p-5">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="rounded bg-canvas px-2 py-0.5 uppercase">{a.platform}</span>
              <span className="rounded bg-canvas px-2 py-0.5">Risk: {RISK[a.risk_level]}</span>
              <span className="rounded bg-canvas px-2 py-0.5">Durum: {STATUS_TR[a.status] ?? a.status}</span>
              <span className="text-muted">Son: {new Date(a.expires_at).toLocaleString("tr-TR")}</span>
            </div>
            <h2 className="mt-2 font-semibold">{a.action}</h2>
            <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
              <div><dt className="text-muted">Neden</dt><dd>{a.reason}</dd></div>
              <div><dt className="text-muted">Beklenen sonuç</dt><dd>{a.expected_outcome}</dd></div>
              <div><dt className="text-muted">Maliyet</dt><dd>{a.cost_amount ? `${a.cost_amount} ${a.cost_currency}` : "Yok"}</dd></div>
            </dl>
            <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
              <pre className="overflow-auto rounded-lg bg-canvas p-3"><b>Önce</b>{"\n"}{JSON.stringify(a.before_state, null, 2) ?? "—"}</pre>
              <pre className="overflow-auto rounded-lg bg-canvas p-3"><b>Sonra</b>{"\n"}{JSON.stringify(a.after_state, null, 2)}</pre>
            </div>
            {a.decision_note && <p className="mt-2 text-sm text-muted">Not: {a.decision_note}</p>}
            {pending && canDecide && <ApprovalActions id={a.id} />}
          </article>
        );
      })}
    </div>
  );
}
