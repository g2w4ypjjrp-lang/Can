import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import { ApiProvider } from "@/components/ApiContext";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { runtimeConfig } from "@/lib/config";

import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  return { ...baseMetadata, metadataBase: new URL(runtimeConfig().siteUrl) };
}

const baseMetadata: Metadata = {
  title: { default: "AI Trading Intelligence — Kripto analiz ve işlem yazılımı", template: "%s · AI Trading Intelligence" },
  description:
    "Binance verisi, balina takibi, yapay zekâ destekli analiz, backtest ve risk yönetimi tek bir Windows uygulamasında. İşlem motoru bilgisayarınızda çalışır; API anahtarlarınız sizde kalır.",
  applicationName: "AI Trading Intelligence",
  openGraph: { type: "website", locale: "tr_TR", siteName: "AI Trading Intelligence" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#111723" },
  ],
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // İstek başlığını okumak sayfayı dinamik yapar: CSP nonce'u her istekte yenidir (proxy.ts).
  await headers();
  const { publicApiUrl } = runtimeConfig();
  return (
    <html lang="tr">
      <body className="flex min-h-screen flex-col font-sans">
        <a
          href="#icerik"
          className="visually-hidden focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:h-auto focus:w-auto focus:rounded-md focus:bg-accent focus:px-4 focus:py-2 focus:text-accent-fg"
        >
          İçeriğe geç
        </a>
        <ApiProvider baseUrl={publicApiUrl}>
          <SiteHeader />
          <main id="icerik" className="flex-1">
            {children}
          </main>
          <SiteFooter />
        </ApiProvider>
      </body>
    </html>
  );
}
