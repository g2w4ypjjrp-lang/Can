"""``ati-cloud-payments``: ödeme bakımı (zamanlanmış görev olarak çalıştırılır).

    uv run ati-cloud-payments maintain --reconcile-minutes 10 --expire-hours 24

* Tarayıcısı geri dönmemiş iyzico ödemelerinin sonucu sağlayıcıdan sorgulanır (imzalı istek).
  PayTR sonucu sunucudan sunucuya bildirimle gelir ve sağlayıcı yanıt alana kadar yeniden dener.
* Süresi geçmiş ödenmemiş siparişler iptal edilir (geç gelen başarılı ödeme yine işlenir).
"""

from __future__ import annotations

import argparse
import asyncio

from ati_cloud.accounts import Database
from ati_cloud.admin.context import AdminContext
from ati_cloud.config import CloudSettings
from ati_cloud.licensing.service import Licensing
from ati_cloud.payments.service import Payments


async def _maintain(reconcile_minutes: int, expire_hours: int) -> int:
    settings = CloudSettings()
    db = Database(settings.database_dsn)
    licensing = Licensing.from_settings(settings)
    payments = Payments.build(
        settings, db, licensing, AdminContext.build(settings, db, licensing).box
    )
    try:
        settled = await payments.reconcile_pending(reconcile_minutes)
        expired = await payments.expire_pending(expire_hours)
    finally:
        await db.close()
    print(f"sonuçlanan: {settled}, iptal edilen: {expired}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ati-cloud-payments")
    sub = parser.add_subparsers(dest="command", required=True)
    maintain = sub.add_parser("maintain", help="Bekleyen ödemeleri sorgula, eskileri iptal et")
    maintain.add_argument("--reconcile-minutes", type=int, default=10)
    maintain.add_argument("--expire-hours", type=int, default=24)
    args = parser.parse_args(argv)
    return asyncio.run(_maintain(args.reconcile_minutes, args.expire_hours))


if __name__ == "__main__":
    raise SystemExit(main())
