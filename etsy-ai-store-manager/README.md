# Etsy AI Store Manager

Etsy mağazası ve Printify hesabı için AI destekli işletme yönetim platformu: pazar araştırması,
ürün keşfi, tasarım, Printify → Etsy ürün hazırlama, çok dilli SEO, reklam yönetimi, sipariş takibi
ve **ürün başına gerçek kâr (katkı)** hesabı. Kontrollü otomasyon: gerçek mağazada etkisi olan her
işlem onay ister.

> Bu klasör, depodaki diğer projeden (AI Trading Intelligence) bağımsızdır.

## Durum

| Faz  | Kapsam                                                                                | Durum                                                   |
| ---- | ------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| 1    | Monorepo, veritabanı (41 tablo + RLS), Auth, dashboard, ayarlar, worker, Docker/Nginx | ✅ Tamamlandı, test edildi                              |
| 2    | Etsy OAuth, mağaza verisi, ilanlar, onaylı ilan düzenleme                             | ✅ Test edildi (canlı doğrulama Etsy anahtarı bekliyor) |
| 3    | Printify                                                                              | ⬜ Printify token bekliyor                              |
| 4    | Profit Engine                                                                         | ⬜                                                      |
| 5–11 | Pazar araştırma, tasarım, SEO, reklam, sipariş, AI yönetici, production               | ⬜                                                      |

Ayrıntılı görev listesi ve API kısıtları: [docs/architecture/development-plan.md](docs/architecture/development-plan.md)

## Teknoloji

Next.js 16 · NestJS 12 · TypeScript (strict) · Tailwind CSS 4 · Supabase (PostgreSQL, Auth, Storage, RLS) ·
Redis + BullMQ · Docker Compose · Nginx · Vitest · Playwright

## Klasör yapısı

```
apps/web        Next.js yönetim paneli (PWA)
apps/api        NestJS REST API (Swagger: /docs)
apps/worker     BullMQ arka plan işleri
packages/shared         Zod şemaları, DTO tipleri, kuyruk adları (API + web ortak)
packages/database       Supabase migration'ları + CLI config
packages/{profit-engine,ai-engine,integrations,ui,config}   sonraki fazlar
infrastructure/{docker,nginx,scripts}   Dockerfile, Nginx, migrate/backup/restore
docs/{architecture,api,deployment,operations}
tests/{unit,integration,e2e}
```

## Yerel geliştirme

Gereken: Node 22, pnpm 10, Docker (Supabase CLI için), Redis.

```bash
pnpm install
npx supabase@2 start --workdir packages/database      # Postgres + Auth + Storage, migration'ları uygular
cp .env.example .env    # yerel değerler: supabase start çıktısındaki URL/anahtarlar
pnpm build:packages
pnpm dev:api            # http://localhost:4000/api/v1, Swagger: http://localhost:4000/docs
pnpm dev:worker
pnpm dev:web            # http://localhost:3000
```

Yerel API için `.env`: `DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres`,
`SUPABASE_URL=http://127.0.0.1:54321`, `SUPABASE_JWT_SECRET=` (boş: JWKS), `REDIS_URL=redis://localhost:6379`,
`TOKEN_ENCRYPTION_KEY=$(openssl rand -base64 32)`.

## Testler

```bash
pnpm lint && pnpm typecheck
pnpm test:unit                       # 76 test
TEST_DATABASE_URL=postgres://...test pnpm test:integration   # 68 test: migration, RLS, API, worker, Etsy akışı (gerçek Postgres + Redis)
pnpm --filter @esm/web build && E2E_SUPABASE_ANON_KEY=<publishable key> pnpm test:e2e   # 11 test: gerçek Supabase Auth + Etsy sözleşme test sunucusu
```

Entegrasyon testleri veritabanını sıfırlar; URL'de `test` geçmeyen bir veritabanında çalışmayı reddeder.

## Dağıtım

[docs/deployment/vps.md](docs/deployment/vps.md) · Operasyon: [docs/operations/runbook.md](docs/operations/runbook.md) ·
Mimari: [docs/architecture/overview.md](docs/architecture/overview.md)

## Güvenlik ilkeleri

- API anahtarları yalnızca sunucu `.env`'inde; `.env` Git'e girmez. OAuth belirteçleri AES-256-GCM ile şifreli.
- RLS her tabloda açık; API sorguları kullanıcının rolüyle (`authenticated` + JWT claims) çalışır.
- Audit log yalnızca ekleme yapılabilir. Rate limiting API ve Nginx'te.
- Demo veri gerçek veriyle karıştırılmaz; dashboard sentetik sayı üretmez.
