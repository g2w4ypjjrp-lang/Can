import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';

/**
 * AES-256-GCM envelope for secrets stored in the database (OAuth tokens, PKCE verifiers).
 * Format: v<keyVersion>.<iv b64url>.<authTag b64url>.<ciphertext b64url>
 * `associatedData` binds a ciphertext to its owner row (e.g. "connected_account:<id>"),
 * so a value copied to another row fails to decrypt.
 * Several key versions can be loaded at once to allow rotation.
 */
export class TokenCipher {
  private readonly keys = new Map<number, Buffer>();

  constructor(
    readonly currentVersion: number,
    keys: Record<number, string>,
  ) {
    for (const [v, b64] of Object.entries(keys)) {
      const key = Buffer.from(b64, 'base64');
      if (key.length !== 32) throw new Error(`Token key v${v} must be 32 bytes (base64)`);
      this.keys.set(Number(v), key);
    }
    if (!this.keys.has(currentVersion)) throw new Error(`Missing token key v${currentVersion}`);
  }

  /** Builds a cipher from TOKEN_ENCRYPTION_KEY (+ optional TOKEN_ENCRYPTION_PREVIOUS_KEYS="1:base64,2:base64"). */
  static fromEnv(env: {
    TOKEN_ENCRYPTION_KEY: string;
    TOKEN_ENCRYPTION_KEY_VERSION: number;
    TOKEN_ENCRYPTION_PREVIOUS_KEYS?: string | undefined;
  }): TokenCipher {
    const keys: Record<number, string> = {};
    for (const part of (env.TOKEN_ENCRYPTION_PREVIOUS_KEYS ?? '').split(',').filter(Boolean)) {
      const [v, k] = part.split(':');
      if (v && k) keys[Number(v)] = k;
    }
    keys[env.TOKEN_ENCRYPTION_KEY_VERSION] = env.TOKEN_ENCRYPTION_KEY;
    return new TokenCipher(env.TOKEN_ENCRYPTION_KEY_VERSION, keys);
  }

  get keyVersion(): number {
    return this.currentVersion;
  }

  encrypt(plaintext: string, associatedData: string): string {
    const key = this.keys.get(this.currentVersion)!;
    const iv = randomBytes(12);
    const cipher = createCipheriv('aes-256-gcm', key, iv);
    cipher.setAAD(Buffer.from(associatedData, 'utf8'));
    const ct = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
    return [
      `v${this.currentVersion}`,
      iv.toString('base64url'),
      cipher.getAuthTag().toString('base64url'),
      ct.toString('base64url'),
    ].join('.');
  }

  decrypt(envelope: string, associatedData: string): string {
    const parts = envelope.split('.');
    if (parts.length !== 4 || !parts[0]!.startsWith('v')) throw new Error('Invalid token envelope');
    const version = Number(parts[0]!.slice(1));
    const key = this.keys.get(version);
    if (!key) throw new Error(`Unknown token key version ${version}`);
    const decipher = createDecipheriv('aes-256-gcm', key, Buffer.from(parts[1]!, 'base64url'));
    decipher.setAAD(Buffer.from(associatedData, 'utf8'));
    decipher.setAuthTag(Buffer.from(parts[2]!, 'base64url'));
    return Buffer.concat([
      decipher.update(Buffer.from(parts[3]!, 'base64url')),
      decipher.final(),
    ]).toString('utf8');
  }

  /** Key version of an existing envelope (used by the rotation job). */
  static versionOf(envelope: string): number {
    return Number(envelope.split('.')[0]?.slice(1));
  }
}
