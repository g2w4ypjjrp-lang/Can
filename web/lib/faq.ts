// Sık sorulan sorular: SSS sayfası ve ana sayfadaki seçki aynı kaynaktan.

export interface FaqItem {
  q: string;
  a: string[];
}

export const FAQ: FaqItem[] = [
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
