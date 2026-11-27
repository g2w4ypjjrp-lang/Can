import { INTERNAL_API_URL } from "./env";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const r = await fetch(INTERNAL_API_URL + path, {
    ...init, cache: "no-store",
    headers: { ...init?.headers, authorization: `Bearer ${token}`, "content-type": "application/json" },
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new ApiError(r.status, typeof body.detail === "string" ? body.detail : `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

export type Org = { id: string; name: string; base_currency: string; role: string };
export type Me = { id: string; email: string | null; organizations: Org[] };
