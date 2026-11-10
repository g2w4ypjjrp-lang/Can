import { CheckCircle2, CircleAlert, Info, TriangleAlert, type LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import { LogoMark } from "@/components/Logo";

// --- Düğmeler ----------------------------------------------------------------------------------

const base =
  "inline-flex items-center justify-center gap-2 rounded-full font-semibold transition-all duration-200 " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-text disabled:cursor-not-allowed disabled:opacity-60";
const sizes = {
  sm: "px-3.5 py-1.5 text-[13px]",
  md: "px-5 py-2.5 text-sm",
  lg: "px-6 py-3.5 text-[15px]",
};
const variants = {
  primary:
    "shine bg-brand text-white shadow-glow hover:-translate-y-px hover:brightness-110 active:translate-y-0 ring-1 ring-inset ring-white/15",
  secondary:
    "border border-border bg-surface/80 text-fg shadow-sm backdrop-blur hover:border-border-strong hover:bg-surface-2",
  ghost: "text-fg hover:bg-surface-2",
  danger: "bg-[#b42318] text-white hover:bg-[#9a1d14] shadow-sm",
  // Degrade (marka) zemin üzerinde: beyaz düğme, koyu lacivert yazı (iki temada aynı).
  light: "bg-white text-[#14215a] shadow-sm hover:bg-[#eef1ff]",
  outlineLight: "text-white ring-1 ring-inset ring-white/50 hover:bg-white/10",
};

type Variant = keyof typeof variants;
type Size = keyof typeof sizes;

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ComponentProps<"button"> & { variant?: Variant; size?: Size }) {
  return <button className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} {...props} />;
}

export function LinkButton({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ComponentProps<typeof Link> & { variant?: Variant; size?: Size }) {
  return <Link className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} {...props} />;
}

// --- Yerleşim ----------------------------------------------------------------------------------

export function Container({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8 ${className}`}>{children}</div>;
}

/** Arka plan süsleri (aurora ışığı, ızgara, gren). Yalnızca görsel; ekran okuyucudan gizli. */
export function Backdrop({ grid = true, aurora = true, className = "" }: { grid?: boolean; aurora?: boolean; className?: string }) {
  return (
    <div aria-hidden="true" className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}>
      {aurora ? (
        <div className="aurora">
          <span />
        </div>
      ) : (
        <div className="glow absolute inset-0" />
      )}
      {grid ? <div className="bg-grid absolute inset-0" /> : null}
      <div className="noise absolute inset-0" />
    </div>
  );
}

export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <p className={`inline-flex items-center gap-2 text-[13px] font-semibold uppercase tracking-[0.14em] text-accent-text ${className}`}>
      <span aria-hidden="true" className="h-px w-6 bg-gradient-to-r from-transparent to-current" />
      {children}
    </p>
  );
}

export function PageHeader({
  title,
  lead,
  eyebrow,
  children,
}: {
  title: string;
  lead?: ReactNode;
  eyebrow?: string;
  children?: ReactNode;
}) {
  return (
    <header className="relative overflow-hidden border-b border-border">
      <Backdrop />
      <Container className="relative py-16 sm:py-24">
        {eyebrow ? <Eyebrow>{eyebrow}</Eyebrow> : null}
        <h1 className="mt-3 max-w-4xl text-4xl font-semibold tracking-tight text-fg sm:text-6xl sm:leading-[1.04]">{title}</h1>
        {lead ? <p className="mt-5 max-w-3xl text-lg leading-relaxed text-muted sm:text-xl">{lead}</p> : null}
        {children ? <div className="mt-8">{children}</div> : null}
      </Container>
    </header>
  );
}

export function SectionTitle({
  id,
  eyebrow,
  title,
  lead,
  center = false,
}: {
  id: string;
  eyebrow?: string;
  title: string;
  lead?: ReactNode;
  center?: boolean;
}) {
  return (
    <div className={center ? "mx-auto max-w-3xl text-center" : "max-w-3xl"}>
      {eyebrow ? <Eyebrow className={center ? "justify-center" : ""}>{eyebrow}</Eyebrow> : null}
      <h2 id={id} className="mt-3 text-3xl font-semibold tracking-tight text-fg sm:text-5xl sm:leading-[1.08]">
        {title}
      </h2>
      {lead ? <p className="mt-5 text-lg leading-relaxed text-muted">{lead}</p> : null}
    </div>
  );
}

// --- Etiket ve kart ----------------------------------------------------------------------------

const badgeTones = {
  neutral: "border-border bg-surface/80 text-fg",
  accent: "border-info-border bg-info-bg text-info-fg",
  success: "border-success-border bg-success-bg text-success-fg",
  warn: "border-warn-border bg-warn-bg text-warn-fg",
  danger: "border-danger-border bg-danger-bg text-danger-fg",
};

export function Badge({
  children,
  className = "",
  tone = "neutral",
}: {
  children: ReactNode;
  className?: string;
  tone?: keyof typeof badgeTones;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium backdrop-blur ${badgeTones[tone]} ${className}`}>
      {children}
    </span>
  );
}

export function Card({
  children,
  className = "",
  as: Tag = "div",
  interactive = false,
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "article" | "section" | "li";
  interactive?: boolean;
}) {
  return (
    <Tag className={`rounded-3xl border border-border bg-surface p-6 shadow-sm ${interactive ? "card-lift" : ""} ${className}`}>
      {children}
    </Tag>
  );
}

// --- Bildirim ----------------------------------------------------------------------------------

