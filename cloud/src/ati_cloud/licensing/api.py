"""Lisans API'si.

* Motor uç noktaları (``/v1/licenses/*``): çerez kullanılmaz; kimlik, cihazın Ed25519 anahtarıyla
  imzalanmış istekle kanıtlanır. Hata gövdesi ``{"detail": {"code", "message"}}``.
* Müşteri uç noktaları (``/v1/me/licenses/*``): oturum çerezi + köken denetimi (CSRF).
"""

from __future__ import annotations

import base64
from typing import Any

from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ati_cloud.accounts import (
    Database,
    SlidingWindowLimiter,
    check_origin,
    client_ip,
    customer_dependency,
    hasher,
    limited,
)
from ati_cloud.config import CloudSettings
from ati_cloud.licensing.service import LicenseError, Licensing


class SignedRequest(BaseModel):
    p: str = Field(min_length=2, max_length=8192)
    s: str = Field(min_length=10, max_length=200)


class RevealRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _error(exc: LicenseError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def create_license_router(
    settings: CloudSettings, db: Database, licensing: Licensing | None
) -> APIRouter:
    router = APIRouter(prefix="/v1")
    activate_ip = SlidingWindowLimiter(10, 60)
    activate_ip_hour = SlidingWindowLimiter(30, 3600)
    renew_ip = SlidingWindowLimiter(120, 60)
    reveal_customer = SlidingWindowLimiter(5, 3600)
    customer_dep = Depends(customer_dependency(db))

    def service() -> Licensing:
        if licensing is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "unavailable", "message": "Lisans servisi yapılandırılmadı"},
            )
        return licensing

    # --- Motor ----------------------------------------------------------------------------

    @router.post("/licenses/activate")
    async def activate(body: SignedRequest, request: Request) -> dict[str, Any]:
        lic = service()
        ip = client_ip(request)
        limited(activate_ip, ip)
        limited(activate_ip_hour, ip)
        try:
            async with db.connection() as conn:
                return await lic.activate(conn, body.model_dump(), ip=ip)
        except LicenseError as exc:
            raise _error(exc) from exc

    @router.post("/licenses/renew")
    async def renew(body: SignedRequest, request: Request) -> dict[str, Any]:
        lic = service()
        ip = client_ip(request)
        limited(renew_ip, ip)
        try:
            async with db.connection() as conn:
                return await lic.renew(conn, body.model_dump(), ip=ip)
        except LicenseError as exc:
            raise _error(exc) from exc

    @router.post("/licenses/deactivate")
    async def deactivate(body: SignedRequest, request: Request) -> dict[str, str]:
        lic = service()
        ip = client_ip(request)
        limited(renew_ip, ip)
        try:
            async with db.connection() as conn:
                await lic.release(conn, body.model_dump(), ip=ip)
        except LicenseError as exc:
            raise _error(exc) from exc
        return {"status": "ok", "message": "Bilgisayar lisanstan çıkarıldı"}

    @router.get("/licenses/signing-key")
    async def signing_key() -> dict[str, str]:
        """Kira imza anahtarının açık kısmı (motor sürümüne gömülen anahtarla karşılaştırma)."""
        lic = service()
        return {
            "kid": lic.signer.kid,
            "public_key": base64.b64encode(lic.signer.public_raw).decode(),
        }

    # --- Müşteri paneli -------------------------------------------------------------------

    @router.post("/me/licenses/{license_id}/devices/{device_id}/deactivate")
    async def customer_deactivate(
        license_id: str,
        device_id: str,
        request: Request,
        customer: dict[str, Any] = customer_dep,
    ) -> dict[str, Any]:
        check_origin(settings, request)
        lic = service()
        try:
            async with db.connection() as conn:
                left = await lic.customer_release(
                    conn,
                    customer_id=customer["id"],
                    license_id=license_id,
                    device_id=device_id,
                    ip=client_ip(request),
                )
        except LicenseError as exc:
            raise _error(exc) from exc
        return {
            "status": "ok",
            "message": (
                "Bilgisayar kaldırıldı. Lisansı yeni bilgisayarınızda etkinleştirebilirsiniz."
            ),
            "device_resets_left": left,
        }

    @router.post("/me/licenses/{license_id}/reveal")
    async def reveal(
        license_id: str,
        body: RevealRequest,
        request: Request,
        response: Response,
        customer: dict[str, Any] = customer_dep,
    ) -> dict[str, str]:
        """Tam lisans anahtarını gösterir; parolanın yeniden girilmesini ister."""
        check_origin(settings, request)
        lic = service()
        limited(reveal_customer, str(customer["id"]))
        try:
            hasher.verify(customer["password_hash"], body.password)
        except (VerifyMismatchError, VerificationError, InvalidHashError) as exc:
            raise HTTPException(status_code=401, detail="Parola hatalı") from exc
        response.headers["Cache-Control"] = "no-store"
        try:
            async with db.connection() as conn:
                key = await lic.reveal(
                    conn, customer_id=customer["id"], license_id=license_id, ip=client_ip(request)
                )
        except LicenseError as exc:
            raise _error(exc) from exc
        return {"key": key}

    return router
