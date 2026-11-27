export function Card({ title, children, tone }: { title: string; children: React.ReactNode; tone?: "yt" | "etsy" }) {
  const bar = tone === "yt" ? "bg-yt" : tone === "etsy" ? "bg-etsy" : "bg-brand";
  return (
    <section className="relative overflow-hidden rounded-2xl border border-line bg-panel p-4">
      <span className={`absolute inset-x-0 top-0 h-1 ${bar}`} />
      <p className="text-xs text-muted">{title}</p>
      <div className="mt-2 text-2xl font-semibold tabular-nums">{children}</div>
    </section>
  );
}

export function Muted({ children }: { children: React.ReactNode }) {
  return <span className="text-base font-normal text-muted">{children}</span>;
}
