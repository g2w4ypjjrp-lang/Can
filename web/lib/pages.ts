// Herkese açık sayfalar: site haritası, uçtan uca testler ve erişilebilirlik/performans
// denetimleri bu listeyi kullanır.
export const PUBLIC_PAGES = [
  "/",
  "/ozellikler",
  "/paketler",
  "/indir",
  "/sss",
  "/yardim",
  "/iletisim",
  "/giris",
  "/kayit",
  "/yasal/kullanim-kosullari",
  "/yasal/gizlilik",
  "/yasal/risk-bildirimi",
  "/yasal/on-bilgilendirme",
  "/yasal/mesafeli-satis-sozlesmesi",
  "/yasal/iptal-ve-iade",
] as const;

export const PRIVATE_PATHS = [
  "/panel",
  "/satin-al",
  "/odeme",
  "/eposta-dogrula",
  "/sifre-sifirla",
  "/sifremi-unuttum",
  "/yonetim",
] as const;
