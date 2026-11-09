import type { Metadata } from "next";

import { AdminLogin } from "@/components/admin/AdminLogin";
import { firstParam } from "@/lib/format";

export const metadata: Metadata = { title: "Giriş" };

export default async function AdminLoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <AdminLogin next={firstParam((await searchParams).sonra)} />;
}
