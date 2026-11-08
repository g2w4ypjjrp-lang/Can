import type { MetadataRoute } from "next";

import { runtimeConfig } from "@/lib/config";
import { PRIVATE_PATHS } from "@/lib/pages";

// Site adresi çalışma anı ayarıdır; derleme anında sabitlenmez.
export const dynamic = "force-dynamic";

export default function robots(): MetadataRoute.Robots {
  const { siteUrl } = runtimeConfig();
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: [...PRIVATE_PATHS] }],
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}
