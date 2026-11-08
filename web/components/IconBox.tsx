import type { LucideIcon } from "lucide-react";

export function IconBox({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border bg-bg text-accent-text">
      <Icon aria-hidden="true" className="h-5 w-5" strokeWidth={1.8} />
    </span>
  );
}
