/**
 * Motor bağlantı bilgisi (yerel API adresi + oturum belirteci).
 *
 * - Masaüstü uygulamasında (Tauri) motoru kabuk başlatır; adres ve belirteç Rust tarafındaki
 *   `engine_connection` komutundan alınır. Belirteç her açılışta rastgele üretilir ve diske
 *   yazılmaz.
 * - Tarayıcıda (geliştirme / uçtan uca testler) adres ve belirteç URL'nin `#` kısmından
 *   (`#engine=http://127.0.0.1:47821&token=...`) veya `VITE_ENGINE_URL` / `VITE_ENGINE_TOKEN`
 *   ortam değişkenlerinden okunur. `#` kısmı sunucuya gönderilmez.
 */

export interface Connection {
  baseUrl: string;
  token: string;
  /** Motoru bu uygulama mı başlattı (Tauri kabuğu)? */
  managed: boolean;
}

const LOOPBACK = /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/;

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Yalnızca yerel (loopback) motor adresine izin verilir. */
export function normalizeBaseUrl(raw: string): string {
  const url = raw.trim().replace(/\/+$/, "");
  if (!LOOPBACK.test(url)) {
    throw new Error("Motor adresi yalnızca bu bilgisayar (127.0.0.1) olabilir");
  }
  return url;
}

export function parseHash(hash: string): Partial<Connection> {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const result: Partial<Connection> = {};
  const engine = params.get("engine");
  const token = params.get("token");
  if (engine) result.baseUrl = normalizeBaseUrl(engine);
  if (token) result.token = token;
  return result;
}

export async function resolveConnection(): Promise<Connection> {
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    const conn = await invoke<{ base_url: string; token: string }>("engine_connection");
    return { baseUrl: normalizeBaseUrl(conn.base_url), token: conn.token, managed: true };
  }
  const fromHash = parseHash(window.location.hash);
  const baseUrl = fromHash.baseUrl ?? import.meta.env.VITE_ENGINE_URL;
  const token = fromHash.token ?? import.meta.env.VITE_ENGINE_TOKEN;
  if (!baseUrl || !token) {
    throw new Error(
      "Motor bağlantı bilgisi yok. Uygulamayı masaüstü kurulumundan açın veya adresi " +
        "#engine=http://127.0.0.1:PORT&token=BELIRTEC biçiminde verin.",
    );
  }
  return { baseUrl: normalizeBaseUrl(baseUrl), token, managed: false };
}

export function wsUrl(baseUrl: string, path: string): string {
  return baseUrl.replace(/^http/, "ws") + path;
}
