"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

import { NavLinks, type NavItem } from "@/components/NavLinks";

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
    <details ref={ref} className="relative md:hidden">
      <summary className="cursor-pointer list-none rounded-full border border-border bg-surface px-4 py-2 text-sm font-medium text-fg">
        Menü
      </summary>
      <nav aria-label="Mobil menü" className="absolute right-0 mt-2 w-60 rounded-2xl border border-border bg-surface p-2 shadow-soft">
        <ul className="flex flex-col gap-0.5">
          <NavLinks asList items={items} linkClass="block rounded-xl px-3 py-2.5 text-sm font-medium text-fg hover:bg-surface-2" activeClass="bg-surface-2" />
        </ul>
      </nav>
    </details>
  );
}
