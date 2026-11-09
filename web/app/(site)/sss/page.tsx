import type { Metadata } from "next";

import { RiskNotice } from "@/components/RiskNotice";
import { Container, LinkButton, PageHeader } from "@/components/ui";

export const metadata: Metadata = {
  title: "Sık sorulan sorular",
  description: "Kazanç, güvenlik, API anahtarları, iPhone uygulaması, lisanslar ve kişisel veriler hakkında sorular.",
};

const FAQ: { q: string; a: string[] }[] = [
  {
    q: "Yazılım kazanç sağlar mı?",
    a: [
      "Hayır, böyle bir vaadimiz yok. AI Trading Intelligence piyasayı analiz eden ve sizin belirlediğiniz kurallarla işlem yapabilen bir araçtır; kazanç garantisi sunmaz.",
      "Kripto varlık işlemleri yüksek risk taşır. Yapay zekâ analizleri olasılık tahminidir ve hatalı olabilir; backtest sonuçları geleceği göstermez.",
    ],
  },
  {
    q: "İşlem motoru nerede çalışır? Sunucu kiralamam gerekir mi?",
    a: [
      "Motor kendi Windows bilgisayarınızda çalışır; sunucu (VDS) kiralamanız gerekmez. Bilgisayarınız kapalıyken veya uyku modundayken motor çalışmaz ve işlem yapmaz.",
    ],
  },
  {
    q: "Binance API anahtarlarım güvende mi?",
    a: [
      "Anahtarlarınız bilgisayarınızda, Windows'un şifreleme altyapısıyla (DPAPI) saklanır ve bize gönderilmez.",
      "Para çekme yetkisi açık olan anahtar kabul edilmez. Binance'te anahtar oluştururken para çekme yetkisini kapalı tutun ve mümkünse IP kısıtlaması tanımlayın.",
    ],
  },
  {
    q: "Gerçek parayla işlem nasıl açılır?",
    a: [
      "Uygulama sanal işlem ve Binance test ağı ile başlar. Gerçek hesapta işlem varsayılan olarak kapalıdır; açmak için ayarlarda ayrıca ve açıkça onay vermeniz gerekir.",
      "Gerçek hesapta da işlem başına risk, günlük zarar sınırı ve acil durdurma her zaman etkindir.",
    ],
  },
  {
    q: "iPhone uygulamasıyla neler yapabilirim?",
    a: [
      "Bilgisayarınızdaki motorun durumunu, pozisyonları ve uyarıları izleyebilir, bildirim alabilirsiniz. Acil durdurma ve otomatik işlemi duraklatma tek dokunuşla yapılır.",
      "Pozisyon kapatma ve otomatik işlemi yeniden başlatma Face ID ister. Telefondan yeni pozisyon açılamaz, risk sınırları değiştirilemez ve para çekilemez.",
    ],
  },
  {
    q: "Hangi borsalar destekleniyor?",
    a: ["Şu anda Binance spot ve vadeli (sürekli kontrat) piyasaları desteklenmektedir."],
  },
  {
    q: "Bir lisansı kaç bilgisayarda kullanabilirim?",
    a: [
      "Seçtiğiniz pakete göre aynı anda 1, 2 veya 3 bilgisayarda. Etkin cihaz sayınızı müşteri panelinde görebilirsiniz. iPhone uygulaması lisansa dâhildir.",
    ],
  },
  {
    q: "Deneme sürümü var mı?",
    a: ["7 günlük deneme paketi planlanmaktadır. Satışa açıldığında paketler sayfasında yer alacaktır."],
  },
  {
    q: "İade koşulları nelerdir?",
    a: ["İade ve cayma koşulları, satışlar başladığında mesafeli satış sözleşmesinde ve satın alma sayfasında açıkça belirtilecektir."],
  },
  {
    q: "Verilerim nerede saklanıyor?",
    a: [
      "Hesap ve lisans bilgileriniz bulut hizmetimizde; işlem geçmişiniz, strateji ayarlarınız ve API anahtarlarınız ise yalnızca kendi bilgisayarınızda tutulur.",
      "Ayrıntılar gizlilik ve KVKK aydınlatma metnindedir.",
    ],
  },
];

export default function FaqPage() {
  return (
    <>
      <PageHeader eyebrow="Destek" title="Sık sorulan sorular" />
      <Container className="py-12">
        <div className="max-w-3xl space-y-3">
          {FAQ.map((item) => (
            <details key={item.q} className="group rounded-xl border border-border bg-surface px-5 py-4 open:pb-5">
              <summary className="cursor-pointer list-none text-lg font-semibold text-fg marker:hidden focus-visible:outline-2 focus-visible:outline-accent">
                <span className="flex items-center justify-between gap-4">
                  <span>{item.q}</span>
                  <span aria-hidden="true" className="text-muted transition-transform group-open:rotate-45">
                    +
                  </span>
                </span>
              </summary>
              {item.a.map((paragraph) => (
                <p key={paragraph} className="mt-3 text-fg">
                  {paragraph}
                </p>
              ))}
            </details>
          ))}
        </div>
        <div className="mt-10 flex flex-wrap gap-3">
          <LinkButton href="/iletisim">Başka bir sorunuz mu var?</LinkButton>
        </div>
        <div className="mt-10 max-w-3xl">
          <RiskNotice />
        </div>
      </Container>
    </>
  );
}
