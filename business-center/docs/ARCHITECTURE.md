# AI Business Center: Teknik Mimari

## 1. Genel bakış

```
                 ┌───────────────────────────── Tarayıcı ─────────────────────────────┐
                 │ Next.js paneli (yalnızca kullanıcı oturum tokenı, API anahtarı YOK)│
                 └───────────────┬──────────────────────────────────┬─────────────────┘
                                 │ Bearer JWT                        │ Supabase Auth
                                 ▼                                   ▼
┌────────────────────────── Backend (FastAPI) ──────────────────────────┐   ┌──────────────┐
│ auth (JWT doğrulama) · rate limit · audit · hata eşleme               │   │ Supabase     │
│ api/  dashboard · organizations · approvals · (P2+) tasks, ceo, ...   │◄─►│ Postgres+RLS │
│ agents/       CEO + 15 uzman + 5 QC ajanı · registry · llm · orchestrator│   │ Storage, Auth│
│ approvals/ (P1 çekirdek) · executor (P3/P4: onaylı işlemi yürütür)    │   └──────────────┘
│ integrations/ (P3/P4) youtube · etsy · printify · anthropic           │
└───────────────┬───────────────────────────────────────────────────────┘
                │ Celery görevleri (P2/P6)
                ▼
         Redis ── worker(lar) ── beat (zamanlanmış raporlar)
```

**Temel kural:** AI çalışır, analiz eder, önerir. Yayınlama, fiyat değişikliği, silme, iade,
reklam ve para harcatan her işlem bir `approvals` kaydı olarak beklemeye alınır. Yalnızca
owner/admin rolündeki bir kullanıcı onaylayabilir. Onaylanan işlem bile yürütülmeden önce
yetki, süre ve `payload_hash` ile yeniden doğrulanır.

## 2. Klasör yapısı

```
business-center/
├── backend/                 Python 3.12+ / FastAPI
│   ├── src/bizcenter/
│   │   ├── main.py          uygulama fabrikası, middleware
│   │   ├── config.py        ortam değişkenleri (BC_*)
│   │   ├── auth.py          Supabase JWT doğrulama (JWKS veya HS256)
│   │   ├── db.py            havuz + kullanıcı adına RLS'li işlem (user_tx)
│   │   ├── middleware.py    istek kimliği, JSON log, güvenlik başlıkları, rate limit
│   │   ├── errors.py        DB kural ihlali → güvenli HTTP hatası
│   │   ├── api/             health, organizations, dashboard, approvals
│   │   ├── agents/          llm.py (Claude), registry.py (rol/araç), orchestrator.py (CEO akışı)
│   │   ├── dispatch.py      Celery veya süreç içi görev dağıtımı
│   │   ├── worker.py        Celery çalışanı
│   │   ├── integrations/    (P3/P4) youtube.py, etsy.py, printify.py
│   └── tests/               gerçek PostgreSQL üzerinde API + RLS + onay testleri
├── frontend/                Next.js 16 / TypeScript / Tailwind 4
│   ├── app/(app)/           dashboard, ai-employees, approvals, [section] (yapılmamış bölümler)
│   ├── app/login, onboarding
│   ├── components/, lib/
│   └── proxy.ts             oturum yenileme + giriş zorunluluğu
├── supabase/
│   ├── migrations/0001_core.sql   36 tablo, RLS, onay ve denetim kuralları
│   └── test/supabase_stub.sql     yalnızca yerel test için auth taklidi
├── docker-compose.yml       backend · frontend · redis
├── scripts/test.sh          tüm testler
└── docs/
```

## 3. Ajan organizasyonu

Ajan kadrosu organizasyon oluşturulduğunda veritabanında kurulur (`app.create_organization`):

| Departman | Ajanlar |
|---|---|
| Yönetim | CEO Agent |
| YouTube (7) | Trend Research, Channel Strategist, Script Writer, Video Production, Thumbnail Designer, YouTube SEO, YouTube Analytics |
| Etsy (8) | Product Research, Competitor Analysis, Design, Etsy SEO, Listing Manager, Printify, Profit Analyst, Sales Analyst |
| Kalite Kontrol (5) | Content Quality, Copyright Compliance, SEO Quality, Financial Verification, Technical Testing |

Her ajanın talimatları sürümlüdür (`agent_instructions`) ve `allowed_tools` ile en az yetki
uygulanır. Ajanlar API'ye doğrudan yazamaz; yalnızca okuma araçları ve "onay iste" aracı alır.

### Görev akışı (P2)
1. Kullanıcı komutu → `tasks` (CEO).
2. CEO, Claude API ile planı `task_steps` olarak çıkarır ve alt ajanlara atar.
3. Her adım Celery'de çalışır; her çağrı `agent_runs` (model, token, maliyet) olarak kaydedilir.
4. Çıktı ilgili QC ajanına gider (`waiting_qc`). Hata varsa adım geri gönderilir.
5. Kritik işlem gerekiyorsa `approvals` kaydı açılır (`waiting_approval`).
6. CEO sonuçları tek rapor olarak birleştirir.

