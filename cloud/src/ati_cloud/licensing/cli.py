"""``ati-cloud-license``: lisans gizli değerleri ve elle lisans üretimi (operasyon aracı).

Admin paneli (Aşama 16) aynı servisi kullanır; bu araç yayına alma hazırlığı, destek ve
testler içindir. Üretilen anahtarlar yalnızca bir kez ekrana yazılır.

    uv run ati-cloud-license gen-secrets           # yeni pepper, KEK ve kira imza anahtarı
    uv run ati-cloud-license public-key            # motor sürümüne gömülecek açık anahtar
    uv run ati-cloud-license issue --plan d30_1dev --email musteri@ornek.com
    uv run ati-cloud-license issue --plan d30_1dev --count 100   # satış havuzu
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import secrets
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ati_cloud.accounts import Database
from ati_cloud.config import CloudSettings
from ati_cloud.licensing.lease import key_id
from ati_cloud.licensing.service import LicenseError, Licensing


def _gen_secrets() -> int:
    signing = Ed25519PrivateKey.generate()
    raw = signing.private_bytes_raw()
    public = signing.public_key().public_bytes_raw()
    print("# Gizli bilgi deposuna ekleyin (depoya veya imaja YAZMAYIN):")
    print(f"ATI_LICENSE_PEPPER={base64.b64encode(secrets.token_bytes(32)).decode()}")
    print(f"ATI_LICENSE_KEK={base64.b64encode(secrets.token_bytes(32)).decode()}")
    print(f"ATI_LEASE_SIGNING_KEY={base64.b64encode(raw).decode()}")
    print("# Motor sürümüne gömülecek açık anahtar (gizli değildir):")
    print(f"# kid={key_id(public)} public_key={base64.b64encode(public).decode()}")
    return 0


async def _issue(plan: str, email: str | None, count: int) -> int:
    settings = CloudSettings()
    licensing = Licensing.from_settings(settings)
    if licensing is None:
        print("Lisans gizli değerleri tanımlı değil (gen-secrets)", file=sys.stderr)
        return 2
    db = Database(settings.database_dsn)
    try:
        async with db.connection() as conn:
            customer_id = None
            if email:
                cur = await conn.execute(
                    "SELECT id FROM customers WHERE email = %s AND status = 'active'",
                    (email.strip().lower(),),
                )
                row = await cur.fetchone()
                if row is None:
                    print(f"Müşteri bulunamadı: {email}", file=sys.stderr)
                    return 1
                customer_id = row["id"]
            await conn.execute("SELECT set_config('ati.actor_type', 'system', false)")
            await conn.execute("SELECT set_config('ati.actor_id', 'ati-cloud-license', false)")
            for _ in range(count):
                license_id, key = await licensing.issue(
                    conn, plan_code=plan, customer_id=customer_id
                )
                print(f"{license_id}\t{key}")
    except LicenseError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    finally:
        await db.close()
    return 0


def _public_key() -> int:
    licensing = Licensing.from_settings(CloudSettings())
    if licensing is None:
        print("ATI_LEASE_SIGNING_KEY tanımlı değil", file=sys.stderr)
        return 2
    print(f"kid={licensing.signer.kid}")
    print(f"public_key={base64.b64encode(licensing.signer.public_raw).decode()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ati-cloud-license")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("gen-secrets", help="Yeni gizli değerler üret")
    sub.add_parser("public-key", help="Kira imza açık anahtarını göster")
    issue = sub.add_parser("issue", help="Lisans üret")
    issue.add_argument("--plan", required=True)
    issue.add_argument("--email", help="Doğrudan bu müşteriye sat (yoksa satış havuzu)")
    issue.add_argument("--count", type=int, default=1, choices=range(1, 1001), metavar="1-1000")
    args = parser.parse_args(argv)
    if args.command == "gen-secrets":
        return _gen_secrets()
    if args.command == "public-key":
        return _public_key()
    return asyncio.run(_issue(args.plan, args.email, args.count))


if __name__ == "__main__":
    raise SystemExit(main())
