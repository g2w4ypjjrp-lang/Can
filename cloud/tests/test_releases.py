"""İndirme sayfası: uygulama sürümleri (yönetici yayınlar, site gösterir). Gerçek PostgreSQL."""

from __future__ import annotations

from typing import Any

import httpx
import psycopg
import pytest

from admin_support import AdminClient, Clock, activate_admin
from ati_cloud.releases import check_download_url

SHA = "a" * 64
EXE = "https://indir.canarslan.net.tr/AI-Trading-Intelligence_1.0.0_x64-setup.exe"


def windows(version: str = "1.0.0", **extra: Any) -> dict[str, Any]:
    return {
        "platform": "windows",
        "version": version,
        "download_url": EXE.replace("1.0.0", version),
        "sha256": SHA.upper(),
        "size_bytes": 95_000_000,
        "min_os": "Windows 10 (64 bit)",
        "notes": "İlk sürüm",
        **extra,
    }


@pytest.fixture
async def root(app: Any, clock: Clock) -> AdminClient:
    return await activate_admin(app, clock, "kok@example.com", ["super_admin"])


@pytest.fixture
def public(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def publish(root: AdminClient, clock: Clock, release_id: str) -> httpx.Response:
    return await root.http.post(
        f"/admin/v1/releases/{release_id}/publish", json={"code": clock.code(root.secret)}
    )


async def test_nothing_published_yet(public: httpx.AsyncClient) -> None:
    response = await public.get("/v1/releases")
    assert response.status_code == 200
    assert response.json() == {"windows": None, "ios": None}
    assert response.headers["cache-control"] == "public, max-age=60"


async def test_draft_publish_withdraw_lifecycle(
    root: AdminClient, clock: Clock, public: httpx.AsyncClient, dsn: str
) -> None:
    created = await root.http.post("/admin/v1/releases", json=windows())
    assert created.status_code == 201, created.text
    release = created.json()
    assert release["status"] == "draft" and release["sha256"] == SHA  # küçük harfe çevrilir
    # Taslak sitede görünmez.
    assert (await public.get("/v1/releases")).json()["windows"] is None

    # Yayınlamak güncel TOTP kodu ister.
    wrong = await root.http.post(
        f"/admin/v1/releases/{release['id']}/publish", json={"code": "000000"}
    )
    assert wrong.status_code == 400
    published = await publish(root, clock, release["id"])
    assert published.status_code == 200, published.text
    shown = (await public.get("/v1/releases")).json()["windows"]
    assert shown["version"] == "1.0.0" and shown["sha256"] == SHA
    assert shown["download_url"] == EXE and shown["size_bytes"] == 95_000_000
    assert shown["signed"] is False and "status" not in shown and "id" not in shown

    # Daha yeni sürüm yayınlanınca en son o gösterilir.
    newer = (await root.http.post("/admin/v1/releases", json=windows("1.1.0"))).json()
    assert (await publish(root, clock, newer["id"])).status_code == 200
    assert (await public.get("/v1/releases")).json()["windows"]["version"] == "1.1.0"

    # Geri çekilen sürüm gösterilmez; önceki yayındaki sürüme dönülür.
    pulled = await root.http.post(
        f"/admin/v1/releases/{newer['id']}/withdraw", json={"reason": "Hatalı paket"}
    )
    assert pulled.status_code == 200 and pulled.json()["status"] == "withdrawn"
    assert (await public.get("/v1/releases")).json()["windows"]["version"] == "1.0.0"

    with psycopg.connect(dsn) as conn:
        actions = [
            r[0]
            for r in conn.execute(
                "SELECT action FROM audit_log WHERE target_type = 'release' ORDER BY id"
            ).fetchall()
        ]
        assert conn.execute("SELECT audit_log_verify()").fetchone() == (None,)
    assert actions == [
        "admin.release_created",
        "admin.release_published",
        "admin.release_created",
        "admin.release_published",
        "admin.release_withdrawn",
    ]


async def test_published_file_cannot_change(root: AdminClient, clock: Clock, dsn: str) -> None:
    release = (await root.http.post("/admin/v1/releases", json=windows())).json()
    # Taslakta düzeltme yapılabilir.
    fixed = await root.http.patch(
        f"/admin/v1/releases/{release['id']}", json={"sha256": "b" * 64, "notes": "Düzeltildi"}
    )
    assert fixed.status_code == 200 and fixed.json()["sha256"] == "b" * 64
    assert (await publish(root, clock, release["id"])).status_code == 200

    # Yayındaki dosyanın adresi/özeti değiştirilemez; açıklama değiştirilebilir.
    for change in (
        {"sha256": SHA},
        {"download_url": EXE.replace(".exe", "-2.exe")},
        {"size_bytes": 1},
    ):
        response = await root.http.patch(f"/admin/v1/releases/{release['id']}", json=change)
        assert response.status_code == 409, change
    notes = await root.http.patch(f"/admin/v1/releases/{release['id']}", json={"notes": "Yeni not"})
    assert notes.status_code == 200 and notes.json()["notes"] == "Yeni not"

    # Uygulama atlatılsa bile veritabanı reddeder.
    with psycopg.connect(dsn, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE app_releases SET sha256 = %s WHERE id = %s", (SHA, release["id"]))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE app_releases SET status = 'draft' WHERE id = %s", (release["id"],))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("DELETE FROM app_releases WHERE id = %s", (release["id"],))


async def test_validation(root: AdminClient) -> None:
    async def create(**changes: Any) -> int:
        body = {**windows(), **changes}
        return (await root.http.post("/admin/v1/releases", json=body)).status_code

    assert await create(version="1.0") == 422
    assert await create(sha256="xyz") == 422
    assert await create(sha256=None) == 422  # Windows paketi için özet zorunlu
    assert await create(size_bytes=None) == 422
    assert await create() == 201
    assert await create() == 409  # aynı platformda aynı sürüm
    # iPhone uygulaması: yalnızca App Store / TestFlight, dosya özeti gerekmez.
    ios = {"platform": "ios", "version": "1.0.0"}
    good = await root.http.post(
        "/admin/v1/releases",
        json={**ios, "download_url": "https://apps.apple.com/tr/app/ati/id1234567890"},
    )
    assert good.status_code == 201, good.text
    bad = await root.http.post(
        "/admin/v1/releases", json={**ios, "version": "1.0.1", "download_url": EXE}
    )
    assert bad.status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "http://indir.canarslan.net.tr/a.exe",  # https değil
        "https://kotu.example/a.exe",  # izinsiz alan adı
        "https://indir.canarslan.net.tr.kotu.example/a.exe",  # benzer alan adı
        "https://indir.canarslan.net.tr@kotu.example/a.exe",  # kullanıcı bilgisi hilesi
        "https://indir.canarslan.net.tr:8443/a.exe",  # port
        "https://indir.canarslan.net.tr/a.zip",  # .exe değil
        "https://indir.canarslan.net.tr/a.exe#x",
        "javascript:alert(1)//a.exe",
    ],
)
def test_download_url_rules(url: str) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        check_download_url("windows", url, ["canarslan.net.tr", "indir.canarslan.net.tr"])


