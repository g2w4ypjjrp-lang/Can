import { Bug } from "lucide-react";
import { useAction, usePoll } from "../api/hooks";
import { Badge, Card, ErrorBox } from "../components/ui";

interface CrashStatus {
  enabled: boolean;
  sent: number;
  dropped: number;
  last_sent_at: string | null;
  last_error: string | null;
  endpoint: string;
}

/** İsteğe bağlı hata raporları (Ayarlar ekranının bir bölümü). Varsayılan kapalı. */
export function CrashReportsSection() {
  const status = usePoll((c) => c.get<CrashStatus>("/v1/crash-reports"), 15_000);
  const toggle = useAction((c, enabled: boolean) => c.post<CrashStatus>("/v1/crash-reports/enabled", { enabled }));
  const s = status.data;

  return (
    <Card
      title="Hata raporları"
      testId="crash-reports"
      actions={
        s ? (
          <Badge tone={s.enabled ? "ok" : "neutral"} testId="crash-state">
            {s.enabled ? "Açık" : "Kapalı"}
          </Badge>
        ) : null
      }
    >
      <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
        <Bug aria-hidden="true" size={20} style={{ flexShrink: 0, marginTop: 2 }} />
        <div className="stack" style={{ gap: 8 }}>
          <p>
            Açarsanız uygulamada bir hata oluştuğunda kısa bir teknik rapor <b>{s?.endpoint ?? "api.canarslan.net.tr"}</b> adresine
            gönderilir; hataları daha hızlı düzeltmemize yardımcı olur. İstediğiniz zaman kapatabilirsiniz.
          </p>
          <ul className="muted small">
            <li>Gönderilen: uygulama sürümü, Windows sürümü, hata türü, kişisel bilgilerden ayıklanmış hata mesajı ve kod satırları.</li>
            <li>
              Gönderilmeyen: adınız, e-postanız, kullanıcı klasörünüz, IP adresiniz, lisans anahtarınız, Binance anahtarları,
              bakiye, emir ve pozisyon bilgileri.
            </li>
            <li>Aynı hata saatte bir kez, toplamda saatte en çok 10 rapor gönderilir.</li>
          </ul>
          <div className="row">
            <button
              type="button"
              className={s?.enabled ? "" : "primary"}
              disabled={!s || toggle.pending}
              onClick={async () => {
                if (s && (await toggle.execute(!s.enabled))) await status.refresh();
              }}
              data-testid="crash-toggle"
            >
              {s?.enabled ? "Hata raporlarını kapat" : "Hata raporlarını aç"}
            </button>
            {s?.enabled ? (
              <span className="muted small" data-testid="crash-sent">
                Bu oturumda gönderilen: {s.sent}
                {s.last_error ? ` · son deneme: ${s.last_error}` : ""}
              </span>
            ) : null}
          </div>
          <ErrorBox error={status.error ?? toggle.error} />
        </div>
      </div>
    </Card>
  );
}
