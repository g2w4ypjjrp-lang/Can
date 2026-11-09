import type { Metadata } from "next";

import { Panel } from "@/components/Panel";

export const metadata: Metadata = { title: "Müşteri paneli", robots: { index: false, follow: false } };

export default function PanelPage() {
  return <Panel />;
}