def test_download_url_accepts_allowed_hosts() -> None:
    hosts = ["canarslan.net.tr", "indir.canarslan.net.tr"]
    check_download_url("windows", EXE, hosts)
    check_download_url("windows", "https://CANARSLAN.net.tr/indir/Kurulum.EXE", hosts)
    check_download_url("ios", "https://testflight.apple.com/join/AbCdEf12", hosts)


async def test_only_release_managers(app: Any, clock: Clock) -> None:
    support = await activate_admin(app, clock, "destek@example.com", ["support"])
    assert (await support.http.get("/admin/v1/releases")).status_code == 403
    assert (await support.http.post("/admin/v1/releases", json=windows())).status_code == 403


def signature(text: str = "imza") -> str:
    import base64

    body = (
        "untrusted comment: signature from tauri secret key\n"
        f"RUQ{text}{'A' * 80}\ntrusted comment: timestamp:1794346520\tfile:setup.exe\n{'B' * 88}\n"
    )
    return base64.b64encode(body.encode()).decode()


async def test_update_manifest_offers_only_newer_signed_windows_release(
    root: AdminClient, clock: Clock, public: httpx.AsyncClient
) -> None:
    url = "/v1/updates/windows-x86_64/1.0.0"
    assert (await public.get(url)).status_code == 204  # hiç sürüm yok

    # İmzasız sürüm otomatik güncellemede sunulmaz (indirme sayfasında görünür).
    unsigned = (await root.http.post("/admin/v1/releases", json=windows("1.1.0"))).json()
    assert unsigned["updatable"] is False
    assert (await publish(root, clock, unsigned["id"])).status_code == 200
    assert (await public.get(url)).status_code == 204

    bad = await root.http.post(
        "/admin/v1/releases", json=windows("1.2.0", update_signature="imza değil")
    )
    assert bad.status_code == 422 and ".sig" in bad.text
    signed = await root.http.post(
        "/admin/v1/releases", json=windows("1.2.0", update_signature=signature())
    )
    assert signed.status_code == 201 and signed.json()["updatable"] is True
    assert (await public.get(url)).status_code == 204  # taslak sunulmaz
    assert (await publish(root, clock, signed.json()["id"])).status_code == 200

    manifest = (await public.get(url)).json()
    assert manifest["version"] == "1.2.0"
    target = manifest["platforms"]["windows-x86_64"]
    assert target["signature"] == signature()
    assert target["url"] == EXE.replace("1.0.0", "1.2.0")
    assert manifest["pub_date"].endswith("Z")
    # Güncel ya da daha yeni sürümdeki uygulamaya, bozuk sürüm numarasına ve başka hedefe: 204.
    for path in (
        "/v1/updates/windows-x86_64/1.2.0",
        "/v1/updates/windows-x86_64/1.3.0-beta",
        "/v1/updates/windows-x86_64/abc",
        "/v1/updates/darwin-aarch64/1.0.0",
    ):
        assert (await public.get(path)).status_code == 204, path
    assert (await public.get("/v1/updates/windows-x86_64/1.2.0-beta")).status_code == 200

    # Yayınlanan sürümün imzası değiştirilemez.
    changed = await root.http.patch(
        f"/admin/v1/releases/{signed.json()['id']}", json={"update_signature": signature("x")}
    )
    assert changed.status_code == 409


def test_version_order() -> None:
    from ati_cloud.releases import version_key

    assert version_key("1.2.0") > version_key("1.2.0-beta") > version_key("1.1.9")
    assert version_key("1.10.0") > version_key("1.9.9")
