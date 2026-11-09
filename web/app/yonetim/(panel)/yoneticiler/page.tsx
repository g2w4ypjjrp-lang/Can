import type { Metadata } from "next";

import { Admins } from "@/components/admin/pages/Admins";

export const metadata: Metadata = { title: "Yöneticiler" };

export default function Page() {
  return <Admins />;
}