### Uygulanan ayrıntılar (P2)
* Model: `claude-opus-5-5` (`BC_LLM_MODEL`). CEO planı yapılandırılmış çıktıyla (JSON şema) alınır;
  plandaki bilinmeyen ajan kodları atılır, en fazla 8 adım.
* Araştırma ajanları Anthropic web arama aracını kullanır (çağrı başına en fazla 5 arama); kaynak
  bağlantıları adım çıktısına kaydedilir.
* Güvenlik sınıflandırıcısı reddederse sunucu tarafı yedek model (`fallbacks: "default"`) devreye girer;
  yine reddedilirse görev açık bir mesajla başarısız olur.
* Maliyet: her çağrının token ve tahmini USD maliyeti `agent_runs` tablosuna yazılır. Görev
  `BC_MAX_TASK_COST_USD` üst sınırını aşarsa durdurulur. Organizasyon başına eşzamanlı görev sınırı vardır.
* İptal: her adım öncesi kontrol edilir. Hata olursa adım `failed`, kalanlar `skipped` olur.

Harici içerik (web sayfaları, rakip listelemeleri, yorumlar) **güvenilmeyen veri** olarak ayrı
bir blokta modele verilir. Talimat olarak yorumlanmaz ve araç yetkisini genişletemez.

## 4. Onay sistemi (P1'de çalışıyor)

* `approvals` tablosuna istemci rolü yazamaz. Karar yalnızca `app.decide_approval()` ile verilir.
* Geçişler veritabanı tetikleyicisiyle sınırlıdır: `pending → approved | rejected | expired`,
  `approved → executed | failed`. Başka geçiş yoktur.
* `payload`, `after_state`, `action` sonradan değiştirilemez.
* Süresi dolan onay onaylanamaz. `app.expire_approvals()` bunları `expired` yapar. Varsayılan onay yoktur.
* Ret için neden zorunludur. Her geçiş `approval_history` tablosuna, her karar `audit_logs` tablosuna yazılır.
* `audit_logs` yalnızca eklemeye açıktır: güncelleme ve silme tetikleyiciyle engellenir.

## 5. Güvenlik

| Konu | Uygulama |
|---|---|
| Kimlik | Supabase Auth. Backend her istekte JWT imzası, `aud`, `exp` ve `role` değerlerini doğrular. |
| Yetki | Backend sorguları `authenticated` rolünde, kullanıcının iddialarıyla çalışır, böylece RLS aynen uygulanır. |
| Kiracı ayrımı | Tüm tablolarda `organization_id` + RLS (üye okur, owner/admin yazar). |
| Tokenlar | `oauth_tokens` istemci rollerine tamamen kapalı. Şifreli (`*_enc`, anahtar sürümlü). |
| Gizli bilgiler | Yalnızca ortam değişkenleri. Frontend'e sadece `NEXT_PUBLIC_*` herkese açık değerler gider. |
| CSRF | API çerez değil Bearer token kullanır. CORS yalnızca tanımlı kökenlere açık. |
| XSS | React kaçışlaması, `dangerouslySetInnerHTML` yok, CSP ve güvenlik başlıkları. |
| Rate limit | IP başına dakikalık sınır; Redis varsa tüm kopyalar arasında ortak, Redis erişilemezse hizmet kesilmez. |
| Prompt injection | Harici veri ayrı blokta, ajanlarda en az araç yetkisi, kritik işlemler onay kapısında. |

## 6. Entegrasyon gerçekleri (bağlamadan önce doğrulanacak)

* **YouTube Data API:** Denetimden (audit) geçmemiş API projeleriyle yüklenen videolar
  *private* olarak kilitlenir. Herkese açık yükleme için Google'a denetim başvurusu gerekir.
  Günlük kota sınırlıdır: yükleme çok kota harcar. Kota sayacı tutulacak.
* **Etsy Open API v3:** Uygulama anahtarı Etsy'den onay ister. Kişisel erişim kendi mağazanızla
  sınırlıdır. Desteklenmeyen uç noktalar için otomasyon varmış gibi davranılmayacak.
* **Printify:** Kendi hesabınız için Personal Access Token ile bağlanılır. Çok kullanıcılı
  dağıtım için Printify OAuth uygulama onayı gerekir.
* **Claude API:** Ajan çalıştırmaları için Anthropic API anahtarı gerekir. Maliyet `agent_runs` tablosuna yazılır.

## 7. Yol haritası ve durum

Sıra kararı: dış platform bağlantıları (YouTube, Etsy, Printify OAuth ve senkronları) en sona bırakıldı.

