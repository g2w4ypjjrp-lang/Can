import { FinanceEntryForm } from "@/components/FinanceEntryForm";
import { SaveReportButton } from "@/components/SaveReportButton";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type Scope = { by_currency: Record<string, Record<string, string | null>>; missing_data: string[] };
type Summary = { scopes: Record<"youtube" | "etsy" | "combined", Scope> };

const ROWS: [string, string][] = [
  ["gross_revenue", "Brüt gelir"], ["discount", "İndirimler"], ["refund", "İade ve iptaller"],
  ["collected_revenue", "Tahsil edilen gelir"], ["platform_fees", "Platform ücretleri"],
  ["expense_production", "Üretim (Printify)"], ["expense_shipping", "Kargo"], ["expense_advertising", "Reklam"],
  ["expense_voiceover", "Seslendirme"], ["expense_software_ai", "Yazılım ve AI"], ["expense_other", "Diğer giderler"],
  ["net_profit", "Net kâr"], ["margin_pct", "Kâr marjı %"], ["tax_reported_separately", "Vergi (ayrı)"],
];
const TITLES = { youtube: "YouTube", etsy: "Etsy", combined: "Birleşik" };

function money(v: string | null | undefined, cur: string) {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat("tr-TR", { style: "currency", currency: cur }).format(Number(v));
}

export default async function Finance({ searchParams }: { searchParams: Promise<{ start?: string; end?: string }> }) {
  const { token, org } = await appContext();
  const sp = await searchParams;
  const valid = (s?: string) => (s && /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : undefined);
  const now = new Date();
  const start = valid(sp.start) ?? new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
  const end = valid(sp.end) ?? now.toISOString().slice(0, 10);
  const s = await api<Summary>(`/api/organizations/${org.id}/finance/summary?start=${start}&end=${end}`, token);
  const admin = org.role !== "viewer";

  return (
    <div className="max-w-6xl space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Financial Reports</h1>
        <p className="text-sm text-muted">Net Kâr = Tahsil Edilen Gelir − Üretim − Platform Ücretleri − Reklam − Diğer. Vergi ayrı
          gösterilir. Para birimleri birbirine eklenmez. Eksik veri varsa rapor doğrulanmamış sayılır.</p>
        <form className="flex flex-wrap items-center gap-2 text-sm">
          <input type="date" name="start" defaultValue={start} className="rounded-lg border border-line bg-transparent px-2 py-1" />
          <span>–</span>
          <input type="date" name="end" defaultValue={end} className="rounded-lg border border-line bg-transparent px-2 py-1" />
          <button className="rounded-lg border border-line px-3 py-1">Göster</button>
          {admin && <SaveReportButton orgId={org.id} start={start} end={end} />}
        </form>
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        {(["youtube", "etsy", "combined"] as const).map((k) => {
          const sc = s.scopes[k];
          const curs = Object.keys(sc.by_currency);
          return (
            <section key={k} className="rounded-2xl border border-line bg-panel p-4">
              <h2 className="font-semibold">{TITLES[k]}</h2>
              {!curs.length && <p className="mt-2 text-sm text-muted">Bu dönem için kayıt yok.</p>}
              {curs.map((cur) => (
                <table key={cur} className="mt-3 w-full text-sm">
                  <caption className="text-left text-xs text-muted">{cur}</caption>
                  <tbody>
                    {ROWS.filter(([key]) => sc.by_currency[cur][key] != null).map(([key, label]) => (
                      <tr key={key} className={key === "net_profit" ? "font-semibold" : ""}>
                        <td className="py-0.5 text-muted">{label}</td>
                        <td className="py-0.5 text-right tabular-nums">
                          {key === "margin_pct" ? `%${Number(sc.by_currency[cur][key]).toLocaleString("tr-TR", { minimumFractionDigits: 2 })}` : money(sc.by_currency[cur][key], cur)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ))}
              {sc.missing_data.length > 0 && (
                <ul className="mt-3 space-y-1 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">
                  {sc.missing_data.map((m) => <li key={m}>⚠ {m}</li>)}
                </ul>
              )}
            </section>
          );
        })}
      </div>
      {admin && <FinanceEntryForm orgId={org.id} />}
    </div>
  );
}
