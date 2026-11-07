"""Motoru ayrı bir süreç olarak (masaüstü uygulamasının yapacağı gibi) başlatan duman testi."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.slow


def _start(data_dir: Path) -> subprocess.Popen[bytes]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATI_")}
    env["ATI_LOG_TO_CONSOLE"] = "false"
    kwargs: dict[str, object] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    return subprocess.Popen(  # type: ignore[call-overload,no-any-return]
        [sys.executable, "-m", "ati_engine", "run", "--data-dir", str(data_dir), "--port", "0"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    )


def _wait_runtime(data_dir: Path, proc: subprocess.Popen[bytes]) -> dict[str, object]:
    runtime_file = data_dir / "runtime" / "local-api.json"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            _, err = proc.communicate()
            raise AssertionError(f"Motor erken çıktı: {err.decode(errors='replace')}")
        if runtime_file.exists():
            try:
                info = json.loads(runtime_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
            else:
                url = f"http://127.0.0.1:{info['port']}/v1/health"
                try:
                    if httpx.get(url, timeout=1).status_code == 200:
                        return dict(info)
                except httpx.HTTPError:
                    pass
        time.sleep(0.1)
    proc.kill()
    raise AssertionError("Motor 30 saniyede hazır olmadı")


def test_engine_process_lifecycle_via_api(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    proc = _start(data_dir)
    try:
        info = _wait_runtime(data_dir, proc)
        base = f"http://127.0.0.1:{info['port']}"
        headers = {"Authorization": f"Bearer {info['token']}"}
        status = httpx.get(f"{base}/v1/status", headers=headers, timeout=5).json()
        assert status["trading_mode"] == "paper"
        assert status["engine_state"] == "running"
        assert (
            httpx.post(f"{base}/v1/engine/shutdown", headers=headers, timeout=5).status_code == 202
        )
        assert proc.wait(timeout=20) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    # Denetim kaydı zinciri sağlam ve açılış/kapanış kayıtlı.
    verify = subprocess.run(
        [sys.executable, "-m", "ati_engine", "verify-audit", "--data-dir", str(data_dir)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert verify.returncode == 0, verify.stderr
    log_file = data_dir / "logs" / "engine.jsonl"
    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert any(line.get("event") == "Motor hazır" for line in lines)
    assert all("token" not in line for line in lines)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX sinyali")
def test_engine_stops_gracefully_on_sigterm(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    proc = _start(data_dir)
    try:
        _wait_runtime(data_dir, proc)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=20) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert not (data_dir / "runtime" / "local-api.json").exists()


def test_cli_output_survives_legacy_console_encoding(tmp_path: Path) -> None:
    """Windows'ta yönlendirilmiş çıktı cp1252 olur; Türkçe mesajlar çökmemeli (CI'da yakalandı)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATI_")}
    env["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run(
        [sys.executable, "-m", "ati_engine", "verify-audit", "--data-dir", str(tmp_path / "d")],
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert "Denetim kaydı sağlam" in result.stdout.decode("utf-8")


def test_cli_version_and_config() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "ati_engine", "version"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert out.stdout.strip()
