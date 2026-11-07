# ati-engine — Yerel İşlem Motoru

AI Trading Intelligence'ın kullanıcının Windows bilgisayarında çalışan işlem motoru.
Mimari için bkz. [`../docs/01-sistem-mimarisi.md`](../docs/01-sistem-mimarisi.md).

## Geliştirme

```bash
cd engine
uv sync                      # bağımlılıklar + geliştirme araçları
uv run pytest                # testler
uv run ruff check . && uv run ruff format --check .
uv run mypy                  # sıkı tip denetimi
```

## Çalıştırma

```bash
uv run ati-engine run --data-dir ./.data --port 0
uv run ati-engine show-config
uv run ati-engine verify-audit --data-dir ./.data
uv run ati-engine export-protocol-schema --output ../shared/protocol/engine-local-api.schema.json
```

Motor her zaman **PAPER (sanal işlem)** modunda başlar. Bu sürümde (Aşama 1) gerçek emir
yürütme modülü bulunmadığından LIVE moduna geçiş teknik olarak engellenmiştir.

Yerel API yalnızca `127.0.0.1` üzerinde açılır. Belirteç, masaüstü uygulaması tarafından
`ATI_LOCAL_API_TOKEN` ortam değişkeniyle verilir; verilmezse motor rastgele bir belirteç
üretip `runtime/local-api.json` dosyasına (yalnızca kullanıcı okuyabilir) yazar.
