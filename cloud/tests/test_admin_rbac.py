"""Aşama 16 kabul kriteri: **her yönetici uç noktası için yetki testi**.

Uygulamadaki tüm ``/admin/v1`` rotaları taranır:

1. Giriş dışındaki her rotanın tam olarak bir yetki denetimi (``require("<yetki>")``) vardır.
2. Oturumsuz istek her rotada 401 alır.
3. Her rol (ve rolsüz yönetici) için: rolün yetkisi yoksa 403, varsa 401/403 dışında bir yanıt.
4. Durum değiştiren istekler başka kökenden gelirse (yetkili rolle bile) 403 alır.

Yeni bir uç nokta eklenip yetki denetimi unutulursa bu test başarısız olur.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.routing import APIRoute

from admin_support import ADMIN_ORIGIN, AdminClient, Clock, activate_admin

ROLES = ["super_admin", "license_manager", "support", "finance", "auditor"]
PUBLIC_AUTH = "/admin/v1/auth/"


def permission_of(route: APIRoute) -> list[str | None]:
    found: list[str | None] = []

    def walk(dependant: Any) -> None:
        for dep in dependant.dependencies:
            if hasattr(dep.call, "permission"):
                found.append(dep.call.permission)
            walk(dep)

    walk(route.dependant)
    return found


def flatten(routes: list[Any]) -> list[Any]:
    """FastAPI 0.16x dahil edilen yönlendiricileri sarmalar; içlerine inilir."""
    flat: list[Any] = []
    for route in routes:
        inner = getattr(route, "original_router", None)
        flat.extend(flatten(inner.routes) if inner is not None else [route])
    return flat


def admin_routes(application: Any) -> list[tuple[str, str, str]]:
    routes = []
    for route in flatten(application.routes):
        if not isinstance(route, APIRoute) or not route.path.startswith("/admin/v1/"):
            continue
        if route.path.startswith(PUBLIC_AUTH):
            continue
        perms = permission_of(route)
        assert len(perms) == 1 and perms[0], (
            f"{route.path}: tek bir yetki denetimi olmalı ({perms})"
        )
        for method in route.methods:
            routes.append((method, route.path, perms[0]))
    return sorted(routes)


def concrete(path: str) -> str:
    return (
        path.replace("{code}", "d30_1dev")
        .replace("{message_id}", "1")
        .replace("{license_id}", str(uuid.uuid4()))
        .replace("{customer_id}", str(uuid.uuid4()))
        .replace("{device_id}", str(uuid.uuid4()))
        .replace("{admin_id}", str(uuid.uuid4()))
    )


async def call(http: httpx.AsyncClient, method: str, path: str, origin: str = ADMIN_ORIGIN) -> int:
    body = None if method == "GET" else {}
    response = await http.request(method, concrete(path), json=body, headers={"Origin": origin})
    return response.status_code


def test_every_admin_route_declares_a_permission(app: Any) -> None:
    routes = admin_routes(app)
    assert len(routes) >= 30
    permissions = {perm for _, _, perm in routes}
    # Sistemdeki her yetki en az bir uç noktada kullanılır (ölü yetki yok); payment.refund Aşama 17.
    with psycopg.connect(app.state.settings.database_url.get_secret_value()) as conn:
        all_perms = {r[0] for r in conn.execute("SELECT code FROM admin_permissions").fetchall()}
    assert all_perms - permissions == {"payment.refund"}
    assert permissions <= all_perms


async def test_rbac_matrix_for_every_admin_route(app: Any, clock: Clock, dsn: str) -> None:
    routes = admin_routes(app)
    with psycopg.connect(dsn) as conn:
        grants: dict[str, set[str]] = {}
        for role, perm in conn.execute(
            "SELECT role_code, permission_code FROM admin_role_permissions"
        ).fetchall():
            grants.setdefault(role, set()).add(perm)

    clients: dict[str, AdminClient] = {}
    for role in ROLES:
        clients[role] = await activate_admin(app, clock, f"{role}@example.com", [role])
    # Rolü sonradan elinden alınmış (hiç yetkisi olmayan) yönetici.
    clients["no_role"] = await activate_admin(app, clock, "rolsuz@example.com", ["auditor"])
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM admin_user_roles WHERE admin_id = %s", (clients["no_role"].id,))

    anonymous = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )
    failures: list[str] = []
    for method, path, perm in routes:
        status = await call(anonymous, method, path)
        if status != 401:
            failures.append(f"oturumsuz {method} {path}: {status} (401 beklenirdi)")
        for role, client in clients.items():
            allowed = perm in grants.get(role, set())
            status = await call(client.http, method, path)
            if allowed and status in (401, 403):
                failures.append(f"{role} {method} {path} [{perm}]: {status} (izinli olmalı)")
            if not allowed and status != 403:
                failures.append(f"{role} {method} {path} [{perm}]: {status} (403 beklenirdi)")
        if method != "GET":
            status = await call(
                clients["super_admin"].http, method, path, origin="https://kotu.example"
            )
            if status != 403:
                failures.append(f"yabancı köken {method} {path}: {status} (403 beklenirdi)")
    await anonymous.aclose()
    for client in clients.values():
        await client.http.aclose()
    assert failures == [], "\n".join(failures)


@pytest.mark.parametrize("role", ROLES)
async def test_me_reports_role_permissions(app: Any, clock: Clock, dsn: str, role: str) -> None:
    client = await activate_admin(app, clock, f"{role}@example.com", [role])
    me = (await client.http.get("/admin/v1/auth/me")).json()
    with psycopg.connect(dsn) as conn:
        expected = sorted(
            r[0]
            for r in conn.execute(
                "SELECT permission_code FROM admin_role_permissions WHERE role_code = %s", (role,)
            ).fetchall()
        )
    assert me["roles"] == [role] and me["permissions"] == expected
    assert me["recovery_codes_left"] == 10
    await client.http.aclose()
