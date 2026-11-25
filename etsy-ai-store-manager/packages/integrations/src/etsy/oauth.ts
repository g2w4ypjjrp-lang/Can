import { createHash, randomBytes } from 'node:crypto';
import { ETSY_DEFAULTS, ETSY_SCOPES, type EtsyAppConfig } from './config.js';
import { EtsyApiError } from './errors.js';

export interface PkcePair {
  verifier: string;
  challenge: string;
}

/** RFC 7636 verifier (43-128 chars of [A-Za-z0-9-._~]) and its S256 challenge. */
export function createPkcePair(): PkcePair {
  const verifier = randomBytes(48).toString('base64url'); // 64 chars, unreserved alphabet
  return { verifier, challenge: pkceChallenge(verifier) };
}

export function pkceChallenge(verifier: string): string {
  return createHash('sha256').update(verifier).digest('base64url');
}

export function createOAuthState(): string {
  return randomBytes(32).toString('base64url');
}

export function buildAuthorizeUrl(
  cfg: EtsyAppConfig,
  params: { state: string; codeChallenge: string; scopes?: readonly string[] },
): string {
  const url = new URL(cfg.connectUrl ?? ETSY_DEFAULTS.connectUrl);
  url.searchParams.set('response_type', 'code');
  url.searchParams.set('client_id', cfg.keystring);
  url.searchParams.set('redirect_uri', cfg.redirectUri);
  url.searchParams.set('scope', (params.scopes ?? ETSY_SCOPES).join(' '));
  url.searchParams.set('state', params.state);
  url.searchParams.set('code_challenge', params.codeChallenge);
  url.searchParams.set('code_challenge_method', 'S256');
  return url.toString();
}

export interface EtsyTokenSet {
  /** Full bearer value as returned by Etsy: "<user_id>.<token>" */
  accessToken: string;
  refreshToken: string;
  tokenType: string;
  expiresAt: Date;
  scopes: string[];
  /** Numeric Etsy user id parsed from the access token prefix. */
  userId: string | null;
}

type FetchLike = typeof fetch;

async function tokenRequest(
  cfg: EtsyAppConfig,
  body: Record<string, string>,
  fetchImpl: FetchLike,
  now: () => Date,
): Promise<EtsyTokenSet> {
  const res = await fetchImpl(cfg.tokenUrl ?? ETSY_DEFAULTS.tokenUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
    body: new URLSearchParams(body).toString(),
  });
  const text = await res.text();
  if (!res.ok) {
    throw new EtsyApiError(res.status, 'POST /v3/public/oauth/token', safeErrorText(text));
  }
  const json = JSON.parse(text) as {
    access_token: string;
    refresh_token: string;
    token_type?: string;
    expires_in: number;
    scope?: string;
  };
  if (!json.access_token || !json.refresh_token) {
    throw new EtsyApiError(502, 'POST /v3/public/oauth/token', 'Token response is missing fields');
  }
  const prefix = json.access_token.split('.')[0] ?? '';
  return {
    accessToken: json.access_token,
    refreshToken: json.refresh_token,
    tokenType: json.token_type ?? 'Bearer',
    expiresAt: new Date(now().getTime() + Number(json.expires_in ?? 3600) * 1000),
    scopes: (json.scope ?? '').split(' ').filter(Boolean),
    userId: /^\d+$/.test(prefix) ? prefix : null,
  };
}

export function exchangeAuthorizationCode(
  cfg: EtsyAppConfig,
  input: { code: string; codeVerifier: string },
  fetchImpl: FetchLike = fetch,
  now: () => Date = () => new Date(),
): Promise<EtsyTokenSet> {
  return tokenRequest(
    cfg,
    {
      grant_type: 'authorization_code',
      client_id: cfg.keystring,
      redirect_uri: cfg.redirectUri,
      code: input.code,
      code_verifier: input.codeVerifier,
    },
    fetchImpl,
    now,
  );
}

export function refreshAccessToken(
  cfg: EtsyAppConfig,
  refreshToken: string,
  fetchImpl: FetchLike = fetch,
  now: () => Date = () => new Date(),
): Promise<EtsyTokenSet> {
  return tokenRequest(
    cfg,
    { grant_type: 'refresh_token', client_id: cfg.keystring, refresh_token: refreshToken },
    fetchImpl,
    now,
  );
}

/** Never echo tokens back in errors/logs. */
function safeErrorText(text: string): string {
  try {
    const j = JSON.parse(text) as { error?: string; error_description?: string };
    return [j.error, j.error_description].filter(Boolean).join(': ') || 'token request failed';
  } catch {
    return text.slice(0, 200).replace(/[A-Za-z0-9._-]{30,}/g, '[redacted]');
  }
}
