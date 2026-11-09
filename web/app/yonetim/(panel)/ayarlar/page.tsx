import type { Metadata } from "next";

import { Settings } from "@/components/admin/pages/Settings";

export const metadata: Metadata = { title: "Ayarlar" };

export default function Page() {
  return <Settings />;
}
