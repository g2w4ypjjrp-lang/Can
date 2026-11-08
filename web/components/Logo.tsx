export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="8" className="fill-accent" />
      <path d="M7 22l6-7 4 4 8-10" fill="none" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" className="stroke-accent-fg" />
      <circle cx="25" cy="9" r="2" className="fill-accent-fg" />
    </svg>
  );
}
