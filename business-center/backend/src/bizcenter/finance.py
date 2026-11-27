"""Finans motoru: kayıtlardan kâr-zarar hesaplar. Eksik veri varsa rapor 'doğrulanmamış' olur.

Net Kâr = Tahsil Edilen Gelir - Üretim/Ürün Maliyetleri - Platform Ücretleri - Reklam - Diğer Giderler
(iade ve indirimler gelirden düşülür). Vergi ayrı raporlanır, net kârdan uydurularak düşülmez.
Para birimleri asla birbirine eklenmez; her para birimi için ayrı hesap yapılır.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import AsyncConnection

EXPENSE_GROUPS = {
    "production": {"printify_production", "production", "materials", "printify"},
    "shipping": {"shipping", "printify_shipping"},
    "advertising": {"ads", "advertising", "etsy_ads", "youtube_ads"},
    "voiceover": {"voiceover"},
    "software_ai": {"software", "ai", "anthropic"},
}


def _group(category: str) -> str:
    c = category.lower()
    return next((g for g, cats in EXPENSE_GROUPS.items() if c in cats), "other")


def compute_pnl(scope: str, revenues: list[dict[str, Any]], records: list[dict[str, Any]],
                expenses: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """scope: youtube | etsy | combined. Dönüş: para birimi -> rakamlar."""
    def inc(d: str | None) -> bool:
        return scope == "combined" or d == scope or (d == "shared" and scope == "combined")

    out: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for r in revenues:
        if inc(r["department"]):
            out[r["currency"]]["gross_revenue"] += Decimal(r["amount"])
    for r in records:
        if inc(r["department"]):
            out[r["currency"]][r["kind"]] += abs(Decimal(r["amount"]))
    for e in expenses:
        if inc(e["department"]):
            out[e["currency"]]["expense_" + _group(e["category"])] += Decimal(e["amount"])

    result: dict[str, dict[str, Any]] = {}
    for cur, f in out.items():
        collected = f["gross_revenue"] - f["refund"] - f["discount"]
        costs = sum((v for k, v in f.items() if k.startswith("expense_")), Decimal(0))
        net = collected - f["fee"] - costs
        result[cur] = {k: str(v) for k, v in sorted(f.items())} | {
            "collected_revenue": str(collected), "platform_fees": str(f["fee"]),
            "total_costs": str(costs), "net_profit": str(net),
            "tax_reported_separately": str(f["tax"]),
            "margin_pct": str((net / collected * 100).quantize(Decimal("0.01"))) if collected else None,
        }
    return result


def missing_data(scope: str, revenues: list[dict[str, Any]], records: list[dict[str, Any]],
                 expenses: list[dict[str, Any]]) -> list[str]:
    miss: list[str] = []
    if scope != "combined":
        revenues = [r for r in revenues if r["department"] == scope]
        expenses = [e for e in expenses if e["department"] in (scope, None)]
    deps = {r["department"] for r in revenues}
    if scope in ("etsy", "combined") and "etsy" in deps:
        if not any(r["department"] == "etsy" and r["kind"] == "fee" for r in records):
            miss.append("Etsy işlem/listeleme/ödeme ücretleri kayıtlı değil")
        if not any(e["department"] == "etsy" and _group(e["category"]) == "production" for e in expenses):
            miss.append("Printify üretim maliyetleri kayıtlı değil")
    if not revenues:
        miss.append("Dönem için gelir kaydı yok")
    currencies = {r["currency"] for r in revenues} | {e["currency"] for e in expenses}
    if len(currencies) > 1:
        miss.append("Birden fazla para birimi var; kur dönüşümü yapılmadı, her para birimi ayrı raporlandı")
    return miss


async def load_period(conn: AsyncConnection, org: Any, start: date, end: date) -> tuple[list, list, list]:
    q = ("select department, {cols}, amount, currency from {t}"
         " where organization_id=%s and occurred_on between %s and %s")
    rev = await (await conn.execute(q.format(cols="category", t="revenue_records"), (org, start, end))).fetchall()
    rec = await (await conn.execute(q.format(cols="kind", t="financial_records"), (org, start, end))).fetchall()
    exp = await (await conn.execute(q.format(cols="category", t="expenses"), (org, start, end))).fetchall()
    return rev, rec, exp
