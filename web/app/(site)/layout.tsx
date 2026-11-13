import type { ReactNode } from "react";

import { SiteAnnouncement } from "@/components/campaign/SiteAnnouncement";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

/** Herkese açık site: duyuru şeridi, üst menü ve risk uyarılı alt bilgi. */
export default function SiteLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <SiteAnnouncement />
      <SiteHeader />
      <main id="icerik" className="flex-1">
        {children}
      </main>
      <SiteFooter />
    </>
  );
}
