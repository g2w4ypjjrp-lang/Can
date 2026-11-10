// Hesap API'si istemcisi (tarayıcı). Oturum, API'nin koyduğu HttpOnly çerezdedir; JavaScript
// belirteci hiç görmez. Her istek çerezle (credentials: "include") ve JSON gövdeyle gider.

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Lisans ve ödeme uç noktalarının makine okunur hata kodu: {"detail": {"code": "..."}}. */
export function errorCode(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail;
  const code = (detail as { code?: unknown } | null | undefined)?.code;
  return typeof code === "string" ? code : null;
}

const FIELD_MESSAGES: Record<string, string> = {
  email: "Geçerli bir e-posta adresi girin",
  password: "Parolanızı girin",
  name: "Adınızı girin",
  message: "Mesajınız en az 10 karakter olmalı",
  topic: "Bir konu seçin",
  token: "Bağlantı geçersiz veya eksik",
  full_name: "Ad soyad en az 3 karakter olmalı",
  phone: "Geçerli bir telefon numarası girin (ör. +90 532 000 00 00)",
  address: "Adres en az 10 karakter olmalı",
  city: "Şehir girin",
  country: "Ülke girin",
  tax_id: "T.C. kimlik no 11, vergi no 10 haneli olmalı",
};

/** FastAPI hata gövdesini kullanıcıya gösterilecek Türkçe metne çevirir. */
export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  // Lisans uç noktaları: {"detail": {"code": "...", "message": "..."}}
  const message = (detail as { message?: unknown } | null | undefined)?.message;
  if (typeof message === "string" && message) return message;
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
  init: { method?: "GET" | "POST" | "PUT" | "PATCH"; body?: unknown; fetcher?: typeof fetch } = {},
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
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, body), errorCode(body));
  return body as T;
}

export interface Message {
  status: string;
  message?: string;
}

export interface LicenseDevice {
  id: string;
  name: string;
  platform: string;
  activated_at: string;
  last_seen_at: string;
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
  devices: LicenseDevice[];
  device_resets_left: number;
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

export interface PaymentStatus {
  open: boolean;
  test_mode: boolean;
  provider: string | null;
  legal_version: string;
}

export interface Order {
  order_no: number;
  status: string;
  total_minor: number;
  discount_minor?: number;
  coupon_code?: string | null;
  currency: string;
  created_at: string;
  paid_at: string | null;
  fulfilled_at: string | null;
  under_review: boolean;
  checkout_url: string | null;
  plan_name: string | null;
  licenses: string[];
  invoice_no: string | null;
}

export interface CheckoutResult {
  order_no: number;
  redirect_url: string;
}
