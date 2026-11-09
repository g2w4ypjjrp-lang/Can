import type { Metadata } from "next";

import { Reports } from "@/components/admin/pages/Reports";

export const metadata: Metadata = { title: "Raporlar" };

export default function Page() {
  return <Reports />;
}
