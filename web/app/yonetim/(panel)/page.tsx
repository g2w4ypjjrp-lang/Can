import type { Metadata } from "next";

import { Dashboard } from "@/components/admin/pages/Dashboard";

export const metadata: Metadata = { title: "Özet" };

export default function Page() {
  return <Dashboard />;
}
