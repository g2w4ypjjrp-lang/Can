// Lighthouse CI: herkese açık sayfaların performans, erişilebilirlik, en iyi uygulama ve SEO
// denetimi (mobil öykünme, yavaşlatılmış ağ/işlemci). Raporlar yalnızca yerel dosyaya yazılır;
// hiçbir yere yüklenmez. Önce `npm run build` gerekir.
const PAGES = [
  "/",
  "/ozellikler",
  "/paketler",
  "/sss",
  "/iletisim",
  "/giris",
  "/kayit",
  "/yasal/kullanim-kosullari",
  "/yasal/gizlilik",
  "/yasal/risk-bildirimi",
];
const PORT = 3200;

module.exports = {
  ci: {
    collect: {
      startServerCommand: `npx next start -p ${PORT} -H 127.0.0.1`,
      startServerReadyPattern: "Ready",
      url: PAGES.map((path) => `http://127.0.0.1:${PORT}${path}`),
      numberOfRuns: 1,
      settings: { chromeFlags: "--headless=new --no-sandbox --disable-dev-shm-usage" },
    },
    assert: {
      assertions: {
        "categories:performance": ["error", { minScore: 0.9 }],
        "categories:accessibility": ["error", { minScore: 1 }],
        "categories:best-practices": ["error", { minScore: 0.95 }],
        "categories:seo": ["error", { minScore: 0.95 }],
      },
    },
    upload: { target: "filesystem", outputDir: ".lighthouseci/reports" },
  },
};
