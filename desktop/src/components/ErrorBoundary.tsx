import { Component, type ErrorInfo, type ReactNode, useEffect } from "react";
import { useClient } from "../api/hooks";
import type { EngineClient } from "../api/client";

/** Arayüz hatasını motora iletir. Motor, kullanıcı hata raporlarını açtıysa ayıklayıp gönderir;
 * kapalıysa hiçbir şey göndermez. Bu çağrı hiçbir zaman hata fırlatmaz. */
export function reportUiError(client: EngineClient, error: unknown, extraStack = "") {
  const err = error instanceof Error ? error : new Error(String(error));
  void client
    .post("/v1/crash-reports/ui", {
      message: err.message.slice(0, 2000),
      stack: `${err.stack ?? ""}\n${extraStack}`.slice(0, 20_000),
      error_type: (err.name || "Error").slice(0, 120),
    })
    .catch(() => undefined);
}

interface Props {
  client: EngineClient;
  children: ReactNode;
}

class Boundary extends Component<Props, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    reportUiError(this.props.client, error, info.componentStack ?? "");
  }

  render() {
    if (this.state.error) {
      return (
        <div className="card" role="alert" data-testid="ui-error">
          <h2>Bu ekranda bir sorun oluştu</h2>
          <p className="muted">
            İşlem motoru çalışmaya devam ediyor; açık pozisyonların stopları borsada yerinde. Başka bir sayfaya geçebilir ya da
            ekranı yeniden deneyebilirsiniz.
          </p>
          <button type="button" onClick={() => this.setState({ error: null })}>
            Yeniden dene
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

/** Sayfa içeriğini sarar: bir ekrandaki hata tüm uygulamayı kapatmaz. */
export function ErrorBoundary({ children }: { children: ReactNode }) {
  const client = useClient();
  return <Boundary client={client}>{children}</Boundary>;
}

/** Yakalanmamış hata ve reddedilen sözleri de iletir. */
export function useGlobalErrorReports() {
  const client = useClient();
  useEffect(() => {
    const onError = (event: ErrorEvent) => reportUiError(client, event.error ?? event.message);
    const onRejection = (event: PromiseRejectionEvent) => reportUiError(client, event.reason);
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, [client]);
}
