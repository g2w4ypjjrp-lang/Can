"""``ati-cloud-admin``: ilk süper yöneticiyi davet etme ve 2FA kurtarma (operasyon aracı).

    uv run ati-cloud-admin invite --email yonetici@canarslan.net.tr --name "Ad Soyad"
    uv run ati-cloud-admin invite --email destek@... --name "..." --role support

Davet bağlantısı yalnızca bir kez yazılır, 72 saat geçerlidir; açan kişi parolasını ve
doğrulama uygulamasını (TOTP) kurar. Diğer yöneticiler panelden davet edilir.
"""

from __future__ import annotations

import argparse
import sys

from ati_cloud.accounts import Database
from ati_cloud.admin.admins import create_invited_admin
from ati_cloud.admin.auth import issue_invite
from ati_cloud.config import CloudSettings
from ati_cloud.loop import run


async def _invite(email: str, name: str, roles: list[str]) -> int:
    settings = CloudSettings()
    db = Database(settings.database_dsn)
    try:
        async with db.connection() as conn:
            await conn.execute("SELECT set_config('ati.actor_type', 'system', false)")
            cur = await conn.execute(
                "SELECT id, status::text FROM admin_users WHERE email = %s", (email.lower(),)
            )
            existing = await cur.fetchone()
            if existing is not None:
                if existing["status"] != "invited":
                    print(
                        "Bu yönetici zaten etkin; 2FA sıfırlaması panelden yapılır.",
                        file=sys.stderr,
                    )
                    return 1
                token = await issue_invite(conn, existing["id"])
            else:
                _, token = await create_invited_admin(
                    conn, email=email, full_name=name, roles=roles, created_by=None
                )
            await conn.execute(
                "INSERT INTO audit_log (actor_type, actor_id, action, target_type, details) "
                "VALUES ('system', 'ati-cloud-admin', 'admin.admin_invited', 'admin', "
                "jsonb_build_object('email', %s::text, 'roles', %s::text[]))",
                (email.lower(), roles),
            )
    finally:
        await db.close()
    print(f"{settings.admin_public_url}/yonetim/davet?token={token}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ati-cloud-admin")
    sub = parser.add_subparsers(dest="command", required=True)
    invite = sub.add_parser("invite", help="Yönetici davet et (bağlantı bir kez yazılır)")
    invite.add_argument("--email", required=True)
    invite.add_argument("--name", required=True)
    invite.add_argument("--role", action="append", default=None, help="Varsayılan: super_admin")
    args = parser.parse_args(argv)
    return run(_invite(args.email, args.name, args.role or ["super_admin"]))


if __name__ == "__main__":
    raise SystemExit(main())
