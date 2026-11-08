import { describe, expect, it } from "vitest";
import { ApiError, buildQuery, EngineClient } from "./client";

function fakeFetch(status: number, body: unknown, calls: { url: string; init?: RequestInit }[] = []) {
  return (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return new Response(body === undefined ? "" : JSON.stringify(body), { status });
  }) as typeof fetch;
}

const conn = { baseUrl: "http://127.0.0.1:47821", token: "gizli-belirtec", managed: false };

describe("motor istemcisi", () => {
  it("belirteci gönderir ve sorgu parametrelerini kodlar", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const client = new EngineClient(conn, fakeFetch(200, { ok: 1 }, calls));
    expect(await client.get("/v1/opportunities", { min_score: 60, market: undefined, q: "a b" })).toEqual({ ok: 1 });
    expect(calls[0]!.url).toBe("http://127.0.0.1:47821/v1/opportunities?min_score=60&q=a+b");
    expect((calls[0]!.init!.headers as Record<string, string>).Authorization).toBe("Bearer gizli-belirtec");
  });
  it("POST gövdesini JSON gönderir", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const client = new EngineClient(conn, fakeFetch(200, { accepted: true }, calls));
    await client.post("/v1/trading-mode", { mode: "testnet" });
    expect(calls[0]!.init!.method).toBe("POST");
    expect(calls[0]!.init!.body).toBe('{"mode":"testnet"}');
  });
  it("hata mesajını okunur hâle getirir", async () => {
    const client = new EngineClient(conn, fakeFetch(409, { detail: "Risk kapısı reddetti: Zarar durdur zorunludur" }));
    await expect(client.post("/v1/execution/trades", {})).rejects.toMatchObject({
      status: 409,
      message: "Risk kapısı reddetti: Zarar durdur zorunludur",
    });
    const validation = new EngineClient(
      conn,
      fakeFetch(422, { detail: [{ loc: ["body", "quantity"], msg: "Input should be greater than 0" }] }),
    );
    await expect(validation.post("/v1/execution/trades", {})).rejects.toThrow("quantity: Input should be greater than 0");
  });
  it("servis kapalıysa 'unavailable' olarak işaretler; ağ hatasını ayırır", async () => {
    const off = new EngineClient(conn, fakeFetch(404, { detail: "Balina radarı etkin değil" }));
    const error = await off.get("/v1/whales/alerts").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).unavailable).toBe(true);
    const down = new EngineClient(conn, (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch);
    await expect(down.get("/v1/status")).rejects.toMatchObject({ status: 0, message: "Motora ulaşılamadı" });
  });
  it("boş parametreleri atlar", () => {
    expect(buildQuery({ a: "", b: null, c: 0, d: false })).toBe("?c=0&d=false");
    expect(buildQuery()).toBe("");
  });
});
