import type { MetadataRoute } from "next";

import { runtimeConfig } from "@/lib/config";
import { PUBLIC_PAGES } from "@/lib/pages";

// Site adresi çalışma anı ayarıdır; derleme anında sabitlenmez.
export const dynamic = "force-dynamic";

export default function sitemap(): MetadataRoute.Sitemap {
  const { siteUrl } = runtimeConfig();
  return PUBLIC_PAGES.map((path) => ({ url: `${siteUrl}${path === "/" ? "" : path}`, changeFrequency: "monthly" }));
}
