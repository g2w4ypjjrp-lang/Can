-- Aşama 10: emir bağlantıları. Koşullu (algo) emir tetiklenince borsada oluşan gerçek emrin
-- kimliği ve OCO listesinin kimliği saklanır; motor yeniden başladığında dolumlar doğru
-- koruma emrine bağlanabilir.

ALTER TABLE orders ADD COLUMN actual_order_id TEXT;
ALTER TABLE orders ADD COLUMN list_id TEXT;
CREATE INDEX ix_orders_actual ON orders (mode, market, actual_order_id)
    WHERE actual_order_id IS NOT NULL;
