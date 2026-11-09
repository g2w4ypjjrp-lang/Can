import type { Metadata } from "next";

import { Licenses } from "@/components/admin/pages/Licenses";

export const metadata: Metadata = { title: "Lisanslar" };

export default function Page() {
  return <Licenses />;
}
