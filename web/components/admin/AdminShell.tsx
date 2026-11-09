"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { useApi } from "@/components/ApiContext";
import { useAdmin } from "@/components/admin/AdminSession";
import { LogoMark } from "@/components/Logo";
import { ADMIN_NAV, ROLE_LABELS, can } from "@/lib/admin";

export function AdminShell({ children }: { children: ReactNode }) {
  const { me, loading } = useAdmin();
  const api = useApi();
  const router = useRouter();
  const pathname = usePathname();

  if (loading && !me) {
    return (
      <main id="icerik" className="flex flex-1 items-center justify-center p-10">
        <p role="status" className="text-muted">
          Oturum denetleniyor…
        </p>
      </main>
    );
  }
  if (!me) return null;

  async function logout() {
    try {
      await api.post("/admin/v1/auth/logout");
    } finally {
      router.replace("/yonetim/giris");
    }
  }

  return (
    <div className="flex flex-1 flex-col lg:flex-row">
      <aside className="border-b border-border bg-surface lg:w-64 lg:shrink-0 lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-2.5 px-5 py-4">
          <LogoMark className="h-7 w-7" />
          <span className="text-sm font-semibold text-fg">Yönetim paneli</span>
        </div>
        <nav aria-label="Yönetim menüsü" className="px-3 pb-4">
          <ul className="flex flex-wrap gap-1 lg:flex-col">
            {ADMIN_NAV.filter((item) => can(me, item.permission)).map((item) => {
              const active = item.href === "/yonetim" ? pathname === item.href : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`block rounded-lg px-3 py-2 text-sm font-medium hover:bg-surface-2 ${active ? "bg-surface-2 text-fg" : "text-muted"}`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="border-t border-border px-5 py-4 text-sm">
          <p className="font-medium text-fg" data-testid="admin-email">
            {me.email}
          </p>
          <p className="text-xs text-muted">{me.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")}</p>
          <button type="button" onClick={() => void logout()} className="mt-3 text-sm font-medium text-link underline underline-offset-2">
            Çıkış yap
          </button>
        </div>
      </aside>
      <main id="icerik" className="min-w-0 flex-1 p-5 sm:p-8">
        {children}
      </main>
    </div>
  );
}
