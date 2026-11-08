"""Web sitesi iletişim formu (Aşama 14).

Mesaj yalnızca veritabanına yazılır. Gönderene otomatik e-posta **gönderilmez**: aksi hâlde
form, rastgele adreslere e-posta yollatmak için kötüye kullanılabilirdi. Köken denetimi,
IP başına hız sınırı ve botlar için gizli tuzak alanı vardır.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field

from ati_cloud.accounts import (
    Database,
    SlidingWindowLimiter,
    check_origin,
    client_ip,
    limited,
    session_customer_id,
)
from ati_cloud.config import CloudSettings

CONTACT_RECEIVED = {
    "status": "ok",
    "message": "Mesajınız alındı. En kısa sürede e-posta ile dönüş yapacağız.",
}


class ContactRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    topic: Literal["sales", "support", "license", "privacy", "other"]
    message: str = Field(min_length=10, max_length=5000)
    # Gizli tuzak alanı: ekranda görünmez; dolu gelirse istek bot kabul edilir.
    website: str = Field(default="", max_length=200)


def create_contact_router(settings: CloudSettings, db: Database) -> APIRouter:
    router = APIRouter(prefix="/v1")
    per_ip = SlidingWindowLimiter(5, 3600)

    @router.post("/contact", status_code=202)
    async def contact(body: ContactRequest, request: Request) -> dict[str, str]:
        check_origin(settings, request)
        limited(per_ip, client_ip(request))
        if body.website:
            return CONTACT_RECEIVED  # bota fark ettirmeden yok say
        customer_id = await session_customer_id(db, request)
        async with db.connection() as conn:
            await conn.execute(
                "INSERT INTO contact_messages "
                "(customer_id, name, email, topic, message, ip, user_agent) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    customer_id,
                    body.name.strip(),
                    str(body.email).lower(),
                    body.topic,
                    body.message.strip(),
                    client_ip(request),
                    (request.headers.get("user-agent") or "")[:300],
                ),
            )
        return CONTACT_RECEIVED

    return router
