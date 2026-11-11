// Telefon tarayıcısı için uzaktan kontrol protokolü (remote-v1). Masaüstündeki QR kodu
// canarslan.net.tr/telefon#p=<eşleştirme bilgisi> adresini açar; # sonrası sunucuya gitmez.
//
// Kriptografi tarayıcının kendi WebCrypto'suyla yapılır; gizli anahtarlar dışa aktarılamaz
// (extractable: false) ve yalnızca bu tarayıcıda (IndexedDB) durur:
// * imza: P-256 ECDSA/SHA-256, ham r‖s (motor ve iPhone ile aynı)
// * motor imzası: Ed25519 (@noble/ed25519)
// * zarf: geçici P-256 ECDH → HKDF-SHA256 (tuz = geçici ‖ alıcı) → AES-256-GCM (ek veri = info)
// Tarayıcı biyometrik kanıt veremez ("browser" koruması): motor korumalı komutları reddeder.

import { verifyAsync } from "@noble/ed25519";

export interface PairingCode {
  v: 1;
  relay: string;
  engine_id: string;
  engine_key: string;
  engine_kx: string;
  pair: string;
  exp: number;
}

export interface Envelope {
  v: 1;
  e: string;
  n: string;
  c: string;
}

export interface Signed {
  p: string;
  s: string;
  proof?: string;
}

export class RemoteError extends Error {}

const subtle = (): SubtleCrypto => globalThis.crypto.subtle;
const enc = new TextEncoder();
const dec = new TextDecoder();
/** WebCrypto'nun beklediği tampon (TS 5.9: Uint8Array<ArrayBuffer>). */
const buf = (bytes: Uint8Array): Uint8Array<ArrayBuffer> => new Uint8Array(bytes);

// --- Kodlama -------------------------------------------------------------------------------------