type Tone = "info" | "warning" | "success" | "danger";
const tones: Record<Tone, { box: string; icon: LucideIcon }> = {
  info: { box: "border-info-border bg-info-bg text-info-fg", icon: Info },
  warning: { box: "border-warn-border bg-warn-bg text-warn-fg", icon: TriangleAlert },
  success: { box: "border-success-border bg-success-bg text-success-fg", icon: CheckCircle2 },
  danger: { box: "border-danger-border bg-danger-bg text-danger-fg", icon: CircleAlert },
};

export function Notice({
  tone = "info",
  title,
  children,
  role,
  id,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
  role?: "alert" | "status" | "note";
  id?: string;
}) {
  const { box, icon: Icon } = tones[tone];
  return (
    <div id={id} role={role} className={`flex gap-3 rounded-2xl border px-4 py-3.5 text-sm ${box}`}>
      <Icon aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2.2} />
      <div className="min-w-0 flex-1">
        {title ? <p className="font-semibold">{title}</p> : null}
        <div className={title ? "mt-1 leading-relaxed" : "leading-relaxed"}>{children}</div>
      </div>
    </div>
  );
}

// --- Form --------------------------------------------------------------------------------------

export const inputBase =
  "block w-full rounded-xl border border-border-strong/70 bg-surface px-3.5 py-2.5 text-fg shadow-sm transition-colors placeholder:text-muted " +
  "hover:border-border-strong focus-visible:border-accent-text focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring aria-[invalid=true]:border-danger-fg";

export function Field({
  id,
  label,
  hint,
  error,
  ...input
}: ComponentProps<"input"> & { id: string; label: string; hint?: string; error?: string }) {
  const describedBy = [hint ? `${id}-ipucu` : null, error ? `${id}-hata` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-fg">
        {label}
        {input.required ? null : <span className="font-normal text-muted"> (isteğe bağlı)</span>}
      </label>
      <input id={id} aria-describedby={describedBy} aria-invalid={error ? true : undefined} className={`mt-1.5 ${inputBase}`} {...input} />
      {hint ? (
        <p id={`${id}-ipucu`} className="mt-1.5 text-sm text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-hata`} className="mt-1.5 text-sm text-danger-fg">
          {error}
        </p>
      ) : null}
    </div>
  );
}

const AUTH_POINTS = [
  "İşlem motoru kendi bilgisayarınızda çalışır",
  "Borsa API anahtarlarınız bize gönderilmez",
  "Önce sanal işlem ve Demo Trading ile deneyin",
];

/** Hesap sayfaları (giriş, kayıt, parola): solda marka paneli, sağda form. */
export function FormCard({ title, children, footer }: { title: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="relative overflow-hidden">
      <Backdrop />
      <Container className="relative grid items-center gap-12 py-12 sm:py-20 lg:grid-cols-[1fr_minmax(0,30rem)]">
        <div className="hidden lg:block">
          <div className="relative overflow-hidden rounded-[2rem] border border-glass-border bg-brand p-10 text-white shadow-lift">
            <div aria-hidden="true" className="bg-dots absolute inset-0 opacity-60" />
            <div className="relative">
              <LogoMark className="h-11 w-11 ring-1 ring-white/30" />
              <p className="mt-8 text-3xl font-semibold leading-tight tracking-tight">
                Piyasayı kendi kurallarınızla analiz edin.
              </p>
              <ul className="mt-8 space-y-3 text-[15px] text-white">
                {AUTH_POINTS.map((point) => (
                  <li key={point} className="flex items-start gap-3">
                    <CheckCircle2 aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0" />
                    {point}
                  </li>
                ))}
              </ul>
              <p className="mt-10 text-sm text-white">
                Kripto varlık işlemleri yüksek risk taşır; yazılım yatırım tavsiyesi vermez ve kazanç garantisi sunmaz.
              </p>
            </div>
          </div>
        </div>
        <div className="mx-auto w-full max-w-md lg:max-w-none">
          <h1 className="text-3xl font-semibold tracking-tight text-fg sm:text-4xl">{title}</h1>
          <div className="glass mt-6 rounded-3xl p-6 shadow-lift sm:p-8">{children}</div>
          {footer ? <div className="mt-6 text-center text-sm text-muted">{footer}</div> : null}
        </div>
      </Container>
    </div>
  );
}

export function TextLink(props: ComponentProps<typeof Link>) {
  return (
    <Link
      {...props}
      className={`font-medium text-link underline decoration-from-font underline-offset-4 transition-colors hover:decoration-2 ${props.className ?? ""}`}
    />
  );
}

// --- İkon kutusu ve istatistik ------------------------------------------------------------------

export function IconTile({ icon: Icon, tone = "accent", className = "" }: { icon: LucideIcon; tone?: "accent" | "violet" | "cyan" | "success" | "danger"; className?: string }) {
  const map = {
    accent: "from-brand-1/18 to-brand-1/4 text-accent-text ring-brand-1/25",
    violet: "from-brand-3/18 to-brand-3/4 text-accent-2 ring-brand-3/25",
    cyan: "from-accent-3/18 to-accent-3/4 text-accent-3 ring-accent-3/25",
    success: "from-[#0f9d58]/16 to-[#0f9d58]/4 text-success-fg ring-[#0f9d58]/25",
    danger: "from-[#d93636]/16 to-[#d93636]/4 text-danger-fg ring-[#d93636]/25",
  };
  return (
    <span className={`inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-b ring-1 ring-inset ${map[tone]} ${className}`}>
      <Icon aria-hidden="true" className="h-5 w-5" strokeWidth={1.9} />
    </span>
  );
}
