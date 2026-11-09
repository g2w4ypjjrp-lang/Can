// RFC 6238 TOTP (testler için). Sunucu aynı zaman adımındaki kodu ikinci kez kabul etmediğinden
// her kod bir öncekinden sonraki adımdan üretilir; gerekirse yeni adım beklenir.
import { createHmac } from "node:crypto";

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

function base32(text: string): Buffer {
  let bits = "";
  for (const ch of text.replace(/=+$/, "").toUpperCase()) {
    const value = ALPHABET.indexOf(ch);
    if (value < 0) throw new Error("base32");
    bits += value.toString(2).padStart(5, "0");
  }
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

export function totpAt(secret: string, step: number): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const digest = createHmac("sha1", base32(secret)).update(counter).digest();
  const offset = digest[digest.length - 1]! & 0x0f;
  const value = (digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(value).padStart(6, "0");
}

export class TotpDevice {
  private last = -1;
  constructor(readonly secret: string) {}

  async next(): Promise<string> {
    for (;;) {
      const current = Math.floor(Date.now() / 30_000);
      const step = Math.max(current, this.last + 1);
      if (step <= current + 1) {
        this.last = step;
        return totpAt(this.secret, step);
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
}
