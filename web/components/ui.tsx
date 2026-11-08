import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

const base =
  "inline-flex items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-semibold transition-colors " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60";
const variants = {
  primary: "bg-accent text-accent-fg hover:bg-accent-strong",
  secondary: "border border-border bg-surface text-fg hover:bg-surface-2",
  ghost: "text-fg hover:bg-surface-2",
};

type Variant = keyof typeof variants;

export function Button({ variant = "primary", className = "", ...props }: ComponentProps<"button"> & { variant?: Variant }) {
  return <button className={`${base} ${variants[variant]} ${className}`} {...props} />;
}

export function LinkButton({
  variant = "primary",
  className = "",
  ...props
}: ComponentProps<typeof Link> & { variant?: Variant }) {
  return <Link className={`${base} ${variants[variant]} ${className}`} {...props} />;
}

export function Container({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mx-auto w-full max-w-6xl px-4 sm:px-6 ${className}`}>{children}</div>;
}

export function PageHeader({ title, lead }: { title: string; lead?: ReactNode }) {
  return (
    <header className="border-b border-border bg-surface">
      <Container className="py-10 sm:py-14">
        <h1 className="text-3xl font-bold tracking-tight text-fg sm:text-4xl">{title}</h1>
        {lead ? <p className="mt-3 max-w-3xl text-lg text-muted">{lead}</p> : null}
      </Container>
    </header>
  );
}

export function Card({ children, className = "", as: Tag = "div" }: { children: ReactNode; className?: string; as?: "div" | "article" | "section" | "li" }) {
  return <Tag className={`rounded-xl border border-border bg-surface p-6 ${className}`}>{children}</Tag>;
}

type Tone = "info" | "warning" | "success" | "danger";
const tones: Record<Tone, string> = {
  info: "border-info-border bg-info-bg text-info-fg",
  warning: "border-warn-border bg-warn-bg text-warn-fg",
  success: "border-success-border bg-success-bg text-success-fg",
  danger: "border-danger-border bg-danger-bg text-danger-fg",
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
  return (
    <div id={id} role={role} className={`rounded-lg border px-4 py-3 text-sm ${tones[tone]}`}>
      {title ? <p className="font-semibold">{title}</p> : null}
      <div className={title ? "mt-1" : ""}>{children}</div>
    </div>
  );
}

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
      <input
        id={id}
        aria-describedby={describedBy}
        aria-invalid={error ? true : undefined}
        className="mt-1.5 block w-full rounded-lg border border-border-strong bg-bg px-3 py-2.5 text-fg placeholder:text-muted focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
        {...input}
      />
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

export function FormCard({ title, children, footer }: { title: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <Container className="py-12 sm:py-16">
      <div className="mx-auto max-w-md">
        <h1 className="text-2xl font-bold tracking-tight text-fg">{title}</h1>
        <div className="mt-6 rounded-xl border border-border bg-surface p-6 sm:p-8">{children}</div>
        {footer ? <div className="mt-6 text-center text-sm text-muted">{footer}</div> : null}
      </div>
    </Container>
  );
}

export function TextLink(props: ComponentProps<typeof Link>) {
  return <Link {...props} className={`font-medium text-link underline underline-offset-2 hover:no-underline ${props.className ?? ""}`} />;
}
