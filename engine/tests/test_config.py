from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from ati_engine.config import EngineSettings, LocalApiSettings, RiskLimits
from ati_engine.core.models import TradingMode
from ati_engine.system.paths import DataPaths, default_data_dir
from ati_engine.system.single_instance import AlreadyRunningError, SingleInstanceLock


def test_safe_defaults(tmp_path: Path) -> None:
    s = EngineSettings(data_dir=tmp_path)
    assert s.trading_mode is TradingMode.PAPER
    assert s.live_trading_enabled is False
    assert s.api.host == "127.0.0.1"
    assert s.risk.max_leverage <= 3
    assert s.binance.futures_ws_market.endswith("/market")


def test_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATI_RISK__MAX_LEVERAGE", "5")
    monkeypatch.setenv("ATI_API__PORT", "50000")
    s = EngineSettings()
    assert s.data_dir == tmp_path
    assert s.risk.max_leverage == 5
    assert s.api.port == 50000


def test_toml_file_is_read_and_env_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    DataPaths(tmp_path).config_file.write_text(
        "[risk]\nmax_open_positions = 7\nmax_leverage = 2\n[api]\nport = 41000\n", encoding="utf-8"
    )
    monkeypatch.setenv("ATI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATI_API__PORT", "42000")
    s = EngineSettings()
    assert s.risk.max_open_positions == 7
    assert s.risk.max_leverage == 2
    assert s.api.port == 42000


def test_unknown_keys_rejected(tmp_path: Path) -> None:
    DataPaths(tmp_path).config_file.write_text("bilinmeyen_ayar = 1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        EngineSettings(data_dir=tmp_path)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com", "::"])  # noqa: S104
def test_local_api_must_be_loopback(host: str) -> None:
    with pytest.raises(ValidationError):
        LocalApiSettings(host=host)


def test_localhost_normalized() -> None:
    assert LocalApiSettings(host="localhost").host == "127.0.0.1"
    assert LocalApiSettings(host="::1").host == "::1"


def test_risk_hard_caps() -> None:
    with pytest.raises(ValidationError, match="Kaldıraç"):
        RiskLimits(max_leverage=50)
    with pytest.raises(ValidationError, match="İşlem başına risk"):
        RiskLimits(max_risk_per_trade_pct=Decimal("10"))
    with pytest.raises(ValidationError, match="Günlük zarar"):
        RiskLimits(max_risk_per_trade_pct=Decimal("3"), max_daily_loss_pct=Decimal("1"))
    with pytest.raises(ValidationError):
        RiskLimits(max_risk_per_trade_pct=Decimal("0"))


def test_default_data_dir_per_platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = default_data_dir()
    if sys.platform == "win32":
        assert path.name == "AITradingIntelligence"
    elif sys.platform != "darwin":
        assert path == tmp_path / "xdg" / "ai-trading-intelligence"


def test_paths_ensure_creates_private_dirs(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path / "root")
    paths.ensure()
    for directory in (paths.market_dir, paths.models_dir, paths.logs_dir, paths.runtime_dir):
        assert directory.is_dir()
    if sys.platform != "win32":
        assert (paths.root.stat().st_mode & 0o777) == 0o700


def test_single_instance_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "engine.lock"
    first = SingleInstanceLock(lock_path)
    first.acquire()
    try:
        with pytest.raises(AlreadyRunningError):
            SingleInstanceLock(lock_path).acquire()
    finally:
        first.release()
    with SingleInstanceLock(lock_path) as again:
        assert again.held
