"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";

export function SaveReportButton({ orgId, start, end }: { orgId: string; start: string; end: string }) {
  const router = useRouter();
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <span className="flex items-center gap-2">
      <button className="rounded-lg border border-line px-3 py-1 text-sm" onClick={async () => {
        const r = await clientApi(`/api/organizations/${orgId}/finance/reports?start=${start}&end=${end}`, { method: "POST" });
        setMsg(r.ok ? `${r.data.saved} rapor kaydedildi` : r.error ?? "Hata"); router.refresh();
      }}>Raporu kaydet</button>
      {msg && <span className="text-xs text-muted">{msg}</span>}
    </span>
  );
}
