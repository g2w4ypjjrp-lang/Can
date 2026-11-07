"""Komut satırı girişi.

Kullanım::

    ati-engine run                     # motoru başlat (varsayılan)
    ati-engine show-config             # etkin ayarları göster (gizli bilgi içermez)
    ati-engine export-protocol-schema  # paylaşılan protokol şemasını yazdır
    ati-engine verify-audit            # yerel denetim kaydı zincirini doğrula
    ati-engine version
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from ati_engine import __version__


def _cmd_run(args: argparse.Namespace) -> int:
    from ati_engine.app import Engine
    from ati_engine.config import EngineSettings
    from ati_engine.system.single_instance import AlreadyRunningError

    overrides: dict[str, object] = {}
    if args.data_dir:
        overrides["data_dir"] = Path(args.data_dir)
    settings = EngineSettings(**overrides)  # type: ignore[arg-type]
    if args.port is not None:
        settings.api.port = args.port
    try:
        return asyncio.run(Engine(settings).run())
    except AlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def _cmd_show_config(args: argparse.Namespace) -> int:
    from ati_engine.config import EngineSettings, redacted_settings_dump

    overrides: dict[str, object] = {}
    if args.data_dir:
        overrides["data_dir"] = Path(args.data_dir)
    settings = EngineSettings(**overrides)  # type: ignore[arg-type]
    print(json.dumps(redacted_settings_dump(settings), indent=2, ensure_ascii=False))
    return 0


def _cmd_export_schema(args: argparse.Namespace) -> int:
    from ati_engine.protocol import build_protocol_schema

    text = json.dumps(build_protocol_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def _cmd_verify_audit(args: argparse.Namespace) -> int:
    from ati_engine.config import EngineSettings
    from ati_engine.storage.audit import AuditLog
    from ati_engine.storage.database import Database

    overrides: dict[str, object] = {}
    if args.data_dir:
        overrides["data_dir"] = Path(args.data_dir)
    settings = EngineSettings(**overrides)  # type: ignore[arg-type]

    async def _verify() -> int:
        db = Database(settings.paths.database)
        await db.open()
        try:
            await db.migrate()
            result = await AuditLog(db).verify()
        finally:
            await db.close()
        if result.ok:
            print(f"Denetim kaydı sağlam ({result.checked} kayıt).")
            return 0
        print(
            f"Denetim kaydı zinciri {result.broken_at_id} numaralı kayıtta kırık!", file=sys.stderr
        )
        return 3

    return asyncio.run(_verify())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ati-engine", description="AI Trading Intelligence motoru"
    )
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Motoru başlat")
    run.add_argument("--data-dir", help="Veri dizini (varsayılan: işletim sistemine göre)")
    run.add_argument("--port", type=int, help="Yerel API portu (0 = otomatik)")
    run.set_defaults(func=_cmd_run)

    show = sub.add_parser("show-config", help="Etkin ayarları göster")
    show.add_argument("--data-dir")
    show.set_defaults(func=_cmd_show_config)

    export = sub.add_parser("export-protocol-schema", help="Protokol JSON şemasını üret")
    export.add_argument("--output", help="Çıktı dosyası (varsayılan: stdout)")
    export.set_defaults(func=_cmd_export_schema)

    verify = sub.add_parser("verify-audit", help="Denetim kaydı zincirini doğrula")
    verify.add_argument("--data-dir")
    verify.set_defaults(func=_cmd_verify_audit)

    version = sub.add_parser("version", help="Sürümü yazdır")
    version.set_defaults(func=lambda _: print(__version__) or 0)
    return parser


def _force_utf8_stdio() -> None:
    """Windows konsolu/borusu varsayılan olarak cp1252 gibi kod sayfaları kullanır ve
    Türkçe karakterlerde (ı, ş, ğ) ``UnicodeEncodeError`` ile çöker. Çıktı ve loglar
    her zaman UTF-8 yazılır; kodlanamayan karakter çökme yerine değiştirilir."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["run", *(argv or [])])
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
