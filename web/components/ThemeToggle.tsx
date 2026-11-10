"use client";

import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { THEME_KEY, type ThemeChoice } from "@/lib/theme";


const OPTIONS: { value: ThemeChoice; label: string; icon: LucideIcon }[] = [
  { value: "system", label: "Sistem teması", icon: Monitor },
  { value: "light", label: "Açık tema", icon: Sun },
  { value: "dark", label: "Koyu tema", icon: Moon },
];

export function applyTheme(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  try {
    if (choice === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, choice);
  } catch {
    // Gizli pencere vb.: seçim yalnızca bu sayfada geçerli olur.
  }
  // Sayfadaki diğer seçiciler (üst menü, alt bilgi) aynı durumu göstersin.
  window.dispatchEvent(new CustomEvent<ThemeChoice>("ati-tema", { detail: choice }));
}

/** Tema seçici (Sistem / Açık / Koyu). Seçim tarayıcıda saklanır. */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const [choice, setChoice] = useState<ThemeChoice>("system");

  useEffect(() => {
    const current = document.documentElement.getAttribute("data-theme");
    setChoice(current === "light" || current === "dark" ? current : "system");
    const onChange = (event: Event) => setChoice((event as CustomEvent<ThemeChoice>).detail);
    window.addEventListener("ati-tema", onChange);
    return () => window.removeEventListener("ati-tema", onChange);
  }, []);

  return (
    <div role="group" aria-label="Tema" className={`inline-flex items-center gap-0.5 rounded-full border border-border bg-surface/70 p-0.5 ${className}`}>
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const active = choice === value;
        return (
          <button
            key={value}
            type="button"
            aria-label={label}
            aria-pressed={active}
            title={label}
            onClick={() => {
              setChoice(value);
              applyTheme(value);
            }}
            className={`inline-flex h-7 w-7 items-center justify-center rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-accent-text ${
              active ? "bg-surface-3 text-fg shadow-sm" : "text-muted hover:text-fg"
            }`}
          >
            <Icon aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
        );
      })}
    </div>
  );
}
