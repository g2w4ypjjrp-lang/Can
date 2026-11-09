import type { Metadata } from "next";

import { Plans } from "@/components/admin/pages/Plans";

export const metadata: Metadata = { title: "Paketler ve fiyatlar" };

export default function Page() {
  return <Plans />;
}
