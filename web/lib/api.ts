// Hesap API'si istemcisi (tarayıcı). Oturum, API'nin koyduğu HttpOnly çerezdedir; JavaScript
// belirteci hiç görmez. Her istek çerezle (credentials: "include") ve JSON gövdeyle gider.

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const FIELD_MESSAGES: Record<string, string> = {
  email: "Geçerli bir e-posta adresi girin",
  password: "Parolanızı girin",
  name: "Adınızı girin",
  message: "Mesajınız en az 10 karakter olmalı",
  topic: "Bir konu seçin",
  token: "Bağlantı geçersiz veya eksik",
};

/** FastAPI hata gövdesini kullanıcıya gösterilecek Türkçe metne çevirir. */
export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const loc = (detail[0] as { loc?: unknown[] }).loc;
    const field = Array.isArray(loc) ? String(loc[loc.length - 1]) : "";
    return FIELD_MESSAGES[field] ?? "Girdiğiniz bilgileri kontrol edin";
  }
  if (status === 429) return "Çok fazla deneme. Biraz bekleyip tekrar deneyin.";
  if (status >= 500) return "Sunucuda geçici bir sorun var. Biraz sonra tekrar deneyin.";
  return "İşlem tamamlanamadı";
}

export const NETWORK_ERROR = "Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.";

export async function apiRequest<T>(
  base: string,
  path: string,
  init: { method?: "GET" | "POST"; body?: unknown; fetcher?: typeof fetch } = {},
): Promise<T> {
  const fetcher = init.fetcher ?? fetch;
  let response: Response;
  try {
    response = await fetcher(`${base}${path}`, {
      method: init.method ?? "GET",
      credentials: "include",
      cache: "no-store",
      headers: init.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    throw new ApiError(0, NETWORK_ERROR);
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, body));
  return body as T;
}

export interface Message {
  status: string;
  message?: string;
}

export interface License {
  id: string;
  key_hint: string;
  plan_code: string;
  plan_name: string;
  status: string;
  device_limit: number;
  sold_at: string | null;
  activated_at: string | null;
  expires_at: string | null;
  active_devices: number;
}

export interface Me {
  id: string;
  email: string;
  email_verified: boolean;
  full_name: string | null;
  locale: string;
  created_at: string;
  licenses: License[];
}
