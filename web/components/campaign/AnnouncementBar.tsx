"use client";

import { ArrowRight, BellRing, CircleCheck, Flame, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Countdown } from "@/components/campaign/Countdown";
import { safeLink, type AnnouncementTone } from "@/lib/announcement";

const KEY = "ati-announcement-closed";

const TONES: Record<AnnouncementTone, { box: string; icon: typeof BellRing }> = {
  campaign: { box: "sale-gradient sale-sparkles", icon: Flame },
  info: { box: "bg-info-bg text-info-fg border-b border-info-border", icon: BellRing },
  success: { box: "bg-success-bg text-success-fg border-b border-success-border", icon: CircleCheck },
  warning: { box: "bg-warn-bg text-warn-fg border-b border-warn-border", icon: TriangleAlert },
};

export interface BarProps {
  /** Kapatma hatırlansın diye içerikten türetilen kimlik (duyuru değişince yeniden görünür). */
  id: string;
  text: string;
  link: string;
  linkLabel: string;
  tone: AnnouncementTone;
  endsAt: string | null;
}

/** Sitenin en üstündeki ince şerit. Kapatılırsa bu tarayıcıda aynı duyuru bir daha gösterilmez. */
export function AnnouncementBar({ id, text, link, linkLabel, tone, endsAt }: BarProps) {
  const [closed, setClosed] = useState(false);

  useEffect(() => {
    try {
      if (window.localStorage.getItem(KEY) === id) setClosed(true);
    } catch {
      // Depolama kapalıysa şerit her seferinde görünür.
    }
  }, [id]);

  if (closed) return null;
  const { box, icon: Icon } = TONES[tone];
  const href = safeLink(link);

  function close() {
    setClosed(true);
    try {
      window.localStorage.setItem(KEY, id);
    } catch {
      // Depolama kapalı: yalnızca bu sayfada kapanır.
    }
  }

  return (
    <aside aria-label="Duyuru" data-testid="announcement-bar" data-tone={tone} className={`relative z-50 text-sm ${box}`}>
      <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2 sm:px-6">
        <Icon aria-hidden="true" className={`h-4 w-4 shrink-0 ${tone === "campaign" ? "wiggle" : ""}`} />
        <p className="min-w-0 flex-1 font-medium leading-snug">
          <span data-testid="announcement-text">{text}</span>
          {endsAt ? (
            <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-black/15 px-2 py-0.5 text-xs">
              ⏳ <Countdown endsAt={endsAt} compact testId="announcement-countdown" />
            </span>
          ) : null}
          {href ? (
            href.startsWith("/") ? (
              <Link href={href} className="ml-3 inline-flex items-center gap-1 font-semibold underline underline-offset-4">
                {linkLabel} <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
              </Link>
            ) : (
              <a href={href} rel="noopener noreferrer" className="ml-3 inline-flex items-center gap-1 font-semibold underline underline-offset-4">
                {linkLabel} <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
              </a>
            )
          ) : null}
        </p>
        <button
          type="button"
          onClick={close}
          aria-label="Duyuruyu kapat"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-full transition-colors hover:bg-black/10 focus-visible:outline-2 focus-visible:outline-current"
        >
          <X aria-hidden="true" className="h-4 w-4" />
        </button>
      </div>
    </aside>
  );
}
