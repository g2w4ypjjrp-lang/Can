import Link from "next/link";

export function PageHeader({ title, desc, children }: { title: string; desc?: string; children?: React.ReactNode }) {
  return (
    <header className="flex flex-wrap items-end gap-3">
      <div className="min-w-0 flex-1">
        <h1 className="text-2xl font-semibold">{title}</h1>
        {desc && <p className="text-sm text-muted">{desc}</p>}
      </div>
      {children && <div className="flex flex-wrap gap-2">{children}</div>}
    </header>
  );
}

export function NotConnected({ what }: { what: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-panel p-6 text-sm">
      <p className="font-medium">{what} bağlı değil.</p>
      <p className="mt-1 text-muted">Bağlandığında gerçek veriler burada görünür; örnek veri gösterilmez.</p>
      <Link href="/integrations" className="mt-3 inline-block text-brand underline">API Integrations'a git</Link>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="rounded-xl border border-line bg-panel p-5 text-sm text-muted">{children}</p>;
}

export function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-line bg-panel p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

export const n = (v: number | string | null | undefined) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("tr-TR"));
