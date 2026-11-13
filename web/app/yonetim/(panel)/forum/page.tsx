import type { Metadata } from "next";

import { ForumModeration } from "@/components/admin/pages/ForumModeration";

export const metadata: Metadata = { title: "Forum onayları" };

export default function Page() {
  return <ForumModeration />;
}
