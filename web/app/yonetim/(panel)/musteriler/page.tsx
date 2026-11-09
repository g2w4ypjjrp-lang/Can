import type { Metadata } from "next";

import { Customers } from "@/components/admin/pages/Customers";

export const metadata: Metadata = { title: "Müşteriler" };

export default function Page() {
  return <Customers />;
}
