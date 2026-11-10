import type { Metadata } from "next";

import { Releases } from "@/components/admin/pages/Releases";

export const metadata: Metadata = { title: "Sürümler" };

export default function Page() {
  return <Releases />;
}
