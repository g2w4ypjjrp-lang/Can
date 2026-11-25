import { Inject, Injectable } from '@nestjs/common';
import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';
import { ENV, type Env } from '../config/env.js';

/**
 * AES-256-GCM envelope for OAuth tokens stored in public.oauth_tokens.
 * Format: v<keyVersion>.<iv b64url>.<authTag b64url>.<ciphertext b64url>
 * The associated data binds a ciphertext to its connected account, so a token
 * row copied to another account fails to decrypt.
 */
@Injectable()
export class TokenCryptoService {
  private readonly keys = new Map<number, Buffer>();
  private readonly currentVersion: number;

  constructor(@Inject(ENV) env: Env) {
    this.currentVersion = env.TOKEN_ENCRYPTION_KEY_VERSION;
    this.keys.set(
      env.TOKEN_ENCRYPTION_KEY_VERSION,
      Buffer.from(env.TOKEN_ENCRYPTION_KEY, 'base64'),
    );
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
    const tag = cipher.getAuthTag();
    return [
      'v' + this.currentVersion,
      iv.toString('base64url'),
      tag.toString('base64url'),
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
}
