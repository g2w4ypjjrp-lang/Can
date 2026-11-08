# ati-cloud — Lisans, Hesap, Ödeme ve Aktarma Servisi

Yönetilen bulut altyapısında (kiralık VDS değil) çalışan FastAPI servisi. İşlem motoru
**burada çalışmaz**; motor kullanıcının Windows bilgisayarındadır. Bu servis yalnızca
hesapları, lisansları, cihaz aktivasyonlarını, ödemeleri ve iOS ↔ masaüstü aktarmasını
yönetir. Mimari: [`../docs/01-sistem-mimarisi.md`](../docs/01-sistem-mimarisi.md),
şema: [`../docs/04-veritabani-semasi.md`](../docs/04-veritabani-semasi.md).

## Geliştirme

```bash
cd cloud
uv sync
# Testler gerçek bir PostgreSQL 16 ister:
export ATI_TEST_DATABASE_URL=postgresql://ati_test:ati_test@127.0.0.1:5432/ati_test
uv run pytest
uv run ruff check . && uv run mypy
```

## Geçişler (migrations)

```bash
export ATI_DATABASE_URL=postgresql://...
uv run ati-cloud-migrate          # bekleyen geçişleri uygular
uv run ati-cloud-migrate --check  # yalnızca durumu raporlar
```

Geçişler `src/ati_cloud/db/migrations/NNNN_ad.sql` dosyalarıdır. Uygulanmış bir geçiş
dosyası değiştirilirse (özet uyuşmazlığı) çalıştırıcı hata verir. Aynı anda birden fazla
örnek açılırsa PostgreSQL advisory lock ile yalnızca biri geçiş uygular.

## Aktarma servisi (Aşama 13)

iOS ↔ masaüstü motoru arasında uçtan uca imzalı mesajları yönlendirir
([protokol](../shared/protocol/remote-v1.md)). Servis hiçbir anahtar tutmaz ve içerikleri
yorumlamaz. Ele geçirilse bile komut üretemez, durum sahteleyemez, cihaz eşleştiremez.
Ayrı bir süreç olarak çalışır:

```bash
uv run ati-cloud-relay --host 0.0.0.0 --port 8765   # TLS (wss://) önündeki yük dengeleyicide
```

Uç noktalar `/v1/relay/engine` ve `/v1/relay/device`. Bağlanan taraf kimliğini imzalı `hello`
ile kanıtlar. Hız sınırı ve motor başına 20 telefon sınırı vardır. Tek örnek durumu bellektedir;
birden çok örnek için Redis pub/sub dağıtım aşamasında (G5) eklenecek.
