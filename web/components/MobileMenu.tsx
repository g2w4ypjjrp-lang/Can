"use client";

import { ArrowRight, CircleHelp, Download, LifeBuoy, LogIn, Mail, Menu, Sparkles, Tag, X, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

import type { NavItem } from "@/components/NavLinks";
import { ThemeToggle } from "@/components/ThemeToggle";

const ICONS: Record<string, [LucideIcon, string]> = {
  "/ozellikler": [Sparkles, "Neler yapabilir"],
  "/paketler": [Tag, "Fiyatlar ve deneme"],
  "/indir": [Download, "Windows uygulaması"],
  "/yardim": [LifeBuoy, "Kurulum ve kullanım"],
  "/sss": [CircleHelp, "Sık sorulanlar"],
  "/iletisim": [Mail, "Bize yazın"],
};

/** Küçük ekran menüsü: tam genişlikte, simgeli kartlar ve belirgin hesap düğmeleri. JavaScript
 * olmadan da açılıp kapanır (details); sayfa değişince, Esc'te ve dışarı dokununca kapanır. */
export function MobileMenu({ items }: { items: NavItem[] }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const pathname = usePathname();

  const close = () => {
    if (ref.current) ref.current.open = false;
  };

  useEffect(close, [pathname]);

  useEffect(() => {
    const details = ref.current;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && details?.open) {
        details.open = false;
        details.querySelector("summary")?.focus();
      }
    }
    // Menü açıkken sayfa arkada kaymasın.
    function onToggle() {
      document.documentElement.style.overflow = details?.open ? "hidden" : "";
    }
    document.addEventListener("keydown", onKey);
    details?.addEventListener("toggle", onToggle);
    return () => {
      document.removeEventListener("keydown", onKey);
      details?.removeEventListener("toggle", onToggle);
      document.documentElement.style.overflow = "";
    };
  }, []);

  return (
    <details ref={ref} className="group lg:hidden">
      <summary
        aria-label="Menü"
        className="grid h-11 w-11 cursor-pointer list-none place-items-center rounded-2xl border border-border bg-surface text-fg shadow-sm transition-colors group-open:border-accent-text group-open:text-accent-text [&::-webkit-details-marker]:hidden"
      >
        <Menu aria-hidden="true" className="h-5 w-5 group-open:hidden" />
        <X aria-hidden="true" className="hidden h-5 w-5 group-open:block" />
      </summary>
      {/* Başlık bulanık zeminli olduğundan konumlar başlığa göredir: yükseklik ekran boyunca verilir. */}
      <div aria-hidden="true" onClick={close} className="fixed left-0 top-16 h-[calc(100dvh-4rem)] w-screen bg-black/40 backdrop-blur-[2px]" />
      <div className="mobile-sheet fixed left-3 right-3 top-[4.6rem] max-h-[calc(100dvh-5.6rem)] overflow-y-auto rounded-3xl border border-border bg-surface p-3 shadow-lift">
        <nav aria-label="Mobil menü">
          <ul className="grid grid-cols-2 gap-2">
            {items.map((item) => {
              const [Icon, hint] = ICONS[item.href] ?? [Sparkles, ""];
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex h-full flex-col gap-2 rounded-2xl border p-3 transition-colors focus-visible:outline-2 focus-visible:outline-accent-text ${
                      active ? "border-accent-text/40 bg-surface-2" : "border-border bg-bg/60 hover:bg-surface-2"
                    }`}
                  >
                    <span className="grid h-9 w-9 place-items-center rounded-xl bg-brand text-white shadow-glow" aria-hidden="true">
                      <Icon className="h-[18px] w-[18px]" />
                    </span>
                    <span>
                      <span className="block text-[15px] font-semibold text-fg">{item.label}</span>
                      {hint ? <span className="block text-xs text-muted">{hint}</span> : null}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="mt-3 grid gap-2">
          <Link
            href="/kayit"
            className="shine flex items-center justify-center gap-2 rounded-2xl bg-brand px-4 py-3.5 text-[15px] font-semibold text-white shadow-glow focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-text"
          >
            Hesap oluştur <ArrowRight aria-hidden="true" className="h-4 w-4" />
          </Link>
          <Link
            href="/giris"
            className="flex items-center justify-center gap-2 rounded-2xl border border-border bg-bg px-4 py-3.5 text-[15px] font-semibold text-fg focus-visible:outline-2 focus-visible:outline-accent-text"
          >
            <LogIn aria-hidden="true" className="h-4 w-4" /> Giriş yap
          </Link>
        </div>
        <div className="mt-3 flex items-center justify-between rounded-2xl bg-bg/60 px-4 py-2.5">
          <span className="text-sm font-medium text-muted">Görünüm</span>
          <ThemeToggle />
        </div>
      </div>
    </details>
  );
}
