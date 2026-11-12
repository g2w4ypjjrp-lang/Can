import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { applyPriceTick } from "../lib/livePrices";
import { ApiError, type EngineClient, type EngineEvent } from "./client";

const ClientContext = createContext<EngineClient | null>(null);

export function ClientProvider({ client, children }: { client: EngineClient; children: ReactNode }) {
  return <ClientContext.Provider value={client}>{children}</ClientContext.Provider>;
}

export function useClient(): EngineClient {
  const client = useContext(ClientContext);
  if (!client) throw new Error("Motor istemcisi yok");
  return client;
}

export interface Poll<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

/** Bir uç noktayı düzenli aralıkla okur; sekme görünmezken durur. */
export function usePoll<T>(
  load: (client: EngineClient) => Promise<T>,
  intervalMs: number,
  deps: unknown[] = [],
): Poll<T> {
  const client = useClient();
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  loadRef.current = load;
  const generation = useRef(0);

  const refresh = useCallback(async () => {
    const current = ++generation.current;
    try {
      const value = await loadRef.current(client);
      if (current !== generation.current) return;
      setData(value);
      setError(null);
    } catch (e) {
      if (current !== generation.current) return;
      setError(e instanceof ApiError ? e : new ApiError(0, String(e), e));
    } finally {
      if (current === generation.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, ...deps]);

  useEffect(() => {
    setLoading(true);
    void refresh();
    if (intervalMs <= 0) return;
    const id = setInterval(() => {
      if (document.visibilityState !== "hidden") void refresh();
    }, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);

  return { data, error, loading, refresh };
}

export type Toast = { id: number; tone: "info" | "warning" | "critical" | "ok"; title: string; body: string };

interface EventsState {
  connected: boolean;
  last: EngineEvent[];
  toasts: Toast[];
  dismiss: (id: number) => void;
  notify: (toast: Omit<Toast, "id">) => void;
}

const EventsContext = createContext<EventsState>({
  connected: false,
  last: [],
  toasts: [],
  dismiss: () => undefined,
  notify: () => undefined,
});

let toastId = 1;

function toToast(event: EngineEvent): Omit<Toast, "id"> | null {
  const e = event as Record<string, unknown>;
  switch (event.type) {
    case "Alert":
      return {
        tone: e.severity === "critical" ? "critical" : e.severity === "warning" ? "warning" : "info",
        title: String(e.title ?? "Uyarı"),
        body: String(e.message ?? ""),
      };
    case "WhaleAlert":
      return { tone: "info", title: `Balina: ${String(e.symbol ?? "")}`, body: String(e.message ?? "") };
    case "EngineStateChanged":
      return {
        tone: e.current === "running" ? "ok" : "warning",
        title: "Motor durumu",
        body: `${String(e.previous ?? "")} → ${String(e.current ?? "")}: ${String(e.reason ?? "")}`,
      };
    default:
      return null;
  }
}

export function EventsProvider({ client, children }: { client: EngineClient; children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [last, setLast] = useState<EngineEvent[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = useCallback((toast: Omit<Toast, "id">) => {
    const id = toastId++;
    setToasts((items) => [...items.slice(-4), { ...toast, id }]);
    setTimeout(() => setToasts((items) => items.filter((t) => t.id !== id)), 8000);
  }, []);
  const dismiss = useCallback((id: number) => setToasts((items) => items.filter((t) => t.id !== id)), []);

  useEffect(
    () =>
      client.events((event) => {
        // Anlık fiyatlar saniyede 10 kez gelebilir: olay listesine girmez, yalnızca fiyat deposuna.
        if (event.type === "PriceTick") {
          applyPriceTick(event.prices);
          return;
        }
        setLast((items) => [event, ...items].slice(0, 200));
        const toast = toToast(event);
        if (toast) notify(toast);
      }, setConnected),
    [client, notify],
  );

  return (
    <EventsContext.Provider value={{ connected, last, toasts, dismiss, notify }}>
      {children}
    </EventsContext.Provider>
  );
}

export function useEvents(): EventsState {
  return useContext(EventsContext);
}

/** POST işlemleri için: çalışıyor/hata durumu ve başarı bildirimi. */
export function useAction<A extends unknown[], R>(
  run: (client: EngineClient, ...args: A) => Promise<R>,
): { pending: boolean; error: string | null; execute: (...args: A) => Promise<R | undefined> } {
  const client = useClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Her çizimde en güncel kapanış kullanılır (form alanlarının son değerleri).
  const runRef = useRef(run);
  runRef.current = run;
  const execute = useCallback(
    async (...args: A) => {
      setPending(true);
      setError(null);
      try {
        return await runRef.current(client, ...args);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return undefined;
      } finally {
        setPending(false);
      }
    },
    [client],
  );
  return { pending, error, execute };
}
