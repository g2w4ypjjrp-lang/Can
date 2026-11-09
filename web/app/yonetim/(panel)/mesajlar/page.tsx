import type { Metadata } from "next";

import { Messages } from "@/components/admin/pages/Messages";

export const metadata: Metadata = { title: "Mesajlar" };

export default function Page() {
  return <Messages />;
}
