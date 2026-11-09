// Herkese açık sayfalar: site haritası, uçtan uca testler ve erişilebilirlik/performans
// denetimleri bu listeyi kullanır.
export const PUBLIC_PAGES = [
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
] as const;

export const PRIVATE_PATHS = [
  "/panel",
  "/satin-al",
  "/eposta-dogrula",
  "/sifre-sifirla",
  "/sifremi-unuttum",
  "/yonetim",
] as const;
