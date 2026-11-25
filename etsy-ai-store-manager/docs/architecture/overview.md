# Mimari

## 1. Genel bakış

Etsy AI Store Manager bir **modüler monolit**tir: tek bir NestJS API'si (modüllere ayrılmış),
ayrı bir **BullMQ worker** süreci ve Next.js yönetim paneli. Veri, kimlik doğrulama ve dosyalar
Supabase'tedir (PostgreSQL + Auth + Storage). Arka plan işleri Redis üzerinden kuyruğa alınır.

```
 Tarayıcı (PWA)                      VPS (Docker Compose)                          Supabase
 ┌───────────────┐  HTTPS  ┌──────────────────────────────────────────┐   ┌─────────────────────┐
 │ Next.js panel │────────▶│ Nginx ─┬─▶ web (Next.js, SSR)            │   │ Auth (JWT, ES256)    │
 └───────────────┘         │        │      │ Bearer (kullanıcı JWT)   │   │ PostgreSQL + RLS     │
        │                  │        └─▶ api (NestJS) ─────────────────┼──▶│ Storage (private)    │
        │ Supabase Auth    │               │  ▲   SET ROLE authenticated   └─────────────────────┘
        └─────────────────▶│               ▼  │   + request.jwt.claims
                           │            Redis ◀── worker (BullMQ) ─────▶ Etsy / Printify / Claude /
                           └──────────────────────────────────────────┘   reklam API'leri (sonraki fazlar)
```

## 2. Bileşenler

| Katman         | Klasör                   | Sorumluluk                                                                            |
| -------------- | ------------------------ | ------------------------------------------------------------------------------------- |
| Web            | `apps/web`               | Next.js 16 App Router, Tailwind 4, Supabase SSR oturumu, server actions, PWA          |
| API            | `apps/api`               | NestJS 12 REST, Swagger, JWT doğrulama, RLS'li DB erişimi, audit, rate limit          |
| Worker         | `apps/worker`            | BullMQ zamanlanmış/arka plan işleri, retry + idempotency                              |
| Paylaşılan     | `packages/shared`        | Zod şemaları (API ve web aynı doğrulamayı kullanır), DTO tipleri, kuyruk adları, menü |
| Veritabanı     | `packages/database`      | Supabase migration'ları, Supabase CLI config, test shim                               |
| Profit Engine  | `packages/profit-engine` | FAZ 4 — Decimal tabanlı bağımsız finans motoru                                        |
| AI Engine      | `packages/ai-engine`     | FAZ 5/10 — Claude orkestrasyonu, tool calling, structured output                      |
| Entegrasyonlar | `packages/integrations`  | FAZ 2/3/8 — Etsy, Printify, reklam API istemcileri                                    |

## 3. Güvenlik modeli

1. **Kimlik:** Supabase Auth. API her istekte erişim belirtecini doğrular (asimetrik anahtarlar için
   JWKS, eski projeler için HS256). `role=authenticated`, `iss`, `aud`, `exp` zorunlu.
2. **Yetki — iki katman:**
   - API, kullanıcı isteklerindeki tüm sorguları bir transaction içinde
     `SET LOCAL ROLE authenticated` + `request.jwt.claims` ile çalıştırır. Böylece **RLS politikaları
     API'den gelen sorgularda da uygulanır** (yalnızca Supabase Data API'de değil).
   - RLS: mağaza üyeliği (`store_members`, roller owner/admin/analyst/viewer) üzerinden
     `private.has_store_role()` güvenlik tanımlı fonksiyonu. anon rolüne hiçbir tablo açık değil.
3. **Sırlar:** OAuth belirteçleri `oauth_tokens` tablosunda AES-256-GCM ile şifreli; şifreli metin
   bağlı hesap kimliğine (AAD) bağlı. Bu tabloya istemci rolleri hiçbir koşulda erişemez.
   API anahtarları yalnızca sunucu `.env`'inde.
4. **Denetim:** `audit_logs` yalnızca ekleme (append-only, trigger ile güncelleme/silme engelli);
   her ayar değişikliğinde önce/sonra değerleri, IP, user-agent ve request id kaydedilir.
5. **Sınırlama:** API'de kullanıcı başı dakikalık limit (ThrottlerGuard), Nginx'te IP başı limit.
   Helmet güvenlik başlıkları, CORS beyaz listesi, 1 MB JSON gövde limiti, katı (strict) Zod şemaları
   (mass-assignment engeli), UUID doğrulama, iç hataların istemciye sızdırılmaması.
6. **Onay sistemi:** Gerçek dünyada yan etkisi olan her işlem `approval_requests` üzerinden geçer
   (ne/neden/fayda/maliyet/kâr etkisi/API işlemi alanları zorunlu). Yürütme FAZ 2+ ile eklenecek.

## 4. Veri ilkeleri

- Para: PostgreSQL `numeric`, servisler arası **ondalık string**, hesaplamada Decimal. Float yok
  (migration testi `real/double` sütunu olmadığını doğrular).
- Gerçek/demo ayrımı: `stores.data_origin` (`live`/`demo`) ve kayıt bazlı `data_origin`. Dashboard
  hiçbir zaman sentetik sayı üretmez; bağlı veri yoksa `dataOrigin: none` döner.
- Tahminler: pazar/rakip/anahtar kelime tablolarında `is_estimate` + `confidence` zorunlu alanlar.
- Reklam gideri: gerçek harcama **yalnızca** `ad_spend`'de; sipariş bazlı dağıtım
  `profit_snapshots.breakdown` içinde tutulur ve ikinci kez gider yazılmaz.
- Ücret kuralları (`fee_rules`): kaynak URL ve doğrulama zamanı zorunlu; doğrulanmamış oranlar
  hesaplamada kullanılmayacak (FAZ 4).

## 5. Arka plan işleri

- Kuyruklar: `maintenance`, `sync`, `ai`, `reports` (`packages/shared/src/queues.ts`).
- Her iş `runIdempotent()` ile çalışır: `automation_jobs.idempotency_key` benzersiz; başarılı bir anahtar
  tekrar çalışmaz, eşzamanlı kopyalar satır kilidi + kira (lease) ile engellenir, çöken worker'ın bıraktığı
  iş kira süresi sonunda yeniden alınır. BullMQ: 3 deneme, üstel geri çekilme.
- FAZ 1 işleri: `system.heartbeat` (uçtan uca sağlık), `system.cleanup-expired-approvals` (15 dk).

## 6. Ölçeklenme / SaaS yolu

- Tüm iş verisi `store_id` ile bölümlenmiş; çoklu mağaza ve çoklu kullanıcı (`store_members`) şimdiden destekli.
- API durumsuz; yatayda çoğaltılabilir. Worker eşzamanlılığı `WORKER_CONCURRENCY` ile ayarlanır.
- Faturalandırma/plan tabloları SaaS aşamasında eklenecek.
