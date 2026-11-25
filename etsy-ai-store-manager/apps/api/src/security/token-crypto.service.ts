import { Inject, Injectable } from '@nestjs/common';
import { TokenCipher } from '@esm/integrations';
import { ENV, type Env } from '../config/env.js';

/** Nest wrapper around the shared AES-256-GCM TokenCipher (see packages/integrations). */
@Injectable()
export class TokenCryptoService {
  private readonly cipher: TokenCipher;

  constructor(@Inject(ENV) env: Env) {
    this.cipher = TokenCipher.fromEnv(env);
  }

  get keyVersion(): number {
    return this.cipher.keyVersion;
  }

  encrypt(plaintext: string, associatedData: string): string {
    return this.cipher.encrypt(plaintext, associatedData);
  }

  decrypt(envelope: string, associatedData: string): string {
    return this.cipher.decrypt(envelope, associatedData);
  }
}
