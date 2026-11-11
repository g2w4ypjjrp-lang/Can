import type { Metadata, Viewport } from "next";

import { PhoneApp } from "@/components/phone/PhoneApp";

// Telefondan izleme: masaüstündeki QR kodu bu sayfayı açar (eşleştirme bilgisi adresin #
// kısmındadır ve sunucuya gönderilmez). Bağlantı aktarma servisi üzerinden uçtan uca şifrelidir.
export const metadata: Metadata = {
  title: "Telefondan izleme",
  description: "Bilgisayarınızdaki AI Trading Intelligence motorunu telefondan izleyin; acil durdurun.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function TelefonPage() {
  return <PhoneApp />;
}
