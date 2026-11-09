import type { Metadata } from "next";

import { Orders } from "@/components/admin/pages/Orders";

export const metadata: Metadata = { title: "Siparişler" };

export default function Page() {
  return <Orders />;
}
