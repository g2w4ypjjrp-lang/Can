// Lighthouse CI: herkese açık sayfaların performans, erişilebilirlik, en iyi uygulama ve SEO
// denetimi (mobil öykünme, yavaşlatılmış ağ/işlemci). Raporlar yalnızca yerel dosyaya yazılır;
// hiçbir yere yüklenmez. Önce `npm run build` gerekir.
// Her sayfa şablonundan biri ölçülür: altı yasal metin aynı şablonla (LegalPage) üretilir, en uzunu
// seçildi. Tüm sayfaların erişilebilirliği ayrıca axe ile uçtan uca testlerde (e2e/pages.spec.ts)
// açık ve koyu temada denetlenir. Ücretsiz CI kotası için ölçüm sayısı sınırlı tutulur.
const PAGES = [
  "/",
  "/ozellikler",
  "/paketler",
  "/indir",
  "/sss",
  "/iletisim",
  "/giris",
  "/kayit",
  "/yasal/gizlilik",
];
const PORT = 3200;

module.exports = {
  ci: {
    collect: {
      startServerCommand: `npx next start -p ${PORT} -H 127.0.0.1`,
      startServerReadyPattern: "Ready",
      url: PAGES.map((path) => `http://127.0.0.1:${PORT}${path}`),
      // Her sayfa 3 kez ölçülür, eşikler ortanca sonuca uygulanır: sunucunun ilk isteğindeki
      // ısınma süresi ve paylaşımlı CI makinelerindeki dalgalanma tek ölçümü bozmasın.
      numberOfRuns: 3,
      settings: { chromeFlags: "--headless=new --no-sandbox --disable-dev-shm-usage" },
    },
    assert: {
      assertions: {
        "categories:performance": ["error", { minScore: 0.9, aggregationMethod: "median-run" }],
        "categories:accessibility": ["error", { minScore: 1, aggregationMethod: "median-run" }],
        "categories:best-practices": ["error", { minScore: 0.95, aggregationMethod: "median-run" }],
        "categories:seo": ["error", { minScore: 0.95, aggregationMethod: "median-run" }],
      },
    },
    upload: { target: "filesystem", outputDir: ".lighthouseci/reports" },
  },
};
