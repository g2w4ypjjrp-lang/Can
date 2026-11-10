"""İsteğe bağlı hata raporları: varsayılan kapalı, kişisel veri ayıklama, tekilleştirme, hız sınırı,
günlük kaydından yakalama ve yerel API. Bulut yerine sahte sunucu (httpx.MockTransport)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from ati_engine.app import Engine
from ati_engine.config import EngineSettings, LocalApiSettings, NotifySettings
from ati_engine.observability.crash import (
    PER_HOUR,
    CrashLogHandler,
    CrashReporter,
    fingerprint,
    scrub,
)
from ati_engine.storage.database import Database
from ati_engine.storage.settings_store import SettingsStore

URL = "https://api.example.test/v1/crash-reports"


def boom(message: str) -> RuntimeError:
    """Yığın izi olan bir istisna."""
    try:
        raise RuntimeError(message)
    except RuntimeError as exc:
        return exc


class FakeCloud:
    def __init__(self) -> None:
        self.reports: list[dict[str, Any]] = []
        self.status = 202

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.reports.append(json.loads(request.content))
        return httpx.Response(self.status, json={"status": "ok"})


@pytest.fixture
async def reporter(tmp_path: Path) -> AsyncIterator[tuple[CrashReporter, FakeCloud, list[float]]]:
    db = Database(tmp_path / "engine.db")
    await db.open()
    await db.migrate()
    cloud = FakeCloud()
    clock = [1000.0]
    r = CrashReporter(
        store=SettingsStore(db),
        url=URL,
        version="9.9.9",
        transport=httpx.MockTransport(cloud.handler),
        clock=lambda: clock[0],
    )
    await r.load()
    yield r, cloud, clock
    await db.close()


def test_scrub_removes_personal_and_secret_data() -> None:
    text = (
        r'File "C:\Users\Can Arslan\AppData\Local\ati\engine.py", line 3 '
        "/home/canarslan/.local/x.py /Users/can/x.py can.arslan@example.com 192.168.1.20 "
        "ATI-AB12-CD34-EF56-GH78 apiKey=abc123 sig "
        "vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A "
        "token tk_3f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e order 912345678"
    )
    out = scrub(text)
    for leaked in (
        "Can Arslan", "canarslan", "/Users/can/", "can.arslan@example.com", "192.168.1.20",
        "ATI-AB12", "abc123", "vmPUZE6mv9", "tk_3f9a8b7c", "912345678",
    ):  # fmt: skip
        assert leaked not in out, leaked
    assert r"C:\Users\<kullanici>\AppData" in out and "/home/<kullanici>/" in out
    # Düz modül yolları okunur kalır.
    assert "ati_engine/execution/binance_venue" in scrub("ati_engine/execution/binance_venue.py")


def test_fingerprint_groups_same_error_regardless_of_values() -> None:
    a = 'Traceback:\n  File "/a/ati_engine/x.py", line 10, in run\nValueError: 1'
    b = 'Traceback:\n  File "/b/ati_engine/x.py", line 99, in run\nValueError: 2'
    c = 'Traceback:\n  File "/b/ati_engine/x.py", line 99, in other\nValueError: 2'
    assert fingerprint("m", "ValueError", a) == fingerprint("m", "ValueError", b)
    assert fingerprint("m", "ValueError", a) != fingerprint("m", "ValueError", c)


async def test_disabled_by_default_and_opt_in_sends_scrubbed_reports(
    reporter: tuple[CrashReporter, FakeCloud, list[float]],
) -> None:
    r, cloud, clock = reporter
    assert r.enabled is False
    exc = boom("bağlanamadı: can@example.com /home/can/x")
    assert r.capture_exception("ati_engine.market", exc) is False
    await r.drain()
    assert cloud.reports == []

    await r.set_enabled(True)
    assert r.capture_exception("ati_engine.market", exc) is True
    # Aynı hata bir saat içinde ikinci kez gönderilmez.
    assert r.capture_exception("ati_engine.market", exc) is False
    await r.drain()
    assert len(cloud.reports) == 1
    report = cloud.reports[0]
    assert report["app"] == "engine" and report["version"] == "9.9.9"
    assert report["error_type"] == "RuntimeError" and report["component"] == "ati_engine.market"
    assert "can@example.com" not in json.dumps(report) and "/home/can/" not in json.dumps(report)
    assert set(report) == {
        "app", "version", "os", "component", "error_type", "message", "stack", "fingerprint",
        "occurred_at",
    }  # fmt: skip
    assert r.status()["sent"] == 1 and r.status()["endpoint"] == "api.example.test"

    clock[0] += 3601
    assert r.capture_exception("ati_engine.market", boom("yine")) is True


async def test_hourly_cap_and_server_errors(
    reporter: tuple[CrashReporter, FakeCloud, list[float]],
) -> None:
    r, cloud, _ = reporter
    await r.set_enabled(True)
    for i in range(PER_HOUR + 5):
        r.capture(f"bilesen{i}", "ValueError", "x", f'File "/a/m{i}.py", line 1, in f{i}')
    await r.drain()
    assert len(cloud.reports) == PER_HOUR and r.dropped >= 5
    cloud.status = 500
    r2 = CrashReporter(
        store=r._store, url=URL, version="1", transport=httpx.MockTransport(cloud.handler)
    )
    await r2.load()
    r2.capture("x", "E", "m", "s")
    await r2.drain()
    assert r2.sent == 0 and r2.last_error == "Sunucu 500 döndü"


async def test_log_handler_captures_only_errors_with_exceptions(
    reporter: tuple[CrashReporter, FakeCloud, list[float]],
) -> None:
    r, cloud, _ = reporter
    await r.set_enabled(True)
    log = logging.getLogger("ati_engine.test_crash")
    handler = CrashLogHandler(r)
    log.addHandler(handler)
    try:
        log.error("exc_info olmayan hata")
        log.warning("uyarı")
        try:
            {}["yok"]
        except KeyError:
            log.exception("Görev çöktü")
    finally:
        log.removeHandler(handler)
    await r.drain()
    assert [c["error_type"] for c in cloud.reports] == ["KeyError"]
    assert cloud.reports[0]["message"].startswith("Görev çöktü")


async def test_local_api_toggle_and_ui_errors(tmp_path: Path) -> None:
    # Gerçek sunucuya hiçbir şey gitmez: adres yerel, kapalı bir bağlantı noktası.
    settings = EngineSettings(
        data_dir=tmp_path / "data",
        log_to_console=False,
        api=LocalApiSettings(port=0),
        notify=NotifySettings(crash_report_url="http://127.0.0.1:9/v1/crash-reports"),
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=15)
    runtime = engine.runtime
    assert runtime is not None and runtime.crash is not None
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{engine.bound_port}",
        headers={"Authorization": f"Bearer {runtime.api_token}"},
    ) as http:
        status = (await http.get("/v1/crash-reports")).json()
        assert status["enabled"] is False and status["endpoint"] == "127.0.0.1"
        off = await http.post("/v1/crash-reports/ui", json={"message": "x", "stack": "y"})
        assert off.json() == {"queued": False}
        on = await http.post("/v1/crash-reports/enabled", json={"enabled": True})
        assert on.json()["enabled"] is True
        ui = await http.post(
            "/v1/crash-reports/ui",
            json={"message": "Cannot read properties of undefined", "stack": "at Lab (Lab.tsx)",
                  "error_type": "TypeError"},
        )  # fmt: skip
        assert ui.json() == {"queued": True}
        assert "crash_reports.enabled" in (await http.get("/v1/audit")).text
        anon = await httpx.AsyncClient(base_url=f"http://127.0.0.1:{engine.bound_port}").get(
            "/v1/crash-reports"
        )
        assert anon.status_code == 401
    runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=15)
    # Motor kapanınca günlük işleyicisi kaldırılır.
    assert not any(isinstance(h, CrashLogHandler) for h in logging.getLogger().handlers)
