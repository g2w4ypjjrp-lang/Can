import { Download, X } from "lucide-react";
import { useEffect, useState } from "react";
import { isTauri } from "../lib/connection";

interface UpdateInfo {
  version: string;
  notes: string | null;
}

/**
 * Otomatik güncelleme: açılıştan 15 sn sonra ve 6 saatte bir sunucuya sorulur. Kurulum yalnızca
 * kullanıcı onaylayınca yapılır; dosyanın imzası gömülü açık anahtarla doğrulanmadan kurulmaz.
 */
export function UpdateBanner() {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(null);

  useEffect(() => {
    if (!isTauri()) return;
    let cancelled = false;
    const check = async () => {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const result = await invoke<UpdateInfo | null>("check_update");
        if (!cancelled) setInfo(result);
      } catch {
        // Sunucuya ulaşılamazsa sessizce sonra yeniden denenir.
      }
    };
    const first = setTimeout(() => void check(), 15_000);
    const every = setInterval(() => void check(), 6 * 3600 * 1000);
    return () => {
      cancelled = true;
      clearTimeout(first);
      clearInterval(every);
    };
  }, []);

  if (!info || dismissed === info.version) return null;
  return (
    <div className="update-banner" role="status" data-testid="update-banner">
      <Download aria-hidden="true" size={18} />
      <div className="update-text">
        <b>Yeni sürüm hazır: {info.version}</b>
        <span className="muted small">
          {info.notes ? `${info.notes.slice(0, 160)} · ` : ""}Güncelleme sırasında motor birkaç saniye durur; borsadaki stop
          emirleriniz yerinde kalır.
        </span>
        {error && <span className="small down">{error}</span>}
      </div>
      <button
        type="button"
        className="primary"
        disabled={installing}
        onClick={async () => {
          setInstalling(true);
          setError(null);
          try {
            const { invoke } = await import("@tauri-apps/api/core");
            await invoke("install_update");
          } catch (e) {
            setError(String(e));
            setInstalling(false);
          }
        }}
      >
        {installing ? "Güncelleniyor…" : "Şimdi güncelle"}
      </button>
      <button type="button" className="ghost" aria-label="Sonra hatırlat" onClick={() => setDismissed(info.version)} disabled={installing}>
        <X aria-hidden="true" size={16} />
      </button>
    </div>
  );
}