| Faz | Kapsam | Durum |
|---|---|---|
| **P1 Foundation** | Klasör yapısı, şema + RLS, backend, frontend, auth, dashboard, onay çekirdeği, Docker, CI | ✅ Kod + testler hazır. Supabase projesi bağlanmadı, Docker yerelde çalıştırılamadı |
| **P2 AI Core** | CEO, registry, Claude API, görev kuyruğu (Celery/Redis), ajan logları, CEO Komut Merkezi | ✅ Kod + testler (sahte model ile) hazır; gerçek Claude çağrısı API anahtarı bekliyor |
| **P3 YouTube (bağlantı)** | Google OAuth + PKCE, kanal, son videolar, 90 günlük analitik, tahmini gelir → finans | ✅ Sahte API ile test edildi; gerçek hesapla denenmedi |
| P3 YouTube | OAuth, kanal senkronu, trend, senaryo, üretim iş akışı, thumbnail, SEO, yayın onayı, analytics | ⏳ |
| **Finans motoru** | Kâr-zarar, manuel kayıt, doğrulanmış rapor | ✅ (P4'ün entegrasyondan bağımsız kısmı) |
| **P4 Etsy + Printify (bağlantı)** | Etsy OAuth + PKCE, listeleme ve sipariş senkronu → gelir; Printify token, ürün/maliyet senkronu | ✅ Sahte API ile test edildi; gerçek hesapla denenmedi |
| P4 Etsy | OAuth, Printify, araştırma, tasarım, SEO, listeleme, siparişler, finans, yayın onayı | ⏳ |
| **P5 Kalite Kontrol** | QC ajanları, telif riski, finansal doğrulama, test otomasyonu | ✅ QC döngüsü (kalırsa 1 düzeltme), telif riskinde insan incelemesi, CI |
| **P6 Otomasyon** | Zamanlanmış görevler, günlük/haftalık/aylık raporlar, bildirimler | ✅ Cron kuralları (10 şablon, varsayılan kapalı), Celery beat, onay süre aşımı, bildirimler |
| **P7 Production** | Performans, güvenlik testi, yedekleme, izleme, dağıtım, dokümantasyon | ✅ Production ayar denetimi, takılı görev temizleyici, beat servisi, Caddy (HTTPS), yedek betiği, [DEPLOYMENT.md](DEPLOYMENT.md). Gerçek sunucuda denenmedi |

### Kalite kontrol akışı (P5)
QC ajanları yapılandırılmış karar döndürür: `verdict` (pass/fail), `issues`, `needs_human_review`.
Kalırsa önceki üretici ajan sorunlarla birlikte bir kez yeniden çalıştırılır ve QC tekrarlanır. Yine
kalırsa görev tamamlanır ama `qc_passed=false` olarak işaretlenir; sonuç gizlenmez. Telif ajanı
kalırsa her zaman insan incelemesi istenir.

### Otomasyon (P6)
`automation_rules` cron + saat dilimi ile çalışır. Celery beat her dakika `tick` çalıştırır: süresi
dolan onayları kapatır (`expired`) ve vadesi gelen kuralları görev olarak başlatır. Eşzamanlı görev
sınırı doluysa çalıştırma atlanır ve bildirim gönderilir. Kurallar kapalı oluşturulur, çünkü her
çalıştırma ücretli model çağrısı yapar.

### Finans (P4 çekirdeği)
`finance.py` saf fonksiyonlarla hesaplar. Para birimleri birleştirilmez, vergi ayrı raporlanır.
Eksik veri (Etsy ücretleri, Printify maliyeti, çoklu para birimi) listelenir. Kayıtlı rapor
yalnızca eksik veri yoksa `verified=true` olur ve dashboard yalnızca doğrulanmış kârı gösterir.

### Onaylı yazma işlemleri
Desteklenen otomatik işlemler: `etsy.listing.update`, `youtube.video.update_metadata` (başlık, açıklama, etiket) ve `etsy.listing.create_draft` (yalnızca taslak; yayına alma ve fotoğraf Etsy panelinden).
Akış: öneri (`POST /organizations/{id}/approvals`; "öncesi" veritabanından okunur) → kullanıcı onayı → `Executor`.
Executor çağrıdan önce şunları yeniden doğrular: durum, payload parmak izi, işlem şeması, entegrasyonun yazma izni
(`listings_w` / `youtube.force-ssl`), hedefin organizasyona ait olması. Sonuç `executed`/`failed` olarak, nedeniyle
birlikte kaydedilir. Yürütücüsü olmayan işlemler (ör. fiyat değişikliği) onaylansa da otomatik uygulanmaz; elle yapılır.
Yazma izni varsayılan olarak istenmez; "Yazma izniyle yeniden bağlan" ile ayrıca verilir.
