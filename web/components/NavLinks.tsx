"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export interface NavItem {
  href: string;
  label: string;
}

/** Menü bağlantıları; bulunulan sayfa aria-current ile işaretlenir. */
export function NavLinks({ items, linkClass, activeClass, asList = false }: { items: NavItem[]; linkClass: string; activeClass: string; asList?: boolean }) {
  const pathname = usePathname();
  const links = items.map((item) => {
    const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
    const link = (
      <Link key={item.href} href={item.href} aria-current={active ? "page" : undefined} className={`${linkClass} ${active ? activeClass : ""}`}>
        {item.label}
      </Link>
    );
    return asList ? <li key={item.href}>{link}</li> : link;
  });
  return <>{links}</>;
}
