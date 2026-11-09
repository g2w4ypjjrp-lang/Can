// Çalışma anı ayarları (sunucu tarafı). Aynı derleme, ortam değişkenleriyle farklı ortamlarda
// (yerel, test, hazırlık, üretim) çalışır; tarayıcıya yalnızca açık API adresi aktarılır.

export interface RuntimeConfig {
  /** Tarayıcının çağırdığı hesap API'si (ör. https://api.alanadi.com). */
  publicApiUrl: string;
  /** Sunucunun çağırdığı API (iç ağ adresi olabilir). */
  serverApiUrl: string;
  /** Sitenin kanonik adresi (site haritası, meta veriler). */
  siteUrl: string;
  /** Paket listesinin önbellek süresi (sn). */
  plansRevalidateS: number;
  production: boolean;
  /** Yönetim paneli alan adı (ör. admin.canarslan.net.tr). Tanımlıysa /yonetim yalnızca orada açılır. */
  adminHost: string | null;
}

function trimSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

export function runtimeConfig(env: Record<string, string | undefined> = process.env): RuntimeConfig {
  const publicApiUrl = trimSlash(env.ATI_PUBLIC_API_URL ?? "http://localhost:8000");
  const revalidate = Number(env.ATI_PLANS_REVALIDATE_S ?? "300");
  return {
    publicApiUrl,
    serverApiUrl: trimSlash(env.ATI_API_URL ?? publicApiUrl),
    siteUrl: trimSlash(env.ATI_PUBLIC_WEB_URL ?? "http://localhost:3000"),
    plansRevalidateS: Number.isFinite(revalidate) && revalidate >= 0 ? revalidate : 300,
    production: env.ATI_ENVIRONMENT === "production",
    adminHost: env.ATI_ADMIN_HOST?.trim().toLowerCase() || null,
  };
}
