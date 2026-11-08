"use client";

import { Notice } from "@/components/ui";
import type { ApiError } from "@/lib/api";

export function ErrorBox({ error }: { error: ApiError | null }) {
  if (!error) return null;
  return (
    <Notice tone="danger" role="alert">
      {error.message}
    </Notice>
  );
}
