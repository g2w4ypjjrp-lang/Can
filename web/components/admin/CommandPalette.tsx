"use client";

import { CornerDownLeft, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

import type { NavEntry } from "@/lib/admin";

/** Hızlı geçiş (Ctrl/⌘ + K): yetkili olunan sayfalar arasında yazarak gezinme. */
export function CommandPalette({ items }: { items: NavEntry[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const listId = useId();

  const results = useMemo(() => {
    const q = query.trim().toLocaleLowerCase("tr-TR");
    return items.filter((item) => !q || `${item.label} ${item.group}`.toLocaleLowerCase("tr-TR").includes(q));
  }, [items, query]);

  useEffect(() => {
    function onKey(event: globalThis.KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      restoreRef.current = document.activeElement as HTMLElement | null;
      setQuery("");
      setIndex(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    } else {
      restoreRef.current?.focus?.();
    }
  }, [open]);

  function go(item: NavEntry | undefined) {
    if (!item) return;
    setOpen(false);
    router.push(item.href);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setIndex((i) => Math.min(results.length - 1, i + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setIndex((i) => Math.max(0, i - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(results[index]);
    } else if (event.key === "Tab") {
      event.preventDefault(); // odak iletişim kutusunda kalır
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="hidden min-w-64 items-center gap-2 rounded-xl border border-border bg-surface/80 px-3 py-2 text-sm text-muted shadow-sm transition-colors hover:border-border-strong hover:text-fg md:inline-flex"
      >
        <Search aria-hidden="true" className="h-4 w-4" />
        <span className="flex-1 text-left">Hızlı geçiş…</span>
        <kbd className="rounded-md border border-border bg-surface-2 px-1.5 py-0.5 font-sans text-[11px] text-fg">Ctrl K</kbd>
      </button>
      {open ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-[#05070e]/55 p-4 pt-[12vh] backdrop-blur-sm" onMouseDown={() => setOpen(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Hızlı geçiş"
            className="glass w-full max-w-xl overflow-hidden rounded-3xl shadow-lift"
            onMouseDown={(e) => e.stopPropagation()}
            onKeyDown={onKeyDown}
          >
            <div className="flex items-center gap-3 border-b border-glass-border px-4 py-3">
              <Search aria-hidden="true" className="h-5 w-5 text-muted" />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setIndex(0);
                }}
                role="combobox"
                aria-expanded="true"
                aria-controls={listId}
                aria-activedescendant={results[index] ? `${listId}-${index}` : undefined}
                aria-label="Gidilecek sayfa"
                placeholder="Sayfa adı yazın…"
                className="flex-1 bg-transparent text-base text-fg outline-none placeholder:text-muted"
              />
              <kbd className="rounded-md border border-border bg-surface-2 px-1.5 py-0.5 text-[11px] text-fg">Esc</kbd>
            </div>
            <ul id={listId} role="listbox" aria-label="Sayfalar" className="max-h-80 overflow-auto p-2">
              {results.length === 0 ? <li className="px-3 py-6 text-center text-sm text-muted">Sonuç yok</li> : null}
              {results.map((item, i) => (
                <li
                  key={item.href}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === index}
                  onMouseEnter={() => setIndex(i)}
                  onClick={() => go(item)}
                  className={`flex cursor-pointer items-center justify-between rounded-xl px-3 py-2.5 text-sm ${i === index ? "bg-surface-3 text-fg" : "text-fg"}`}
                >
                  <span>
                    {item.label}
                    <span className="ml-2 text-xs text-muted">{item.group}</span>
                  </span>
                  {i === index ? <CornerDownLeft aria-hidden="true" className="h-4 w-4 text-muted" /> : null}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </>
  );
}
