"use client";

import { Menu } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

import { NavLinks, type NavItem } from "@/components/NavLinks";
import { ThemeToggle } from "@/components/ThemeToggle";

/** Küçük ekran menüsü. JavaScript olmadan da açılıp kapanır (details); sayfa değişince kapanır. */
export function MobileMenu({ items }: { items: NavItem[] }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const pathname = usePathname();

  useEffect(() => {
    if (ref.current) ref.current.open = false;
  }, [pathname]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && ref.current?.open) {
        ref.current.open = false;
        ref.current.querySelector("summary")?.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <details ref={ref} className="group relative lg:hidden">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-full border border-border bg-surface px-4 py-2 text-sm font-medium text-fg shadow-sm">
        <Menu aria-hidden="true" className="h-4 w-4" />
        Menü
      </summary>
      <div className="glass absolute right-0 mt-3 w-72 rounded-3xl p-2 shadow-lift">
        <nav aria-label="Mobil menü">
          <ul className="flex flex-col gap-0.5">
            <NavLinks asList items={items} linkClass="block rounded-2xl px-4 py-3 text-[15px] font-medium text-fg hover:bg-surface-2" activeClass="bg-surface-2" />
          </ul>
        </nav>
        <div className="mt-1 flex items-center justify-between border-t border-border px-4 pb-2 pt-3">
          <span className="text-sm text-muted">Tema</span>
          <ThemeToggle />
        </div>
      </div>
    </details>
  );
}
