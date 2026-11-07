"""Yerel veri dizini yerleşimi.

Windows: ``%LOCALAPPDATA%\\AITradingIntelligence``
macOS:   ``~/Library/Application Support/AITradingIntelligence`` (geliştirme amaçlı)
Linux:   ``$XDG_DATA_HOME/ai-trading-intelligence`` (geliştirme/CI amaçlı)

Dizin yapısı::

    <root>/
      config.toml          kullanıcı ayarları (gizli bilgi içermez)
      engine.db            SQLite (WAL): emirler, pozisyonlar, günlük, denetim kaydı
      engine.lock          tek örnek kilidi
      market/              Parquet dosyaları (tarihsel mum ve işlem verisi, Aşama 5)
      models/              Yapay zekâ model dosyaları (Aşama 6)
      logs/                Dönen JSON log dosyaları
      runtime/             Çalışma anı bilgileri (yerel API portu ve belirteci)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME_WINDOWS = "AITradingIntelligence"
APP_DIR_NAME_POSIX = "ai-trading-intelligence"


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME_WINDOWS
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME_WINDOWS
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME_POSIX


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @property
    def config_file(self) -> Path:
        return self.root / "config.toml"

    @property
    def database(self) -> Path:
        return self.root / "engine.db"

    @property
    def lock_file(self) -> Path:
        return self.root / "engine.lock"

    @property
    def market_dir(self) -> Path:
        return self.root / "market"

    @property
    def history_db(self) -> Path:
        return self.market_dir / "history.duckdb"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    @property
    def runtime_file(self) -> Path:
        return self.runtime_dir / "local-api.json"

    def ensure(self) -> None:
        for directory in (
            self.root,
            self.market_dir,
            self.models_dir,
            self.logs_dir,
            self.runtime_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
            if sys.platform != "win32":
                # Windows'ta %LOCALAPPDATA% zaten kullanıcıya özeldir.
                directory.chmod(0o700)
