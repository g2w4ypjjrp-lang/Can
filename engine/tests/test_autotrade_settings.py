"""Bot (otomatik işlem) ayarlarının uygulamadan düzenlenmesi: doğrulama, risk sınırları üst sınır,
kalıcılık (motor yeniden başlayınca uygulanır), varsayılana dönüş ve denetim kaydı."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from ati_engine.app import Engine
from ati_engine.config import AutoTradeSettings, EngineSettings, LocalApiSettings, RiskLimits
from ati_engine.execution.auto import merged_settings


def test_merged_settings_respects_risk_limits() -> None:
    base, limits = AutoTradeSettings(), RiskLimits()
    cfg = merged_settings(base, limits, {"min_score": 80, "leverage": 3, "enabled": True})
    assert cfg.min_score == 80 and cfg.leverage == 3
    assert cfg.enabled is False  # açma/kapama bu yoldan değişmez
    with pytest.raises(ValueError, match="risk sınırını"):
        merged_settings(base, limits, {"risk_per_trade_pct": "0.6"})
    with pytest.raises(ValueError, match="3x"):
        merged_settings(base, limits, {"leverage": 4})
    with pytest.raises(ValueError, match="piyasa"):
        merged_settings(base, limits, {"markets": []})


@pytest.fixture
def engine_at(tmp_path: Path) -> Callable[[], AsyncIterator[httpx.AsyncClient]]:
    @asynccontextmanager
    async def run() -> AsyncIterator[httpx.AsyncClient]:
        settings = EngineSettings(
            data_dir=tmp_path / "data", log_to_console=False, api=LocalApiSettings(port=0)
        )
        engine = Engine(settings)
        task = asyncio.create_task(engine.run())
        await asyncio.wait_for(engine.ready.wait(), timeout=15)
        assert engine.runtime is not None
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{engine.bound_port}",
            headers={"Authorization": f"Bearer {engine.runtime.api_token}"},
        ) as http:
            yield http
        engine.runtime.request_shutdown()
        await asyncio.wait_for(task, timeout=15)

    return run  # type: ignore[return-value]


async def test_settings_are_validated_persisted_and_reset(engine_at: Callable[..., Any]) -> None:
    async with engine_at() as http:
        status = (await http.get("/v1/autotrade")).json()
        assert status["settings"]["min_score"] == 70.0
        assert status["limits"] == {"max_risk_per_trade_pct": "0.5", "max_leverage": 3}
        assert status["defaults"]["leverage"] == 2
        for bad in (
            {"risk_per_trade_pct": "0.75"},  # risk sınırı %0,5
            {"leverage": 5},  # risk sınırı 3x
            {"min_score": 30},  # en düşük 50
            {"markets": []},
            {"max_entries_per_hour": 0},
            {},
        ):
            response = await http.post("/v1/autotrade/settings", json=bad)
            assert response.status_code == 422, (bad, response.text)
        too_risky = await http.post("/v1/autotrade/settings", json={"risk_per_trade_pct": "0.75"})
        assert "risk sınırını" in too_risky.json()["detail"]
        ok = await http.post(
            "/v1/autotrade/settings",
            json={"min_score": 82, "risk_per_trade_pct": "0.4", "leverage": 3,
                  "markets": ["usdm_futures", "spot"], "symbol_cooldown_s": 7200},
        )  # fmt: skip
        assert ok.status_code == 200, ok.text
        settings = ok.json()["settings"]
        assert settings["min_score"] == 82 and Decimal(settings["risk_per_trade_pct"]) == Decimal(
            "0.4"
        )
        assert settings["markets"] == ["usdm_futures", "spot"] and ok.json()["enabled"] is False
        audit = (await http.get("/v1/audit")).text
        assert "autotrade.settings_changed" in audit

    # Motor yeniden başlayınca kayıtlı ayarlar uygulanır.
    async with engine_at() as http:
        settings = (await http.get("/v1/autotrade")).json()["settings"]
        assert settings["min_score"] == 82 and settings["leverage"] == 3
        reset = await http.post("/v1/autotrade/settings/reset")
        assert reset.json()["settings"]["min_score"] == 70.0

    async with engine_at() as http:
        assert (await http.get("/v1/autotrade")).json()["settings"]["min_score"] == 70.0


async def test_decision_interval_is_saved_and_applied_after_restart(
    engine_at: Callable[..., Any],
) -> None:
    """Karar aralığı (ör. 1 dakika) kaydedilir; motor yeniden başlayınca fırsat motoru ve bot o
    aralıkla çalışır. Sinyal geçerliliği aralığa göre kısalır (1 dk → 60 sn)."""
    async with engine_at() as http:
        status = (await http.get("/v1/autotrade")).json()
        assert status["interval"] == "1h" and status["signal_valid_s"] == 900
        assert status["restart_required"] is False
        bad = await http.post("/v1/autotrade/interval", json={"interval": "7m"})
        assert bad.status_code == 422
        saved = (await http.post("/v1/autotrade/interval", json={"interval": "1m"})).json()
        assert saved["decision_interval_saved"] == "1m" and saved["restart_required"] is True
        assert saved["interval"] == "1h"  # yeniden başlayana kadar eski aralık
    async with engine_at() as http:
        status = (await http.get("/v1/autotrade")).json()
        assert status["interval"] == "1m" and status["restart_required"] is False
        assert status["signal_valid_s"] == 60
        assert status["next_decision_ms"] % 60_000 == 0
        stats = (await http.get("/v1/opportunities/stats")).json()
        assert stats["interval"] == "1m"
        audit = (await http.get("/v1/audit?limit=50")).text
        assert "autotrade.interval_changed" in audit


async def test_bot_on_off_survives_restart(engine_at: Callable[..., Any]) -> None:
    """Bot açık bırakıldıysa uygulama yeniden açılınca da açık gelir (işlem modu güvenlik
    gereği Sanal başladığından gerçek hesapta, gerçek para yeniden onaylanana kadar girmez;
    Sanal modda sanal hesapta işlem açar)."""
    async with engine_at() as http:
        assert (await http.get("/v1/autotrade")).json()["enabled"] is False
        assert (await http.post("/v1/autotrade", json={"enabled": True})).json()["enabled"] is True
    async with engine_at() as http:
        status = (await http.get("/v1/autotrade")).json()
        assert status["enabled"] is True and status["environment"] == "paper"
        mode = next(c for c in status["checks"] if c["key"] == "mode")
        # Sanal modda bot sanal hesapla işlem açar (borsaya emir gitmez).
        assert mode["ok"] is True and "Sanal hesap" in mode["detail"]
        assert "10.000 USDT" in mode["detail"]
        assert (await http.post("/v1/autotrade", json={"enabled": False})).json()[
            "enabled"
        ] is False
    async with engine_at() as http:
        assert (await http.get("/v1/autotrade")).json()["enabled"] is False


async def test_unexpected_error_reaches_the_ui_with_its_reason(
    engine_at: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Beklenmeyen hata CORS başlıklı JSON yanıta çevrilir: arayüz 'Motora ulaşılamadı' yerine
    gerçek nedeni gösterir."""
    from ati_engine.execution.auto import AutoTrader

    def boom(self: AutoTrader) -> dict[str, Any]:
        raise RuntimeError("deneme hatası")

    origin = LocalApiSettings().allowed_origins[0]
    async with engine_at() as http:
        monkeypatch.setattr(AutoTrader, "status", boom)
        response = await http.get("/v1/autotrade", headers={"Origin": origin})
        assert response.status_code == 500
        assert "deneme hatası" in response.json()["detail"]
        assert response.headers.get("access-control-allow-origin") == origin
