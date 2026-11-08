// İçerik güvenliği politikası. Betikler yalnızca istek başına üretilen nonce ile çalışır;
// sayfa başka bir siteye çerçevelenemez, form başka adrese gönderilemez, ağ istekleri yalnızca
// sitenin kendisine ve hesap API'sine yapılabilir.

export interface CspOptions {
  nonce: string;
  apiOrigin: string;
  dev: boolean;
  https: boolean;
}

export function buildCsp({ nonce, apiOrigin, dev, https }: CspOptions): string {
  const directives: [string, ...string[]][] = [
    ["default-src", "'self'"],
    ["script-src", "'self'", `'nonce-${nonce}'`, "'strict-dynamic'", ...(dev ? ["'unsafe-eval'"] : [])],
    ["style-src", "'self'", dev ? "'unsafe-inline'" : `'nonce-${nonce}'`],
    ["img-src", "'self'", "data:", "blob:"],
    ["font-src", "'self'"],
    ["connect-src", "'self'", apiOrigin, ...(dev ? ["ws:"] : [])],
    ["manifest-src", "'self'"],
    ["worker-src", "'self'"],
    ["frame-src", "'none'"],
    ["frame-ancestors", "'none'"],
    ["object-src", "'none'"],
    ["base-uri", "'self'"],
    ["form-action", "'self'"],
  ];
  if (https) directives.push(["upgrade-insecure-requests"]);
  return directives.map((d) => d.join(" ")).join("; ");
}

export function newNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

export function originOf(url: string): string {
  try {
    return new URL(url).origin;
  } catch {
    return "'self'";
  }
}
