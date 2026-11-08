import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { EngineClient } from "./api/client";
import { ClientProvider, EventsProvider } from "./api/hooks";
import { App } from "./App";
import { resolveConnection } from "./lib/connection";
import "./styles.css";

function Root() {
  const [client, setClient] = useState<EngineClient | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const attempt = async (tries: number): Promise<void> => {
      try {
        const connection = await resolveConnection();
        if (!cancelled) setClient(new EngineClient(connection));
      } catch (e) {
        // Masaüstünde motor başlarken birkaç saniye sürebilir.
        if (tries > 0 && !cancelled) {
          setTimeout(() => void attempt(tries - 1), 1000);
        } else if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    };
    void attempt(30);
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="boot">
        <h1>Motora bağlanılamadı</h1>
        <p>{error}</p>
      </div>
    );
  }
  if (!client) {
    return (
      <div className="boot" data-testid="booting">
        <h1>AI Trading Intelligence</h1>
        <p>İşlem motoru başlatılıyor…</p>
      </div>
    );
  }
  return (
    <ClientProvider client={client}>
      <EventsProvider client={client}>
        <App />
      </EventsProvider>
    </ClientProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
