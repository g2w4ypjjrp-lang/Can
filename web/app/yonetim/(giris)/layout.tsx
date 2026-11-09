import type { ReactNode } from "react";

import { LogoMark } from "@/components/Logo";

export default function AdminAuthLayout({ children }: { children: ReactNode }) {
  return (
    <main id="icerik" className="flex flex-1 items-start justify-center px-4 py-12 sm:py-20">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2.5">
          <LogoMark />
          <span className="font-semibold text-fg">AI Trading Intelligence · Yönetim</span>
        </div>
        {children}
      </div>
    </main>
  );
}
