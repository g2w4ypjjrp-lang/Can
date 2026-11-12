import type { NextConfig } from "next";

// İçerik güvenliği politikası (CSP) her istekte yeni bir nonce ile proxy.ts'de eklenir.
// Buradakiler tüm yanıtlara (statik dosyalar dâhil) uygulanan sabit güvenlik başlıklarıdır.
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()",
  },
];

const config: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      // Telefon sayfası: ana ekrandaki uygulamada QR'ı kamerayla okutmak için yalnızca bu sayfada
      // kamera izni (kendi sitesi). Servis çalışanı her açılışta güncel alınır.
      {
        source: "/telefon",
        headers: [
          {
            key: "Permissions-Policy",
            value: "camera=(self), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()",
          },
        ],
      },
      { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache" }] },
    ];
  },
};

export default config;
