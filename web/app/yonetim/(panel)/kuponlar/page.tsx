import type { Metadata } from "next";

import { Coupons } from "@/components/admin/pages/Coupons";

export const metadata: Metadata = { title: "İndirim kuponları" };

export default function Page() {
  return <Coupons />;
}
