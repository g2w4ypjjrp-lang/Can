import type { Metadata } from "next";

import { CrashReports } from "@/components/admin/pages/CrashReports";

export const metadata: Metadata = { title: "Hata raporları" };

export default function Page() {
  return <CrashReports />;
}
