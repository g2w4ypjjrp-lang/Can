import { Suspense } from "react";
import { OAuthCallback } from "@/components/OAuthCallback";
import { appContext } from "@/lib/context";

export default async function Page() {
  const { org } = await appContext();
  return <Suspense><OAuthCallback provider="youtube" orgId={org.id} /></Suspense>;
}
