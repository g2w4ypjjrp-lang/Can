'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { Menu, Store, X } from 'lucide-react';
import { NAV_ITEMS } from '@esm/shared';
import { NavIcon } from './nav-icon';

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const isActive = (href: string) =>
    href === '/dashboard'
      ? pathname === '/dashboard'
      : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed left-3 top-3 z-40 rounded-lg border border-line bg-white p-2 shadow-sm lg:hidden"
        aria-label="Menüyü aç"
      >
        <Menu className="h-5 w-5 text-navy-900" aria-hidden />
      </button>
      {open && (
        <div
          className="fixed inset-0 z-40 bg-slate-900/30 lg:hidden"
          onClick={() => setOpen(false)}
          aria-hidden
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-line bg-white transition-transform lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
        aria-label="Ana menü"
      >
        <div className="flex h-16 items-center justify-between border-b border-line px-5">
          <Link
            href="/dashboard"
            className="flex items-center gap-2.5"
            onClick={() => setOpen(false)}
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-navy-900 text-white">
              <Store className="h-4 w-4" aria-hidden />
            </span>
            <span className="text-sm font-semibold leading-tight text-navy-900">
              Etsy AI
              <br />
              <span className="font-normal text-slate-500">Store Manager</span>
            </span>
          </Link>
          <button
            type="button"
            className="lg:hidden"
            onClick={() => setOpen(false)}
            aria-label="Menüyü kapat"
          >
            <X className="h-5 w-5 text-slate-500" aria-hidden />
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-4">
          <ul className="space-y-0.5">
            {NAV_ITEMS.map((item, i) => {
              const active = isActive(item.href);
              return (
                <li key={item.slug}>
                  <Link
                    href={item.href}
                    onClick={() => setOpen(false)}
                    aria-current={active ? 'page' : undefined}
                    className={`group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                      active
                        ? 'bg-brand-50 font-semibold text-brand-600'
                        : 'text-slate-600 hover:bg-slate-50 hover:text-navy-900'
                    }`}
                  >
                    <span className="w-4 text-right text-[11px] tabular-nums text-slate-400">
                      {i + 1}
                    </span>
                    <NavIcon name={item.icon} className="h-4 w-4 shrink-0" />
                    <span className="flex-1 truncate">{item.label}</span>
                    {item.status === 'planned' && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                        F{item.phase}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </aside>
    </>
  );
}
