"""Hesap/lisans API sunucusu: ``ati-cloud-api``.

Üretimde TLS sonlandıran yük dengeleyicinin arkasında çalışır. İstemci adresi yalnızca
``ATI_TRUSTED_PROXIES`` içindeki vekillerden gelen ``X-Forwarded-For`` ile çözülür (hız sınırı
ve denetim kaydı için).
"""

from __future__ import annotations

import argparse

import uvicorn

from ati_cloud.app import create_app
from ati_cloud.config import CloudSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ati-cloud-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    settings = CloudSettings()
    uvicorn.run(
        create_app(settings),
        host=args.host,
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.trusted_proxies,
        server_header=False,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
