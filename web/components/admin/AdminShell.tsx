"use client";

import {
  BarChart3,
  Download,
  Inbox,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Menu,
  ScrollText,
  Settings,
  ShieldCheck,
  ShoppingCart,
  Tags,
  TicketPercent,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useApi } from "@/components/ApiContext";
import { CommandPalette } from "@/components/admin/CommandPalette";
import { useAdmin } from "@/components/admin/AdminSession";
import { LogoMark } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ADMIN_NAV, NAV_GROUPS, ROLE_LABELS, can, type NavEntry } from "@/lib/admin";

const ICONS: Record<string, LucideIcon> = {
  "/yonetim": LayoutDashboard,
  "/yonetim/siparisler": ShoppingCart,
  "/yonetim/paketler": Tags,
  "/yonetim/kuponlar": TicketPercent,
  "/yonetim/raporlar": BarChart3,
  "/yonetim/musteriler": Users,
  "/yonetim/lisanslar": KeyRound,
  "/yonetim/mesajlar": Inbox,
  "/yonetim/surumler": Download,
  "/yonetim/yoneticiler": ShieldCheck,
  "/yonetim/denetim": ScrollText,
  "/yonetim/ayarlar": Settings,
};

function isActive(pathname: string, href: string) {
  return href === "/yonetim" ? pathname === href : pathname.startsWith(href);
}

function initials(name: string, email: string) {
  const source = name.trim() || email;
  const parts = source.split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0]!.charAt(0) + parts[parts.length - 1]!.charAt(0) : source.slice(0, 2);
  return letters.toLocaleUpperCase("tr-TR");
}

function Sidebar({ items, pathname, onNavigate }: { items: NavEntry[]; pathname: string; onNavigate?: () => void }) {
  return (
    <nav aria-label="Yönetim menüsü" className="flex-1 overflow-y-auto px-3 pb-4">
      {NAV_GROUPS.map((group) => {
        const groupItems = items.filter((item) => item.group === group);
        if (!groupItems.length) return null;
        return (
          <div key={group} className="mt-5 first:mt-2">
            <p className="px-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">{group}</p>
            <ul className="mt-2 space-y-0.5">
              {groupItems.map((item) => {
                const Icon = ICONS[item.href] ?? LayoutDashboard;
                const active = isActive(pathname, item.href);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={`group relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent-text ${
                        active ? "bg-surface-3 text-fg shadow-sm" : "text-muted hover:bg-surface-2 hover:text-fg"
                      }`}
                    >
                      {active ? <span aria-hidden="true" className="absolute inset-y-2 left-0 w-1 rounded-full bg-brand" /> : null}
                      <Icon aria-hidden="true" className={`h-4 w-4 shrink-0 ${active ? "text-accent-text" : ""}`} />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

export function AdminShell({ children }: { children: ReactNode }) {
  const { me, loading } = useAdmin();
  const api = useApi();
  const router = useRouter();
  const pathname = usePathname();
  const [drawer, setDrawer] = useState(false);

  useEffect(() => setDrawer(false), [pathname]);

  if (loading && !me) {
    return (
      <main id="icerik" className="flex flex-1 items-center justify-center p-10">
        <p role="status" className="flex items-center gap-3 text-muted">
          <span aria-hidden="true" className="h-4 w-4 animate-spin rounded-full border-2 border-border border-t-accent-text" />
          Oturum denetleniyor…
        </p>
      </main>
    );
  }
  if (!me) return null;

  const items = ADMIN_NAV.filter((item) => can(me, item.permission));
  const current = ADMIN_NAV.find((item) => isActive(pathname, item.href));

  async function logout() {
    try {
      await api.post("/admin/v1/auth/logout");
    } finally {
      router.replace("/yonetim/giris");
    }
  }

  const userCard = (
    <div className="border-t border-border p-3">
      <div className="flex items-center gap-3 rounded-2xl bg-surface-2/70 p-3">
        <span aria-hidden="true" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand text-sm font-semibold text-white">
          {initials(me.full_name, me.email)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-fg">{me.full_name || "Yönetici"}</p>
          <p className="truncate text-xs text-muted" data-testid="admin-email">
            {me.email}
          </p>
          <p className="truncate text-[11px] text-muted">{me.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")}</p>
        </div>
      </div>
      <button
        type="button"
        onClick={() => void logout()}
        className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg"
      >
        <LogOut aria-hidden="true" className="h-4 w-4" />
        Çıkış yap
      </button>
    </div>
  );

  const brand = (
    <div className="flex items-center gap-3 px-5 py-5">
      <LogoMark className="h-9 w-9" />
      <div>
        <p className="text-sm font-semibold leading-tight text-fg">AI Trading Intelligence</p>
        <p className="text-xs text-muted">Yönetim paneli</p>
      </div>
    </div>
  );

  return (
    <div className="flex min-h-screen flex-1 bg-bg">
      <aside className="sticky top-0 hidden h-screen w-72 shrink-0 flex-col border-r border-border bg-surface lg:flex">
        {brand}
        <Sidebar items={items} pathname={pathname} />
        {userCard}
      </aside>

      {drawer ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button type="button" aria-label="Menüyü kapat" className="absolute inset-0 bg-[#05070e]/55 backdrop-blur-sm" onClick={() => setDrawer(false)} />
          <aside id="yonetim-cekmece" className="absolute inset-y-0 left-0 flex w-80 max-w-[85vw] flex-col border-r border-border bg-surface shadow-lift">
            <div className="flex items-center justify-between pr-3">
              {brand}
              <button type="button" aria-label="Menüyü kapat" onClick={() => setDrawer(false)} className="rounded-xl p-2 text-muted hover:bg-surface-2 hover:text-fg">
                <X aria-hidden="true" className="h-5 w-5" />
              </button>
            </div>
            <Sidebar items={items} pathname={pathname} onNavigate={() => setDrawer(false)} />
            {userCard}
          </aside>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-glass-border bg-glass-strong px-4 backdrop-blur-xl sm:px-6">
          <button
            type="button"
            aria-label="Menüyü aç"
            aria-expanded={drawer}
            aria-controls="yonetim-cekmece"
            onClick={() => setDrawer(true)}
            className="rounded-xl border border-border bg-surface p-2 text-fg shadow-sm lg:hidden"
          >
            <Menu aria-hidden="true" className="h-5 w-5" />
          </button>
          <p className="min-w-0 truncate text-sm text-muted">
            Yönetim <span aria-hidden="true">/</span> <span className="font-medium text-fg">{current?.label ?? "Panel"}</span>
          </p>
          <div className="ml-auto flex items-center gap-2">
            <CommandPalette items={items} />
            <ThemeToggle />
          </div>
        </header>
        <main id="icerik" className="mx-auto w-full max-w-[1400px] flex-1 p-4 sm:p-6 lg:p-8">
          {children}
        </main>
      </div>
    </div>
  );
}
