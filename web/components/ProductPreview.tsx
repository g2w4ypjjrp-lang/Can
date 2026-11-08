// Ana sayfadaki örnek arayüz görselleri. Yalnızca süs amaçlıdır (ekran okuyucudan gizli) ve
// kazanç/kâr rakamı içermez; altında "örnek arayüz" açıklaması bulunur.

const SCANNER = [
  { symbol: "SOLUSDT", score: 82, tag: "Trend" },
  { symbol: "ETHUSDT", score: 74, tag: "Hacim artışı" },
  { symbol: "BNBUSDT", score: 61, tag: "Sıkışma" },
  { symbol: "XRPUSDT", score: 55, tag: "Balina alımı" },
];

function Chart() {
  return (
    <svg viewBox="0 0 320 120" className="h-28 w-full" preserveAspectRatio="none">
      <defs>
        <linearGradient id="onizleme-alan" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.35" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[30, 60, 90].map((y) => (
        <line key={y} x1="0" x2="320" y1={y} y2={y} stroke="var(--grid-line)" strokeWidth="1" />
      ))}
      <path
        d="M0 92 L20 88 L40 94 L60 80 L80 84 L100 70 L120 74 L140 58 L160 64 L180 50 L200 56 L220 42 L240 48 L260 36 L280 40 L300 28 L320 32 L320 120 L0 120 Z"
        fill="url(#onizleme-alan)"
      />
      <path
        d="M0 92 L20 88 L40 94 L60 80 L80 84 L100 70 L120 74 L140 58 L160 64 L180 50 L200 56 L220 42 L240 48 L260 36 L280 40 L300 28 L320 32"
        fill="none"
        stroke="var(--accent)"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path d="M0 96 C80 92 160 80 240 62 S300 46 320 44" fill="none" stroke="var(--accent-2)" strokeWidth="1.5" strokeDasharray="4 4" />
    </svg>
  );
}

export function ProductPreview() {
  return (
    <figure className="relative">
      <div aria-hidden="true" className="absolute -inset-6 rounded-[2rem] bg-accent/10 blur-2xl" />
      <div aria-hidden="true" className="relative overflow-hidden rounded-2xl border border-border bg-surface shadow-soft">
        <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
          <span className="h-2.5 w-2.5 rounded-full bg-danger-border" />
          <span className="h-2.5 w-2.5 rounded-full bg-warn-border" />
          <span className="h-2.5 w-2.5 rounded-full bg-success-border" />
          <span className="ml-2 text-xs font-medium text-muted">Genel bakış</span>
          <span className="ml-auto rounded-full bg-info-bg px-2 py-0.5 text-[11px] font-semibold text-info-fg">Sanal işlem</span>
        </div>
        <div className="grid gap-3 p-4 sm:grid-cols-5">
          <div className="rounded-xl border border-border bg-bg p-3 sm:col-span-3">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-fg">BTCUSDT · 1 saat</span>
              <span className="text-muted">EMA trend</span>
            </div>
            <Chart />
            <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
              <span className="rounded-full bg-surface-2 px-2 py-0.5 text-fg">Balina: alış kümesi</span>
              <span className="rounded-full bg-surface-2 px-2 py-0.5 text-fg">Emir defteri duvarı</span>
            </div>
          </div>
          <div className="rounded-xl border border-border bg-bg p-3 sm:col-span-2">
            <p className="text-xs font-semibold text-fg">Fırsat tarayıcı</p>
            <ul className="mt-2 space-y-2">
              {SCANNER.map((row) => (
                <li key={row.symbol} className="text-[11px]">
                  <div className="flex justify-between">
                    <span className="font-medium text-fg">{row.symbol}</span>
                    <span className="text-muted">{row.tag}</span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-surface-2">
                    <div className={`h-1.5 rounded-full bg-accent ${row.score > 80 ? "w-[82%]" : row.score > 70 ? "w-[74%]" : row.score > 60 ? "w-[61%]" : "w-[55%]"}`} />
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div className="flex items-center gap-4 rounded-xl border border-border bg-bg p-3 sm:col-span-5">
            <div className="min-w-0 flex-1">
              <div className="flex justify-between text-[11px]">
                <span className="font-medium text-fg">Günlük zarar sınırı kullanımı</span>
                <span className="text-muted">%2 sınır</span>
              </div>
              <div className="mt-1.5 h-1.5 rounded-full bg-surface-2">
                <div className="h-1.5 w-[22%] rounded-full bg-success-fg" />
              </div>
            </div>
            <span className="shrink-0 rounded-full border border-danger-border px-3 py-1 text-[11px] font-semibold text-danger-fg">Acil durdurma</span>
          </div>
        </div>
      </div>
      <figcaption className="relative mt-3 text-center text-xs text-muted">Örnek arayüz görüntüsüdür; gerçek piyasa verisi veya işlem sonucu içermez.</figcaption>
    </figure>
  );
}

export function PhonePreview() {
  return (
    <div aria-hidden="true" className="mx-auto w-52 rounded-[2.2rem] border border-border-strong/50 bg-bg p-2.5 shadow-soft">
      <div className="rounded-[1.7rem] border border-border bg-surface px-4 pb-5 pt-6">
        <div className="mx-auto mb-4 h-1.5 w-14 rounded-full bg-surface-2" />
        <p className="text-[11px] text-muted">Ofis bilgisayarı</p>
        <p className="text-sm font-semibold text-fg">Motor çalışıyor</p>
        <div className="mt-3 space-y-2 text-[11px]">
          <div className="flex justify-between rounded-lg bg-bg px-2.5 py-2">
            <span className="text-muted">Açık pozisyon</span>
            <span className="font-medium text-fg">2</span>
          </div>
          <div className="flex justify-between rounded-lg bg-bg px-2.5 py-2">
            <span className="text-muted">Balina uyarısı</span>
            <span className="font-medium text-fg">ETHUSDT</span>
          </div>
        </div>
        <div className="mt-4 rounded-xl bg-danger-bg py-3 text-center text-xs font-semibold text-danger-fg">Acil durdurma</div>
        <p className="mt-2 text-center text-[10px] text-muted">Pozisyon kapatma: Face ID</p>
      </div>
    </div>
  );
}

export function DesktopPreview() {
  return (
    <div aria-hidden="true" className="overflow-hidden rounded-xl border border-border bg-bg">
      <div className="flex gap-1.5 border-b border-border px-3 py-2">
        <span className="h-2 w-2 rounded-full bg-surface-2" />
        <span className="h-2 w-2 rounded-full bg-surface-2" />
        <span className="h-2 w-2 rounded-full bg-surface-2" />
      </div>
      <div className="grid grid-cols-[4.5rem_1fr] gap-2 p-2.5 text-[10px]">
        <div className="space-y-1.5">
          {["Genel bakış", "Piyasa", "Fırsatlar", "Balina", "Risk"].map((item, index) => (
            <div key={item} className={`rounded-md px-1.5 py-1 ${index === 0 ? "bg-surface-2 text-fg" : "text-muted"}`}>
              {item}
            </div>
          ))}
        </div>
        <div className="space-y-2">
          <div className="h-16 rounded-md bg-surface-2" />
          <div className="grid grid-cols-3 gap-2">
            <div className="h-8 rounded-md bg-surface-2" />
            <div className="h-8 rounded-md bg-surface-2" />
            <div className="h-8 rounded-md bg-surface-2" />
          </div>
        </div>
      </div>
    </div>
  );
}
