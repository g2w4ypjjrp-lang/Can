// Yardım merkezi içeriği: kurulumdan sık hatalara adım adım rehberler. Metinler kazanç vaadi
// içermez (içerik kuralı testleri tüm sayfalarda denetler).

export interface HelpTopic {
  id: string;
  title: string;
  lead: string;
  steps?: string[];
  notes?: string[];
}

export const HELP_TOPICS: HelpTopic[] = [
  {
    id: "kurulum",
    title: "Uygulamayı kurma",
    lead: "Windows 10 ya da 11 (64 bit) gerekir. Kurulum yönetici izni istemez.",
    steps: [
      "İndir sayfasından kurulum dosyasını indirin.",
      "İsterseniz sayfadaki SHA-256 özetini PowerShell'de Get-FileHash ile karşılaştırarak dosyayı doğrulayın.",
      "Dosyaya çift tıklayın. Windows \"Bilgisayarınız korundu\" uyarısı gösterirse Ek bilgi → Yine de çalıştır'a basın (kod imzalama sertifikası eklenene kadar bu uyarı görünebilir).",
      "Kurulum birkaç saniye sürer; uygulama açılınca işlem motoru arka planda başlar.",
    ],
  },
  {
    id: "lisans",
    title: "Lisansı etkinleştirme",
    lead: "Uygulama açılınca lisans anahtarı ister. Anahtar ATI-XXXX-XXXX-XXXX-XXXX biçimindedir.",
    steps: [
      "Anahtarınız satın almadan sonra Müşteri paneli → Lisanslarım bölümünde görünür (güvenlik için parolanızı yeniden girmeniz istenir).",
      "Anahtarı uygulamadaki lisans ekranına yazıp Etkinleştir'e basın.",
      "Lisans bu bilgisayara bağlanır. Bilgisayar değiştirirken eski bilgisayarda Ayarlar → Lisans → \"Bu bilgisayarı lisanstan çıkar\"ı kullanın ya da müşteri panelinden cihazı kaldırın.",
    ],
    notes: [
      "İnternet yokken lisans 72 saate kadar geçerli kalır; sonra yenilemek için bağlantı gerekir.",
      "Lisans geçersizken yeni işlem açılmaz; açık pozisyonların borsadaki stopları korunur.",
    ],
  },
  {
    id: "iki-adimli",
    title: "Hesabınızda iki adımlı doğrulama",
    lead: "Parolanız ele geçse bile hesabınızı ve lisans anahtarlarınızı korur. Telefonda bir doğrulama uygulaması gerekir.",
    steps: [
      "Müşteri paneli → Güvenlik bölümünde \"Aç\"a basın ve parolanızı girin.",
      "Google Authenticator, Microsoft Authenticator veya 1Password gibi bir uygulamayla QR kodu okutun.",
      "Uygulamadaki 6 haneli kodu yazıp Etkinleştir'e basın.",
      "Gösterilen 10 kurtarma kodunu güvenli bir yere kaydedin; bir daha gösterilmez.",
    ],
    notes: [
      "Telefonunuzu kaybederseniz girişte kod yerine kurtarma kodlarından birini yazın; her kod bir kez çalışır.",
      "Kapatmak için parolanız ve güncel bir kod (veya kurtarma kodu) gerekir.",
    ],
  },
  {
    id: "binance-demo",
    title: "Binance Demo Trading anahtarı oluşturma",
    lead: "Önce sahte bakiyeyle, gerçek fiyatlarla deneyin. Binance'in test ortamı Demo Trading'e taşındı.",
    steps: [
      "demo.binance.com adresine Binance hesabınızla giriş yapın.",
      "Sağ üstten API Management (API Yönetimi) → Create API'ye basın ve bir ad verin.",
      "Görünen API Key ve Secret Key'i kopyalayın (Secret yalnızca bir kez gösterilir).",
      "Uygulamada Ayarlar → Binance Demo Trading anahtarı bölümüne yapıştırıp Doğrula ve kaydet'e basın.",
      "Ayarlar → İşlem modu'nu Demo Trading yapın.",
    ],
    notes: [
      "Gerçek hesap anahtarı ve eski testnet.binance.vision anahtarı Demo Trading'de çalışmaz.",
      "Anahtarlar bilgisayarınızda şifreli saklanır; bize ya da buluta gönderilmez.",
    ],
  },
  {
    id: "gercek-hesap",
    title: "Gerçek parayla işlem (Demo para / Gerçek para)",
    lead: "Uygulama sanal modda açılır. Bot ve elle işlemler için Demo para (Binance Demo Trading) ya da Gerçek para seçilebilir; gerçek para ayrı ve açık onay gerektirir.",
    steps: [
      "binance.com → Profil → API Yönetimi → API Oluştur. Yetkiler: Okuma ve Futures için Vadeli işlemler (Spot için Spot ve Marjin işlemi). Para çekme yetkisini açmayın.",
      "Uygulamada Ayarlar → Binance gerçek hesap anahtarları bölümüne anahtarı girin. Uygulama yetkileri okur; para çekme veya transfer yetkisi açıksa anahtarı reddeder.",
      "Ayarlar → İşlem modu → Gerçek para'ya basın, açılan pencerede onay ifadesini birebir yazın. Lisansın geçerli ve acil durdurmanın kapalı olması gerekir.",
      "Bot kartındaki 'Bot hangi hesapla işlem yapsın?' seçiciyle Demo para ve Gerçek para arasında geçebilirsiniz; Demo'ya dönüş onay istemez.",
    ],
    notes: [
      "Uygulama yeniden başladığında güvenlik için sanal moda döner; gerçek parayı her seferinde yeniden onaylarsınız.",
      "Gerçek hesap anahtarında yalnızca okuma ve işlem izni verin; para çekme (withdraw) iznini asla açmayın. Para çekme izni açık anahtar uygulama tarafından reddedilir.",
      "Anahtara IP kısıtı koymanız önerilir (yalnızca kendi bilgisayarınızın IP adresi).",
      "Gerçek moda geçerken onay ifadesini yazmanız istenir. Kayıp riski size aittir; geçmiş ve sanal sonuçlar gelecekteki sonuçları göstermez.",
    ],
  },
  {
    id: "telefon",
    title: "iPhone'dan kontrol (QR ile eşleştirme)",
    lead: "Telefondan durum izleme, acil durdurma, bot durdurma/başlatma ve pozisyon kapatma yapılabilir; yeni işlem açılamaz, para çekilemez.",
    steps: [
      "Masaüstünde Telefon ekranında \"Telefondan kontrol\" anahtarını açın.",
      "QR kodu göster'e basın (kod 5 dakika geçerli, tek kullanımlık).",
      "iPhone uygulamasında Bilgisayarı eşleştir'e dokunup kodu okutun.",
    ],
    notes: [
      "Kod yalnızca AI Trading Intelligence iPhone uygulamasının içinden okunur; telefonun kendi Kamera uygulaması bu kodu açmaz (bağlantı değil, şifreli eşleşme bilgisidir).",
      "Botu başlatma, pozisyon kapatma ve acil durdurmayı kaldırma Face ID onayı ister.",
    ],
  },
  {
    id: "telegram",
    title: "Telegram bildirimleri",
    lead: "Acil durdurma, pozisyon açılış/kapanışları ve uyarılar kendi Telegram botunuza gelir.",
    steps: [
      "Telegram'da @BotFather'a /newbot yazın, bota ad verin ve verilen bot anahtarını kopyalayın.",
      "Kendi botunuzu açıp /start yazın.",
      "Uygulamada Ayarlar → Telegram bildirimleri: anahtarı yapıştırın, Sohbeti bul'a basın, Kaydet ve aç'a basın.",
      "Deneme mesajı ile kontrol edin.",
    ],
  },
  {
    id: "bot-nasil-karar-verir",
    title: "Bot nasıl karar verir?",
    lead: "Her mum kapanışında 16 strateji, formasyonlar, piyasa rejimi ve üst zaman dilimi birlikte değerlendirilip 0–100 arası bir fırsat puanı hesaplanır. Puan bir göstergedir, kâr garantisi değildir.",
    steps: [
      "Göstergeler ve stratejiler: EMA, RSI, MACD, Bollinger, Ichimoku, VWAP, destek/direnç, hacim, funding ve açık pozisyon gibi 14 klasik kural.",
      "Formasyonlar: yutan mum, çekiç, sabah/akşam yıldızı gibi mum formasyonları ile ikili dip/tepe, omuz-baş-omuz, üçgen ve bayrak kırılımları.",
      "Piyasa rejimi: trend, yatay ya da aşırı oynak piyasa ayırt edilir; trendde trend stratejileri, yatayda dönüş stratejileri öne çıkar, aşırı oynaklıkta puan düşer.",
      "Üst zaman dilimi: 1 saatlik sinyal 4 saatlik trendle karşılaştırılır; büyük trende karşı işlemde puan düşürülür.",
      "Kendini ayarlama: her stratejinin sanal yarışmadaki sonuçlarına göre puandaki ağırlığı saatte bir güncellenir (en az 10 işlemden sonra, 0,4–1,4 arası).",
      "Risk kapısı: puan eşiği geçse bile her işlem zarar durdur, kaldıraç, günlük zarar ve pozisyon sınırlarından geçmek zorundadır.",
    ],
    notes: ["Her fırsatın gerekçesi Fırsatlar ekranında bileşen bileşen görünür; stratejilerin ağırlıkları Strateji performansı ekranındadır."],
  },
  {
    id: "bot-ayarlari",
    title: "Bot (otomatik işlem) ayarları",
    lead: "Bot, puanı eşik üstündeki fırsatlarda yalnızca Demo Trading'de işlem açar. Ayarları Spot / Futures işlemler ekranındaki \"Bot ayarları\" kartından değiştirebilirsiniz.",
    steps: [
      "En düşük fırsat puanı (50–100): yükseldikçe daha az ama daha seçici işlem açılır.",
      "İşlem başına risk: zarar durdurda kaybedilecek pay. Risk sınırının üstüne çıkamaz.",
      "Kaldıraç, saatte en fazla giriş, aynı sembolde bekleme süresi ve piyasaları seçin.",
      "İz süren stop (Futures): yarısı 1R'de alınır, zarar durdur girişe çekilir, kalan yarı fiyatı izleyen stopla taşınır.",
      "Art arda kayıp sınırı: belirlenen sayıda zararlı pozisyondan sonra bot yeni işleme mola verir.",
      "Kaydet'e basın; beğenmezseniz \"Varsayılana dön\" ile ilk ayarlara dönebilirsiniz.",
    ],
    notes: [
      "Her işlem yine risk kapısından geçer ve zarar durdur zorunludur.",
      "Değişiklikler denetim kaydına yazılır. Sonuçlar garanti değildir.",
    ],
  },
  {
    id: "backtest",
    title: "Backtest ve yapay zekâ modeli eğitimi",
    lead: "Stratejileri geçmiş veride, ücret ve kayma dahil deneyin.",
    steps: [
      "Backtest ve eğitim ekranında önce Geçmiş veri bölümünden sembolleri indirin.",
      "Geriye dönük test bölümünde sembolleri ve işlem başı riski seçip Testi başlat'a basın; rapora tıklayarak sonuçları görün.",
      "Model eğitimi bölümünde eğittiğiniz model, Grafik ve AI analiz ekranında tahmin olarak kullanılır.",
    ],
    notes: ["Yürüyen pencere (örneklem dışı) sonuçları aşırı uyumu yakalamaya yardım eder; sonuçlar geleceği garanti etmez."],
  },
  {
    id: "hata-raporlari",
    title: "Hata raporları",
    lead: "İsteğe bağlıdır ve varsayılan olarak kapalıdır. Açarsanız hataları daha hızlı düzeltebiliriz.",
    steps: [
      "Uygulamada Ayarlar → Hata raporları bölümünde \"Hata raporlarını aç\"a basın.",
      "Bir hata oluştuğunda kısa bir teknik rapor otomatik gönderilir; hiçbir şey yapmanız gerekmez.",
    ],
    notes: [
      "Gönderilmeyenler: adınız, e-postanız, kullanıcı klasörünüz, IP adresiniz, lisans ve borsa anahtarlarınız, bakiye ve işlem bilgileri.",
      "Aynı hata saatte bir kez, toplamda saatte en çok 10 rapor gönderilir.",
    ],
  },
  {
    id: "guncelleme",
    title: "Güncellemeler",
    lead: "Yeni sürüm çıkınca uygulamanın üstünde \"Yeni sürüm hazır\" şeridi görünür.",
    notes: [
      "Şimdi güncelle'ye basınca dosyanın imzası doğrulanır, motor birkaç saniye durur ve uygulama yeniden açılır. Borsadaki stop emirleri yerinde kalır.",
    ],
  },
];

