import type { Metadata } from "next";

import { CoinNews } from "@/components/admin/pages/CoinNews";

export const metadata: Metadata = { title: "Coin haberleri" };

export default function Page() {
  return <CoinNews />;
}
