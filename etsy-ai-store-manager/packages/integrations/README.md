# packages/integrations

Resmî dış API istemcileri. Hem API hem worker tarafından kullanılır.

| Modül               | Durum                                                                                                              |
| ------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `etsy/`             | FAZ 2 — Etsy Open API v3: OAuth 2.0 + PKCE, token yenileme, hız limiti uyumlu istemci, Money dönüşümü, eşleyiciler |
| `crypto/`           | OAuth token şifreleme (AES-256-GCM, anahtar sürümlü, AAD)                                                          |
| Printify            | FAZ 3                                                                                                              |
| Reklam platformları | FAZ 8                                                                                                              |

Kaynak: https://developers.etsy.com/documentation/ ve resmî OpenAPI şeması
(`https://www.etsy.com/openapi/generated/oas/3.0.0.json`), 2026-11-25 tarihinde doğrulandı.
