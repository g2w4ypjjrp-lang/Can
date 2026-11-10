import { LockKeyhole, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import { LogoMark } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Backdrop } from "@/components/ui";

export default function AdminAuthLayout({ children }: { children: ReactNode }) {
  return (
    <main id="icerik" className="relative flex flex-1 items-start justify-center overflow-hidden px-4 py-12 sm:py-20">
      <Backdrop />
      <div className="relative w-full max-w-md">
        <div className="mb-8 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <LogoMark className="h-10 w-10" />
            <div>
              <p className="font-semibold leading-tight text-fg">AI Trading Intelligence</p>
              <p className="text-xs text-muted">Yönetim paneli</p>
            </div>
          </div>
          <ThemeToggle />
        </div>
        {children}
        <ul className="mt-6 flex flex-wrap justify-center gap-x-5 gap-y-2 text-xs text-muted">
          <li className="flex items-center gap-1.5">
            <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5 text-success-fg" /> İki adımlı doğrulama zorunlu
          </li>
          <li className="flex items-center gap-1.5">
            <LockKeyhole aria-hidden="true" className="h-3.5 w-3.5 text-accent-text" /> Oturum yalnızca bu alan adında
          </li>
        </ul>
      </div>
    </main>
  );
}
