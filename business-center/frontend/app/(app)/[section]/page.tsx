import { notFound } from "next/navigation";
import { NAV } from "@/lib/nav";

export default async function Upcoming({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  const item = NAV.find((n) => n.slug === section && !n.ready);
  if (!item) notFound();
  return (
    <div className="max-w-xl">
      <h1 className="text-2xl font-semibold">{item.label}</h1>
      <p className="mt-3 rounded-xl border border-line bg-panel p-5 text-sm text-muted">
        Bu bölüm henüz geliştirilmedi. Plan: <b>Phase {item.phase}</b>. Çalışıyormuş gibi görünen sahte bir ekran yerine
        bunu açıkça belirtiyoruz.
      </p>
    </div>
  );
}
