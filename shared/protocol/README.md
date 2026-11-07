# Paylaşılan Protokol

`engine-local-api.schema.json`, motorun yerel API'sinin (REST istek/yanıt modelleri ve
WebSocket olay akışı) JSON Schema tanımıdır. Masaüstü (TypeScript) ve iOS (Swift)
istemcileri tiplerini bu dosyadan üretir.

Dosya elle düzenlenmez; koddan üretilir:

```bash
cd engine
uv run ati-engine export-protocol-schema --output ../shared/protocol/engine-local-api.schema.json
```

`engine/tests/test_protocol_schema.py`, depodaki dosyanın koddan üretilenle aynı olduğunu
CI'da doğrular.

WebSocket akışı: istemci `/v1/events` adresine bağlanır, 5 saniye içinde
`{"type":"auth","token":"..."}` gönderir, `{"type":"auth_ok"}` alır; ardından her olay
`type` alanıyla etiketlenmiş JSON nesnesi olarak gelir (`EngineEvent` birleşimi).
