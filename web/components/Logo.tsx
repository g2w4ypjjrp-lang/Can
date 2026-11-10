/** Marka işareti: degrade kare içinde yükselen çizgi. Süs; ekran okuyucudan gizli. */
export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <span aria-hidden="true" className={`relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-[28%] bg-brand shadow-glow ${className}`}>
      <span className="absolute inset-0 bg-gradient-to-b from-white/25 to-transparent" />
      <svg viewBox="0 0 32 32" className="relative h-full w-full" focusable="false">
        <path d="M7 22l6-7 4 4 8-10" fill="none" stroke="#ffffff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="25" cy="9" r="2.1" fill="#ffffff" />
      </svg>
    </span>
  );
}

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`text-[15px] font-semibold tracking-tight text-fg ${className}`}>
      AI Trading <span className="text-accent-text">Intelligence</span>
    </span>
  );
}
