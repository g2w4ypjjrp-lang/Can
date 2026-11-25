-- =============================================================================
-- 0012 Indexes for foreign keys used in joins / cascades.
-- FKs referencing users (actor columns) and approval requests are lookup-only
-- and intentionally left unindexed.
-- =============================================================================
create index ad_accounts_connected_account_idx on public.ad_accounts (connected_account_id);
create index ad_spend_campaign_idx on public.ad_spend (campaign_id);
create index ai_decisions_ai_task_idx on public.ai_decisions (ai_task_id);
create index competitor_research_market_research_idx on public.competitor_research (market_research_id);
create index customer_messages_customer_idx on public.customer_messages (customer_id);
create index customer_messages_order_idx on public.customer_messages (order_id);
create index market_research_ai_task_idx on public.market_research (ai_task_id);
create index notifications_store_idx on public.notifications (store_id);
create index order_items_listing_idx on public.order_items (listing_id);
create index orders_customer_idx on public.orders (customer_id);
create index price_recommendations_variant_idx on public.price_recommendations (product_variant_id);
create index price_recommendations_listing_idx on public.price_recommendations (listing_id);
create index product_opportunities_market_research_idx on public.product_opportunities (market_research_id);
create index products_design_idx on public.products (design_id);
create index profit_snapshots_order_idx on public.profit_snapshots (order_id);
create index profit_snapshots_listing_idx on public.profit_snapshots (listing_id);
