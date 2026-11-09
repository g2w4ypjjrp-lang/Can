import type { Metadata } from "next";

import { Audit } from "@/components/admin/pages/Audit";

export const metadata: Metadata = { title: "Denetim kaydı" };

export default function Page() {
  return <Audit />;
}