export function b64(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

export function unb64(text: string): Uint8Array {
  const s = atob(text);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

export function b64url(bytes: Uint8Array): string {
  return b64(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function unb64url(text: string): Uint8Array {
  const padded = text.replace(/-/g, "+").replace(/_/g, "/");
  return unb64(padded + "=".repeat((4 - (padded.length % 4)) % 4));
}

export function hex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function unhex(text: string): Uint8Array {
  const out = new Uint8Array(text.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(text.slice(i * 2, i * 2 + 2), 16);
  return out;
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const p of parts) {
    out.set(p, offset);
    offset += p.length;
  }
  return out;
}

/** Kimlik: SHA-256(açık anahtar) ilk 16 bayt, onaltılık (engine_id / device_id). */
export async function keyId(publicKey: Uint8Array): Promise<string> {
  const digest = new Uint8Array(await subtle().digest("SHA-256", buf(publicKey)));
  return hex(digest.slice(0, 16));
}

// --- QR kodu ---------------------------------------------------------------------------------------

/** Adresin # kısmından (``#p=<base64url JSON>``) eşleştirme bilgisini okur ve denetler. */
export async function parsePairing(hash: string, now = Date.now()): Promise<PairingCode> {
  const match = /[#&]p=([A-Za-z0-9_-]+)/.exec(hash)?.[1];
  if (!match) throw new RemoteError("Adreste eşleştirme bilgisi yok. QR kodu yeniden okutun.");
  let code: PairingCode;
  try {
    code = JSON.parse(dec.decode(unb64url(match))) as PairingCode;
  } catch {
    throw new RemoteError("QR kodu okunamadı. Masaüstünde yeni kod üretip tekrar okutun.");
  }
  if (code.v !== 1) throw new RemoteError("Desteklenmeyen kod sürümü");
  const loopback = ["ws://127.0.0.1", "ws://localhost", "ws://[::1]"];
  if (typeof code.relay !== "string" || !(code.relay.startsWith("wss://") || loopback.some((p) => code.relay.startsWith(p)))) {
    throw new RemoteError("Aktarma adresi güvenli değil");
  }
  if (!code.engine_kx) throw new RemoteError("Kod şifreleme anahtarı içermiyor; masaüstü uygulamasını güncelleyin");
  if ((await keyId(unb64(code.engine_key))) !== code.engine_id) {
    throw new RemoteError("Motor kimliği anahtarla eşleşmiyor");
  }
  if (typeof code.exp !== "number" || code.exp < now) {
    throw new RemoteError("Kodun süresi doldu. Masaüstünde \"Yeni kod üret\"e basıp tekrar okutun.");
  }
  return code;
}

// --- Anahtarlar --------------------------------------------------------------------------------------

export interface DeviceKeys {
  signing: CryptoKeyPair;
  guarded: CryptoKeyPair;
  kx: CryptoKeyPair;
  signingPub: Uint8Array;
  guardedPub: Uint8Array;
  kxPub: Uint8Array;
  deviceId: string;
}

async function rawPublic(key: CryptoKey): Promise<Uint8Array> {
  return new Uint8Array(await subtle().exportKey("raw", key)); // X9.63, 65 bayt
}

/** Bu tarayıcıya özel anahtarlar. Gizli kısımlar dışa aktarılamaz. */
export async function generateDeviceKeys(): Promise<DeviceKeys> {
  const ecdsa = { name: "ECDSA", namedCurve: "P-256" } as const;
  const signing = (await subtle().generateKey(ecdsa, false, ["sign", "verify"])) as CryptoKeyPair;
  const guarded = (await subtle().generateKey(ecdsa, false, ["sign", "verify"])) as CryptoKeyPair;
  const kx = (await subtle().generateKey({ name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"])) as CryptoKeyPair;
  const signingPub = await rawPublic(signing.publicKey);
  return {
    signing,
    guarded,
    kx,
    signingPub,
    guardedPub: await rawPublic(guarded.publicKey),
    kxPub: await rawPublic(kx.publicKey),
    deviceId: await keyId(signingPub),
  };
}

/** P-256 ECDSA/SHA-256; WebCrypto imzası zaten ham r‖s (64 bayt). */
export async function signP256(privateKey: CryptoKey, data: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await subtle().sign({ name: "ECDSA", hash: "SHA-256" }, privateKey, buf(data)));
}

export async function verifyEngine(engineKey: Uint8Array, text: string, signature: Uint8Array): Promise<boolean> {
  try {
    return await verifyAsync(signature, enc.encode(text), engineKey);
  } catch {
    return false;
  }
}

// --- Zarf (uçtan uca şifreleme) ---------------------------------------------------------------------

export function channelInfo(direction: "e2d" | "d2e", engineId: string, deviceId: string): string {
  return `ati-remote-v1|${direction}|${engineId}|${deviceId}`;
}

async function envelopeKey(shared: Uint8Array, ephemeralPub: Uint8Array, recipientPub: Uint8Array, info: Uint8Array, usage: KeyUsage) {
  const ikm = await subtle().importKey("raw", buf(shared), "HKDF", false, ["deriveBits"]);
  const bits = await subtle().deriveBits(
    { name: "HKDF", hash: "SHA-256", salt: buf(concat(ephemeralPub, recipientPub)), info: buf(info) },
    ikm,
    256,
  );
  return subtle().importKey("raw", bits, "AES-GCM", false, [usage]);
}

async function ecdh(privateKey: CryptoKey, peerX963: Uint8Array): Promise<Uint8Array> {
  const peer = await subtle().importKey("raw", buf(peerX963), { name: "ECDH", namedCurve: "P-256" }, false, []);
  return new Uint8Array(await subtle().deriveBits({ name: "ECDH", public: peer }, privateKey, 256));
}

export async function seal(
  recipientPub: Uint8Array,
  plaintext: string,
  info: string,
  fixed?: { ephemeral: CryptoKeyPair; nonce: Uint8Array },
): Promise<Envelope> {
  const ephemeral =
    fixed?.ephemeral ?? ((await subtle().generateKey({ name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"])) as CryptoKeyPair);
  const ephemeralPub = await rawPublic(ephemeral.publicKey);
  const nonce = fixed?.nonce ?? globalThis.crypto.getRandomValues(new Uint8Array(12));
  const infoBytes = enc.encode(info);
  const key = await envelopeKey(await ecdh(ephemeral.privateKey, recipientPub), ephemeralPub, recipientPub, infoBytes, "encrypt");
  const sealed = await subtle().encrypt(
    { name: "AES-GCM", iv: buf(nonce), additionalData: buf(infoBytes), tagLength: 128 },
    key,
    buf(enc.encode(plaintext)),
  );
  return { v: 1, e: b64(ephemeralPub), n: b64(nonce), c: b64(new Uint8Array(sealed)) };
}

export async function openSealed(envelope: unknown, recipient: CryptoKey, recipientPub: Uint8Array, info: string): Promise<string> {
  const env = envelope as Partial<Envelope> | null;
  if (!env || env.v !== 1 || typeof env.e !== "string" || typeof env.n !== "string" || typeof env.c !== "string") {
    throw new RemoteError("şifreli zarf bekleniyordu");
  }
  const ephemeralPub = unb64(env.e);
  const infoBytes = enc.encode(info);
  const key = await envelopeKey(await ecdh(recipient, ephemeralPub), ephemeralPub, recipientPub, infoBytes, "decrypt");
  try {
    const plain = await subtle().decrypt(
      { name: "AES-GCM", iv: buf(unb64(env.n)), additionalData: buf(infoBytes), tagLength: 128 },
      key,
      buf(unb64(env.c)),
    );
    return dec.decode(plain);
  } catch {
    throw new RemoteError("zarf çözülemedi");
  }
}

/** Test vektörleri için: ham P-256 gizli sayıyı (ve açık anahtarı) WebCrypto anahtarına çevirir. */
export async function importEcPrivate(privateHex: string, publicX963: Uint8Array, algorithm: "ECDH" | "ECDSA"): Promise<CryptoKey> {
  const jwk: JsonWebKey = {
    kty: "EC",
    crv: "P-256",
    d: b64url(unhex(privateHex)),
    x: b64url(publicX963.slice(1, 33)),
    y: b64url(publicX963.slice(33, 65)),
  };
  const usages: KeyUsage[] = algorithm === "ECDH" ? ["deriveBits"] : ["sign"];
  return subtle().importKey("jwk", jwk, { name: algorithm, namedCurve: "P-256" }, false, usages);
}

// --- Mesajlar -------------------------------------------------------------------------------------------

export function relayHelloText(deviceId: string, engineId: string, ts: number): string {
  return `ati-relay-hello|device|${deviceId}|${engineId}|${ts}`;
}

export async function hmacProof(secret: Uint8Array, data: Uint8Array): Promise<string> {
  const key = await subtle().importKey("raw", buf(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return b64(new Uint8Array(await subtle().sign("HMAC", key, buf(data))));
}

export async function deviceHello(keys: DeviceKeys, engineId: string, ts = Date.now()) {
  const sig = await signP256(keys.signing.privateKey, enc.encode(relayHelloText(keys.deviceId, engineId, ts)));
  return { type: "hello", role: "device", device_id: keys.deviceId, engine_id: engineId, key: b64(keys.signingPub), ts_ms: ts, sig: b64(sig) };
}

export async function pairRequest(code: PairingCode, keys: DeviceKeys, name: string, ts = Date.now()): Promise<Signed> {
  const nonce = hex(globalThis.crypto.getRandomValues(new Uint8Array(8)));
  const text = JSON.stringify({
    v: 1,
    type: "pair_request",
    engine_id: code.engine_id,
    device_id: keys.deviceId,
    name: name.slice(0, 60),
    signing_key: b64(keys.signingPub),
    guarded_key: b64(keys.guardedPub),
    protection: "browser",
    kx_key: b64(keys.kxPub),
    ts_ms: ts,
    nonce,
  });
  const data = enc.encode(text);
  return { p: text, s: b64(await signP256(keys.signing.privateKey, data)), proof: await hmacProof(unb64url(code.pair), data) };
}

export async function signedCommand(
  keys: DeviceKeys,
  engineId: string,
  seq: number,
  command: string,
  args: Record<string, unknown> = {},
  ts = Date.now(),
): Promise<Signed> {
  const text = JSON.stringify({ v: 1, type: "command", engine_id: engineId, device_id: keys.deviceId, key: "signing", seq, ts_ms: ts, command, args });
  return { p: text, s: b64(await signP256(keys.signing.privateKey, enc.encode(text))) };
}

/** Motordan gelen zarfı açar, Ed25519 imzasını doğrular, içeriği döner. */
export async function openFromEngine(
  envelope: unknown,
  keys: DeviceKeys,
  engineId: string,
  engineKey: Uint8Array,
): Promise<Record<string, unknown>> {
  const text = await openSealed(envelope, keys.kx.privateKey, keys.kxPub, channelInfo("e2d", engineId, keys.deviceId));
  const signed = JSON.parse(text) as Signed;
  if (typeof signed.p !== "string" || typeof signed.s !== "string" || !(await verifyEngine(engineKey, signed.p, unb64(signed.s)))) {
    throw new RemoteError("motor imzası geçersiz");
  }
  const payload = JSON.parse(signed.p) as Record<string, unknown>;
  if (payload.engine_id !== engineId || (payload.device_id !== undefined && payload.device_id !== keys.deviceId)) {
    throw new RemoteError("mesaj bu cihaza ait değil");
  }
  return payload;
}

export async function sealForEngine(message: Signed, engineKx: Uint8Array, engineId: string, deviceId: string): Promise<Envelope> {
  return seal(engineKx, JSON.stringify(message), channelInfo("d2e", engineId, deviceId));
}

export const REASONS: Record<string, string> = {
  ok: "Uygulandı",
  replay: "Bu komut daha önce işlendi",
  stale: "Telefon saati yanlış ya da komut gecikti",
  bad_signature: "İmza geçersiz",
  biometric_required: "Face ID onayı gerekli",
  browser_view_only: "Bu işlem telefon tarayıcısından yapılamaz; masaüstü uygulamasından yapın",
  revoked_device: "Bu telefonun eşleştirmesi kaldırılmış",
  unknown_device: "Telefon eşleştirilmemiş",
  not_allowed: "Bu işlem uzaktan yapılamaz",
  failed: "Motor işlemi uygulayamadı",
  device_limit: "Lisansınızdaki telefon sınırı dolu",
};
