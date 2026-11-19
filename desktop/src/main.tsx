import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { EngineClient } from "./api/client";
import { ClientProvider, EventsProvider } from "./api/hooks";
import { VerificationHost } from "./components/Verification";
import { App } from "./App";
import { resolveConnection } from "./lib/connection";
import "./styles.css";

// Motor ilk açılışta (ör. Windows Defender yeni dosyayı tararken) 1-2 dakika sürebilir. Tauri
// tarafı 120 sn bekler; arayüz de en az o kadar bekler ve "hazır değil" durumunda vazgeçmez.
const WAIT_TRIES = 180;

function Root() {
  const [client, setClient] = useState<EngineClient | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waited, setWaited] = useState(0);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setWaited(0);
    const attempt = async (tries: number): Promise<void> => {
      try {
        const connection = await resolveConnection();
        if (!cancelled) setClient(new EngineClient(connection));
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        const starting = /hazır değil: (starting|restarting)/.test(message);
        if (!cancelled && (tries > 0 || starting) && tries > -60) {
          setWaited((w) => w + 1);
          setTimeout(() => void attempt(tries - 1), 1000);
        } else if (!cancelled) {
          setError(message);
        }
      }
    };
    void attempt(WAIT_TRIES);
    return () => {
      cancelled = true;
    };
  }, [round]);

  if (error) {
    return (
      <div className="boot">
        <h1>Motora bağlanılamadı</h1>
        <p>{error}</p>
        <button type="button" className="primary" onClick={() => setRound((r) => r + 1)}>
          Tekrar dene
        </button>
      </div>
    );
  }
  if (!client) {
    return (
      <div className="boot" data-testid="booting">
        <h1>AI Trading Intelligence</h1>
        <p>İşlem motoru başlatılıyor…{waited > 15 ? ` (${waited} sn) İlk açılışta Windows güvenlik taraması nedeniyle 1-2 dakika sürebilir.` : ""}</p>
      </div>
    );
  }
  return (
    <ClientProvider client={client}>
      <EventsProvider client={client}>
        <App />
        <VerificationHost />
      </EventsProvider>
    </ClientProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
