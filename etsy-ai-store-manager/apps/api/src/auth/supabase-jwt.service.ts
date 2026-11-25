import { Inject, Injectable, UnauthorizedException } from '@nestjs/common';
import { createRemoteJWKSet, jwtVerify, type JWTPayload, type JWTVerifyGetKey } from 'jose';
import { ENV, type Env } from '../config/env.js';
import type { AuthContext } from '../database/database.service.js';

/**
 * Verifies Supabase Auth access tokens server-side.
 *  - Asymmetric signing keys (default for new projects): JWKS at
 *    <SUPABASE_URL>/auth/v1/.well-known/jwks.json
 *  - Legacy HS256 shared secret: SUPABASE_JWT_SECRET
 */
@Injectable()
export class SupabaseJwtService {
  private readonly issuer: string;
  private readonly audience: string;
  private readonly secret: Uint8Array | null;
  private readonly jwks: JWTVerifyGetKey | null;

  constructor(@Inject(ENV) env: Env) {
    const base = env.SUPABASE_URL.replace(/\/+$/, '');
    this.issuer = `${base}/auth/v1`;
    this.audience = env.SUPABASE_JWT_AUDIENCE;
    this.secret = env.SUPABASE_JWT_SECRET
      ? new TextEncoder().encode(env.SUPABASE_JWT_SECRET)
      : null;
    this.jwks = this.secret
      ? null
      : createRemoteJWKSet(new URL(`${this.issuer}/.well-known/jwks.json`));
  }

  async verify(token: string): Promise<AuthContext> {
    let payload: JWTPayload;
    try {
      const options = { issuer: this.issuer, audience: this.audience, clockTolerance: 5 };
      payload = this.secret
        ? (await jwtVerify(token, this.secret, { ...options, algorithms: ['HS256'] })).payload
        : (await jwtVerify(token, this.jwks!, { ...options, algorithms: ['ES256', 'RS256'] }))
            .payload;
    } catch {
      throw new UnauthorizedException('Oturum geçersiz veya süresi dolmuş');
    }
    if (payload.role !== 'authenticated' || typeof payload.sub !== 'string' || !payload.sub) {
      throw new UnauthorizedException('Oturum geçersiz');
    }
    return {
      userId: payload.sub,
      email: typeof payload.email === 'string' ? payload.email : undefined,
      claims: payload as Record<string, unknown>,
    };
  }
}
