/** Marka işareti: mavi-lacivert degrade rozet, yükselen mumlar, trend çizgisi ve hedef düğümü (uygulama
 * simgesiyle aynı). Süs; ekran okuyucudan gizli. Degrade kimlikleri sabittir: sayfada birden çok
 * kez kullanılsa da tanımlar aynıdır. */
export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      aria-hidden="true"
      focusable="false"
      className={`shrink-0 ${className}`}
    >
      <defs>
        <linearGradient id="ati-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#4f8cff" />
          <stop offset="0.5" stopColor="#2563eb" />
          <stop offset="1" stopColor="#1e3a8a" />
        </linearGradient>
        <linearGradient id="ati-shine" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.38" />
          <stop offset="0.55" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="ati-glow" cx="0.78" cy="0.28" r="0.35">
          <stop offset="0" stopColor="#fff" stopOpacity="0.55" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="18" fill="url(#ati-bg)" />
      <rect x="2" y="2" width="60" height="60" rx="18" fill="url(#ati-glow)" />
      <rect x="2" y="2" width="60" height="60" rx="18" fill="url(#ati-shine)" />
      <rect x="2.75" y="2.75" width="58.5" height="58.5" rx="17.25" fill="none" stroke="#fff" strokeOpacity="0.35" strokeWidth="1.5" />
      <g fill="#fff" fillOpacity="0.42" stroke="#fff" strokeOpacity="0.42" strokeWidth="1.6" strokeLinecap="round">
        <line x1="17" y1="34" x2="17" y2="50" />
        <rect x="14" y="38" width="6" height="9" rx="1.6" stroke="none" />
        <line x1="27" y1="27" x2="27" y2="46" />
        <rect x="24" y="30" width="6" height="12" rx="1.6" stroke="none" />
        <line x1="37" y1="21" x2="37" y2="40" />
        <rect x="34" y="24" width="6" height="12" rx="1.6" stroke="none" />
      </g>
      <path d="M11 45 L21 35.5 L29 39 L47 20.5" fill="none" stroke="#fff" strokeWidth="3.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="48.5" cy="19" r="7.5" fill="none" stroke="#fff" strokeOpacity="0.45" strokeWidth="1.4" />
      <circle cx="48.5" cy="19" r="4.2" fill="#fff" />
      <path d="M48.5 9.2v3.2M48.5 25.6v3.2M38.7 19h3.2M55.1 19h3.2" stroke="#fff" strokeOpacity="0.7" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/** Şekillendirilmiş isim: degrade "AI", kalın "Trading", geniş aralıklı "INTELLIGENCE". */
export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex flex-col leading-none ${className}`}>
      <span className="text-[16px] font-extrabold tracking-tight text-fg">
        <span className="bg-gradient-to-r from-[#5b93ff] to-[#2563eb] bg-clip-text text-transparent">AI</span> Trading
      </span>
      <span lang="en" className="mt-[3px] text-[9.5px] font-bold uppercase tracking-[0.32em] text-accent-text">
        {" "}
        Intelligence
      </span>
    </span>
  );
}
