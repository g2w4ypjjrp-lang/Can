// Uygulama sürümleri (indirme sayfası). Kaynak: bulut API'si GET /v1/releases; sürümler yönetim
// panelinden (Sürümler) yayınlanır. API'ye ulaşılamazsa sayfa çökmez, "yakında" gösterilir.

import { runtimeConfig } from "@/lib/config";

export interface Release {
  version: string;
  download_url: string;
  sha256: string | null;
  size_bytes: number | null;
  min_os: string;
  notes: string;
  signed: boolean;
  published_at: string;
}

export interface Releases {
  windows: Release | null;
  ios: Release | null;
}

export interface ReleasesResult {
  releases: Releases;
  reachable: boolean;
}

const NONE: Releases = { windows: null, ios: null };

export async function fetchReleases(fetcher: typeof fetch = fetch): Promise<ReleasesResult> {
  const cfg = runtimeConfig();
  try {
    const response = await fetcher(`${cfg.serverApiUrl}/v1/releases`, {
      signal: AbortSignal.timeout(3000),
      ...(cfg.plansRevalidateS > 0
        ? { next: { revalidate: Math.min(cfg.plansRevalidateS, 60) } }
        : { cache: "no-store" as const }),
    });
    if (!response.ok) return { releases: NONE, reachable: false };
    const body = (await response.json()) as Partial<Releases> | null;
    return {
      releases: { windows: usable(body?.windows), ios: usable(body?.ios) },
      reachable: true,
    };
  } catch {
    return { releases: NONE, reachable: false };
  }
}

/** Yalnızca https bağlantısı olan, biçimi doğru kayıt gösterilir (API zaten denetler; ikinci kat). */
export function usable(release: Release | null | undefined): Release | null {
  if (!release || typeof release.version !== "string" || typeof release.download_url !== "string") return null;
  let url: URL;
  try {
    url = new URL(release.download_url);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" || url.username || url.password) return null;
  if (release.sha256 !== null && !/^[0-9a-f]{64}$/.test(release.sha256)) return null;
  return release;
}

/** 95_000_000 → "90,6 MB" (ikili birim, Windows'un gösterdiği gibi). */
export function formatSize(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return "—";
  const units = ["bayt", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 ? 0 : 1;
  return `${value.toLocaleString("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits })} ${units[unit]}`;
}

/** İndirilen dosyanın adı (doğrulama komutunda gösterilir). */
export function fileName(url: string): string {
  try {
    const last = new URL(url).pathname.split("/").filter(Boolean).pop();
    return last ? decodeURIComponent(last) : "kurulum.exe";
  } catch {
    return "kurulum.exe";
  }
}