export interface Problem {
  q: string;
  a: string;
}

export const PROBLEMS: Problem[] = [
  {
    q: "\"Binance anahtarı reddetti (-2015)\" hatası",
    a: "Anahtar demo.binance.com → API Management'ta oluşturulmalı; gerçek hesap anahtarı ve eski test ağı anahtarı çalışmaz. Gizli anahtarı eksiksiz yapıştırın. IP kısıtı koyduysanız bilgisayarınızın IP adresini ekleyin.",
  },
  {
    q: "\"Bilgisayarın saati Binance'ten farklı (-1021)\" hatası",
    a: "Windows Ayarlar → Saat ve dil → Tarih ve saat: \"Saati otomatik ayarla\"yı açın ve \"Şimdi eşitle\"ye basın.",
  },
  {
    q: "\"Lisans anahtarı geçersiz\"",
    a: "Anahtarı müşteri panelinden kopyalayıp yapıştırın (O harfi ile 0 rakamı karışabilir; uygulama biçimi denetler). \"Henüz bir müşteri hesabına atanmadı\" yazıyorsa anahtar satış havuzundadır ve önce hesabınıza tanımlanmalıdır. Sorun sürerse iletişim formundan yazın.",
  },
  {
    q: "\"Çevrim dışı tolerans süresi doldu\"",
    a: "Bilgisayar 72 saatten uzun süre lisans sunucusuna ulaşamadı. İnternete bağlanıp Ayarlar → Lisans → Şimdi yenile'ye basın.",
  },
  {
    q: "Telefon eşleşmiyor",
    a: "Masaüstünde Telefon ekranında durumun \"Bağlı\" olduğunu kontrol edin, yeni QR kodu üretin ve 5 dakika içinde okutun. Kurumsal ağlarda güvenlik duvarı aktarma servisini engelleyebilir.",
  },
  {
    q: "Telegram mesajı gelmiyor",
    a: "Botunuza Telegram'da /start yazdığınızdan emin olun, Sohbeti bul'u yeniden deneyin ve Deneme mesajı gönderin. Hata mesajı Ayarlar'da görünür.",
  },
];
