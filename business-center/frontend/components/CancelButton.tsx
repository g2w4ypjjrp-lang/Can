"use client";
import { useRouter } from "next/navigation";
import { API_URL } from "@/lib/env";
import { supabaseBrowser } from "@/lib/supabase/client";

export function CancelButton({ id }: { id: string }) {
  const router = useRouter();
  async function cancel() {
    if (!confirm("Görev iptal edilsin mi?")) return;
    const { data } = await supabaseBrowser().auth.getSession();
    await fetch(`${API_URL}/api/tasks/${id}/cancel`, {
      method: "POST", headers: { authorization: `Bearer ${data.session?.access_token ?? ""}` },
    });
    router.refresh();
  }
  return <button onClick={cancel} className="rounded-lg border border-line px-3 py-1 text-sm">İptal et</button>;
}
