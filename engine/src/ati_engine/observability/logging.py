"""Yapılandırılmış (JSON) loglama.

* Standart ``logging`` ve ``structlog`` aynı işlem hattından geçer.
* Her kayıt maskeleme işlemcisinden geçer: API anahtarı, imza, belirteç gibi değerler
  ``***`` ile değiştirilir (bkz. ``security.redaction``).
* Dosya logları döner (rotating): 10 MB x 10 dosya.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import structlog
from structlog.typing import EventDict, Processor

from ati_engine.security.redaction import redact

_STD_ATTRS = frozenset(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def _redact_processor(_: Any, __: str, event_dict: EventDict) -> EventDict:
    redacted = redact(dict(event_dict))
    assert isinstance(redacted, MutableMapping)  # noqa: S101
    return dict(redacted)


def _extra_from_record(_: Any, __: str, event_dict: EventDict) -> EventDict:
    record = event_dict.get("_record")
    if isinstance(record, logging.LogRecord):
        for key, value in vars(record).items():
            if key not in _STD_ATTRS and not key.startswith("_") and key not in event_dict:
                event_dict[key] = value
    return event_dict


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = True,
    console: bool = True,
    log_dir: Path | None = None,
) -> None:
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _extra_from_record,
        structlog.processors.format_exc_info,
        _redact_processor,
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(level)
    # HTTP istemcilerinin istek günlükleri adres yazar (Telegram adresinde bot anahtarı, Binance
    # adreslerinde imza bulunabilir); yalnızca uyarı ve üstü kaydedilir.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        root.addHandler(stream)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "engine.jsonl", maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
        )
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=shared,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.JSONRenderer(ensure_ascii=False),
                ],
            )
        )
        root.addHandler(file_handler)

    # Üçüncü taraf kütüphanelerin gürültüsünü azalt.
    for noisy in ("uvicorn.access", "websockets", "asyncio"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, logging.getLevelName(level)))

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
