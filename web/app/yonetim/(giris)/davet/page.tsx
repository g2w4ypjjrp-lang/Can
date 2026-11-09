import type { Metadata } from "next";

import { AdminInvite } from "@/components/admin/AdminInvite";
import { firstParam } from "@/lib/format";

export const metadata: Metadata = { title: "Davet" };

export default async function AdminInvitePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <AdminInvite token={firstParam((await searchParams).token)} />;
}
