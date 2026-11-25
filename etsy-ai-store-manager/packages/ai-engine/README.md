# packages/ai-engine

Claude API orkestrasyonu (`@anthropic-ai/sdk`, model `claude-opus-5-5`).

- `market-research.ts` — FAZ 5: web araştırması (sunucu tarafı `web_search_20260209`, `pause_turn` yönetimi,
  reddedilme için sunucu tarafı yedek model) ve Zod şemasıyla doğrulanan yapılandırılmış pazar analizi.
- Her çağrının token kullanımı ve tahmini maliyeti `ai_tasks` tablosuna yazılır.
- Model asla satış rakamı uyduramaz; Etsy API'den gelmeyen her sinyal `isEstimate` olarak işaretlenir,
  kaynağı verilmeyen web atıfları "unverified" yapılır.
