"use client";
import { useRouter } from "next/navigation";
import { clientApi } from "@/lib/client-api";

export function MarkAllRead({ orgId }: { orgId: string }) {
  const router = useRouter();
  return (
    <button className="rounded-lg border border-line px-3 py-1 text-sm"
      onClick={async () => { await clientApi(`/api/organizations/${orgId}/notifications/read`, { method: "POST" }); router.refresh(); }}>
      Tümünü okundu say
    </button>
  );
}
