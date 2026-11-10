"""İsteğe bağlı uygulama hata raporları: kabul, ayıklama, tekilleştirme, sınırlar, yönetici."""

from __future__ import annotations

from typing import Any

import httpx
import psycopg

from admin_support import Clock, activate_admin

FP = "0123456789abcdef0123456789abcdef"


def report(**extra: Any) -> dict[str, Any]:
    return {
        "app": "engine",
        "version": "0.4.0",
        "os": "Windows 11",
        "component": "ati_engine.market",
        "error_type": "RuntimeError",
        "message": "bağlanamadı: ayse@example.com 10.0.0.5 ATI-AB12-CD34-EF56-GH78",
        "stack": r'File "C:\Users\Ayşe Yılmaz\AppData\x.py", line 3, in run '
        "key=vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A",
        "fingerprint": FP,
        **extra,
    }


async def test_reports_are_scrubbed_grouped_and_listed_for_admins(
    app: Any, clock: Clock, conn: psycopg.Connection
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        first = await http.post("/v1/crash-reports", json=report())
        assert first.status_code == 202 and first.json() == {"status": "stored"}
        again = await http.post("/v1/crash-reports", json=report(version="0.4.1"))
        assert again.json() == {"status": "counted"}
        for bad in (
            report(fingerprint="xyz"), report(app="baska"), report(message="x" * 501),
            report(version="1.0 ; DROP"),
        ):  # fmt: skip
            assert (await http.post("/v1/crash-reports", json=bad)).status_code == 422
    row = conn.execute(
        "SELECT message, stack, occurrences, first_version, last_version FROM crash_reports"
    ).fetchone()
    assert row is not None
    message, stack, occurrences, first_version, last_version = row
    for leaked in ("ayse@example.com", "10.0.0.5", "ATI-AB12", "Ayşe Yılmaz", "vmPUZE6mv9"):
        assert leaked not in message + stack, leaked
    assert (occurrences, first_version, last_version) == (2, "0.4.0", "0.4.1")
    columns = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'crash_reports'"
    ).fetchall()}  # fmt: skip
    assert not columns & {"ip", "customer_id", "device_id", "email"}

    admin = await activate_admin(app, clock, "kurucu@example.com", ["super_admin"])
    support = await activate_admin(app, clock, "destek@example.com", ["support"])
    assert (await support.http.get("/admin/v1/crash-reports")).status_code == 403
    listed = (await admin.http.get("/admin/v1/crash-reports")).json()
    assert [r["fingerprint"] for r in listed] == [FP] and listed[0]["status"] == "new"
    fixed = await admin.http.patch(f"/admin/v1/crash-reports/{FP}", json={"status": "fixed"})
    assert fixed.status_code == 200
    assert (await admin.http.get("/admin/v1/crash-reports", params={"status": "new"})).json() == []
    missing = await admin.http.patch("/admin/v1/crash-reports/" + "f" * 32, json={"status": "seen"})
    assert missing.status_code == 404

    # Düzeltildi işaretli hata aynı sürümde sayılır; yeni sürümde yeniden açılır.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        await http.post("/v1/crash-reports", json=report(version="0.4.1"))
        assert conn.execute("SELECT status FROM crash_reports").fetchone() == ("fixed",)
        await http.post("/v1/crash-reports", json=report(version="0.5.0"))
        assert conn.execute("SELECT status FROM crash_reports").fetchone() == ("new",)
    actions = [r[0] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    assert "admin.crash_status" in actions
    for client in (admin, support):
        await client.http.aclose()


async def test_rate_limit_per_ip(app: Any) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        codes = [
            (await http.post("/v1/crash-reports", json=report(fingerprint=f"{i:032x}"))).status_code
            for i in range(32)
        ]
    assert codes.count(202) == 30 and codes[-1] == 429
