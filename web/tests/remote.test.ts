// Telefon tarayıcısı protokolü: Python motoru ve iPhone uygulamasıyla aynı baytlar (ortak test
// vektörleri), eşleştirme kodu denetimi ve uçtan uca zarf.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  b64,
  b64url,
  channelInfo,
  deviceHello,
  generateDeviceKeys,
  hmacProof,
  importEcPrivate,
  keyId,
  openFromEngine,
  openSealed,
  pairRequest,
  parsePairing,
  RemoteError,
  seal,
  signedCommand,
  unb64,
  unb64url,
  verifyEngine,
} from "@/lib/remote";

const vectors = JSON.parse(
  readFileSync(fileURLToPath(new URL("../../shared/protocol/test-vectors/remote-v1.json", import.meta.url)), "utf8"),
);
const enc = new TextEncoder();

describe("ortak test vektörleri", () => {
  it("motorun Ed25519 imzalı özetini doğrular, değiştirilmişini reddeder", async () => {
    const key = unb64(vectors.engine.key);
    expect(await keyId(key)).toBe(vectors.engine.engine_id);
    const ok = vectors.engine.snapshot;
    expect(await verifyEngine(key, ok.p, unb64(ok.s))).toBe(true);
    const bad = vectors.engine.tampered_snapshot;
    expect(await verifyEngine(key, bad.p, unb64(bad.s))).toBe(false);
  });

  it("cihaz kimliği ve eşleştirme kanıtı aynı", async () => {
    expect(await keyId(unb64(vectors.device.public_x963))).toBe(vectors.device.device_id);
    const proof = await hmacProof(unb64url(vectors.pairing.secret_b64url), enc.encode(vectors.pairing.payload));
    expect(proof).toBe(vectors.pairing.proof);
  });

  it("zarflar her iki yönde aynı baytları üretir ve açılır", async () => {
    const env = vectors.envelope;
    for (const [direction, recipientHex, recipientPub] of [
      ["e2d", env.device_kx_private_hex, env.device_kx_public_x963],
      ["d2e", env.engine_kx_private_hex, env.engine_kx_public_x963],
    ] as const) {
      const v = env[direction];
      const recipientX963 = unb64(recipientPub);
      const recipient = await importEcPrivate(recipientHex, recipientX963, "ECDH");
      // Alıcı vektördeki zarfı açar.
      expect(await openSealed(v.envelope, recipient, recipientX963, v.info)).toBe(v.plaintext);
      // Aynı geçici anahtar ve nonce ile aynı zarf üretilir.
      const ephemeralX963 = unb64(v.envelope.e);
      const ephemeralPrivate = await importEcPrivate(v.ephemeral_private_hex, ephemeralX963, "ECDH");
      const ephemeral = { privateKey: ephemeralPrivate, publicKey: await crypto.subtle.importKey("raw", new Uint8Array(ephemeralX963), { name: "ECDH", namedCurve: "P-256" }, true, []) };
      const again = await seal(recipientX963, v.plaintext, v.info, { ephemeral, nonce: unb64(v.nonce) });
      expect(again).toEqual(v.envelope);
      // Yanlış bağlamla açılmaz (başka cihaza ya da yöne yönlendirme).
      await expect(openSealed(v.envelope, recipient, recipientX963, v.info.replace(direction, direction === "e2d" ? "d2e" : "e2d"))).rejects.toThrow(RemoteError);
    }
  });
});

describe("eşleştirme kodu", () => {
  async function code(overrides: Record<string, unknown> = {}) {
    const engineKey = unb64(vectors.engine.key);
    const payload = {
      v: 1,
      relay: "wss://relay.example",
      engine_id: await keyId(engineKey),
      engine_key: vectors.engine.key,
      engine_kx: vectors.envelope.engine_kx_public_x963,
      pair: vectors.pairing.secret_b64url,
      exp: Date.now() + 60_000,
      ...overrides,
    };
    return `#p=${b64url(enc.encode(JSON.stringify(payload)))}`;
  }

  it("geçerli kodu okur; süresi dolmuş, güvensiz ya da bozuk kodu açıklamayla reddeder", async () => {
    const parsed = await parsePairing(await code());
    expect(parsed.engine_id).toBe(vectors.engine.engine_id);
    await expect(parsePairing(await code({ exp: Date.now() - 1 }))).rejects.toThrow(/süresi doldu/);
    await expect(parsePairing(await code({ relay: "ws://evil.example" }))).rejects.toThrow(/güvenli değil/);
    await expect(parsePairing(await code({ engine_id: "00".repeat(16) }))).rejects.toThrow(/eşleşmiyor/);
    await expect(parsePairing("#p=%%%")).rejects.toThrow(RemoteError);
    await expect(parsePairing("")).rejects.toThrow(/eşleştirme bilgisi yok/);
  });
});

describe("tarayıcı cihazı", () => {
  it("anahtarlar dışa aktarılamaz; istekler imzalı ve 'browser' korumalı", async () => {
    const keys = await generateDeviceKeys();
    expect(keys.signing.privateKey.extractable).toBe(false);
    expect(keys.kx.privateKey.extractable).toBe(false);
    expect(keys.deviceId).toBe(await keyId(keys.signingPub));
    const parsed = await parsePairing(
      `#p=${b64url(enc.encode(JSON.stringify({ v: 1, relay: "wss://r.example", engine_id: vectors.engine.engine_id, engine_key: vectors.engine.key, engine_kx: vectors.envelope.engine_kx_public_x963, pair: vectors.pairing.secret_b64url, exp: Date.now() + 1000 })))}`,
    );
    const request = await pairRequest(parsed, keys, "Telefon");
    const body = JSON.parse(request.p);
    expect(body.protection).toBe("browser");
    expect(request.proof).toBe(await hmacProof(unb64url(parsed.pair), enc.encode(request.p)));
    const verifyKey = await crypto.subtle.importKey("raw", new Uint8Array(keys.signingPub), { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
    expect(await crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, verifyKey, new Uint8Array(unb64(request.s)), enc.encode(request.p))).toBe(true);
    const command = JSON.parse((await signedCommand(keys, parsed.engine_id, 5, "engage_kill_switch")).p);
    expect(command).toMatchObject({ key: "signing", seq: 5, command: "engage_kill_switch", device_id: keys.deviceId });
    const hello = await deviceHello(keys, parsed.engine_id, 1);
    expect(hello).toMatchObject({ type: "hello", role: "device", key: b64(keys.signingPub), ts_ms: 1 });
  });

  it("motorun gönderdiği (imzalı ve şifreli) mesajı açar; başka cihaza ait ya da değiştirilmiş olanı reddeder", async () => {
    const keys = await generateDeviceKeys();
    const engineId = vectors.engine.engine_id;
    const engineKey = unb64(vectors.engine.key);
    // Vektördeki imzalı özet bu cihaza şifrelenir (motorun yaptığı gibi).
    const signed = JSON.stringify(vectors.engine.snapshot);
    const forOther = await seal(keys.kxPub, signed, channelInfo("e2d", engineId, keys.deviceId));
    // Özet vektördeki cihaza ait: bu cihaz kabul etmemeli.
    await expect(openFromEngine(forOther, keys, engineId, engineKey)).rejects.toThrow(/bu cihaza ait değil/);
    const tampered = await seal(keys.kxPub, JSON.stringify(vectors.engine.tampered_snapshot), channelInfo("e2d", engineId, keys.deviceId));
    await expect(openFromEngine(tampered, keys, engineId, engineKey)).rejects.toThrow(/imzası geçersiz/);
  });
});
