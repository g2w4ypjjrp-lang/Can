import { type Connection, wsUrl } from "../lib/connection";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Servis kapalı / etkin değil (motorda ilgili bileşen çalışmıyor). */
  get unavailable(): boolean {
    return this.status === 404 || this.status === 503;
  }
}

export type Query = Record<string, string | number | boolean | undefined | null>;

function describe(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI doğrulama hataları: [{loc, msg}]
    return detail
      .map((d) => {
        const item = d as { loc?: unknown[]; msg?: string };
        const field = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
        return field ? `${field}: ${item.msg ?? ""}` : (item.msg ?? "");
      })
      .join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  return fallback;
}

export function buildQuery(params?: Query): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Motorun "doğrulama kodu gerekli" yanıtı (HTTP 428): uygulama doğrulaması açıkken kritik işlemler. */
export interface VerificationRequest {
  code: "verification_required";
  reason: "required" | "invalid";
  action: string;
  label: string;
  message: string;
}

/** Kod sorar; vazgeçilirse null döner. */
export type Verifier = (request: VerificationRequest) => Promise<string | null>;

export const VERIFICATION_HEADER = "X-ATI-Verification";

function isVerification(error: unknown): error is ApiError & { detail: VerificationRequest } {
  return (
    error instanceof ApiError &&
    error.status === 428 &&
    typeof error.detail === "object" &&
    error.detail !== null &&
    (error.detail as { code?: unknown }).code === "verification_required"
  );
}

export class EngineClient {
  /** Kritik işlemde kod sormak için (uygulama doğrulaması); arayüz kurar. */
  verifier: Verifier | null = null;

  constructor(
    readonly connection: Connection,
    private readonly fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  async request<T>(method: "GET" | "POST", path: string, body?: unknown, params?: Query): Promise<T> {
    let code: string | undefined;
    // Kod istenirse sorulur ve aynı istek kodla yinelenir (hatalı kodda yeniden sorulur, en çok 3 kez).
    for (let attempt = 0; ; attempt += 1) {
      try {
        return await this.send<T>(method, path, body, params, code);
      } catch (error) {
        if (!isVerification(error) || !this.verifier || attempt >= 3) throw error;
        const entered = await this.verifier(error.detail);
        if (!entered) throw new ApiError(428, "İşlem doğrulanmadığı için yapılmadı", error.detail);
        code = entered;
      }
    }
  }

  private async send<T>(
    method: "GET" | "POST",
    path: string,
    body: unknown,
    params: Query | undefined,
    code: string | undefined,
  ): Promise<T> {
    const headers: Record<string, string> = { Authorization: `Bearer ${this.connection.token}` };
    if (code) headers[VERIFICATION_HEADER] = code;
    let payload: string | undefined;
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    let response: Response;
    try {
      response = await this.fetchImpl(this.connection.baseUrl + path + buildQuery(params), {
        method,
        headers,
        body: payload,
      });
    } catch (error) {
      throw new ApiError(0, "Motora ulaşılamadı", error);
    }
    const text = await response.text();
    let data: unknown = undefined;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    if (!response.ok) {
      const detail = (data as { detail?: unknown } | undefined)?.detail ?? data;
      throw new ApiError(response.status, describe(detail, `HTTP ${response.status}`), detail);
    }
    return data as T;
  }

  get<T>(path: string, params?: Query): Promise<T> {
    return this.request<T>("GET", path, undefined, params);
  }

  post<T>(path: string, body?: unknown, params?: Query): Promise<T> {
    return this.request<T>("POST", path, body, params);
  }

  /** Olay akışı: bağlanır, belirteçle kimlik doğrular, koparsa artan bekleme ile yeniden bağlanır. */
  events(onEvent: (event: EngineEvent) => void, onStatus?: (connected: boolean) => void): () => void {
    let socket: WebSocket | null = null;
    let closed = false;
    let backoff = 500;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (closed) return;
      socket = new WebSocket(wsUrl(this.connection.baseUrl, "/v1/events"));
      socket.onopen = () => socket?.send(JSON.stringify({ type: "auth", token: this.connection.token }));
      socket.onmessage = (message) => {
        let data: EngineEvent;
        try {
          data = JSON.parse(String(message.data)) as EngineEvent;
        } catch {
          return;
        }
        if (data.type === "auth_ok") {
          backoff = 500;
          onStatus?.(true);
          return;
        }
        onEvent(data);
      };
      socket.onclose = () => {
        onStatus?.(false);
        if (closed) return;
        timer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 10_000);
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }
}

export interface EngineEvent {
  type: string;
  ts_ms?: number;
  [key: string]: unknown;
}
