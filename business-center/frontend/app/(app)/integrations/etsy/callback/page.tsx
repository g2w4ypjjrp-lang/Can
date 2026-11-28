import { Suspense } from "react";
import { EtsyCallback } from "@/components/EtsyCallback";
import { appContext } from "@/lib/context";

export default async function Page() {
  const { org } = await appContext();
  return <Suspense><EtsyCallback orgId={org.id} /></Suspense>;
}
