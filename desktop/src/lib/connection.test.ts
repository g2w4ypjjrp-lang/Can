import { describe, expect, it } from "vitest";
import { normalizeBaseUrl, parseHash, wsUrl } from "./connection";

describe("bağlantı", () => {
  it("adres ve belirteci URL'nin # kısmından okur", () => {
    expect(parseHash("#engine=http://127.0.0.1:47821/&token=abc")).toEqual({
      baseUrl: "http://127.0.0.1:47821",
      token: "abc",
    });
    expect(parseHash("")).toEqual({});
  });
  it("yalnızca bu bilgisayardaki motora bağlanır", () => {
    expect(normalizeBaseUrl("http://localhost:1234")).toBe("http://localhost:1234");
    expect(() => normalizeBaseUrl("http://192.168.1.5:47821")).toThrow(/127\.0\.0\.1/);
    expect(() => normalizeBaseUrl("https://evil.example.com")).toThrow();
    expect(() => parseHash("#engine=http://10.0.0.1:1&token=x")).toThrow();
  });
  it("WebSocket adresine çevirir", () => {
    expect(wsUrl("http://127.0.0.1:1", "/v1/events")).toBe("ws://127.0.0.1:1/v1/events");
  });
});
