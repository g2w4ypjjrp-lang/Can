"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV } from "@/lib/nav";

export function Sidebar({ orgName, email }: { orgName: string; email: string | null }) {
  const path = usePathname();
  return (
    <aside className="border-b border-line bg-panel md:sticky md:top-0 md:h-screen md:w-64 md:shrink-0 md:overflow-y-auto md:border-r md:border-b-0">
      <div className="p-4">
        <p className="text-[10px] font-semibold tracking-[.25em] text-muted">AI BUSINESS CENTER</p>
        <p className="mt-1 truncate font-semibold">{orgName}</p>
        <p className="truncate text-xs text-muted">{email}</p>
      </div>
      <nav className="flex gap-1 overflow-x-auto px-2 pb-3 md:flex-col md:overflow-visible">
        {NAV.map((n) => {
          const active = path === `/${n.slug}`;
          return (
            <Link key={n.slug} href={`/${n.slug}`}
              className={`flex shrink-0 items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm ${
                active ? "bg-brand text-white" : "hover:bg-canvas"}`}>
              <span>{n.label}</span>
              {!n.ready && <span className={`text-[10px] ${active ? "text-white/80" : "text-muted"}`}>P{n.phase}</span>}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
