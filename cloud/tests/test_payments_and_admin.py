from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from tests.conftest import ARGON2_HASH, Factory


def _payment(
    conn: psycopg.Connection, order: Any, provider_id: str, status: str = "succeeded"
) -> None:
    conn.execute(
        "INSERT INTO payments (order_id, provider, provider_payment_id, status, amount_minor, currency) "
        "VALUES (%s, 'test', %s, %s, 1000, 'USD')",
        (order, provider_id, status),
    )


def test_webhook_event_is_processed_once(conn: psycopg.Connection) -> None:
    sql = (
        "INSERT INTO payment_webhook_events (provider, provider_event_id, event_type, signature_valid, payload) "
        "VALUES ('test', 'evt_1', 'payment.succeeded', true, '{}')"
    )
    conn.execute(sql)
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(sql)
    # Uygulamanın kullanacağı idempotent desen:
    row = conn.execute(
        "INSERT INTO payment_webhook_events (provider, provider_event_id, event_type, signature_valid, payload) "
        "VALUES ('test', 'evt_1', 'payment.succeeded', true, '{}') "
        "ON CONFLICT (provider, provider_event_id) DO NOTHING RETURNING id"
    ).fetchone()
    assert row is None


def test_unsigned_webhook_cannot_be_marked_processed(conn: psycopg.Connection) -> None:
    conn.execute(
        "INSERT INTO payment_webhook_events (provider, provider_event_id, event_type, signature_valid, payload) "
        "VALUES ('test', 'evt_forged', 'payment.succeeded', false, '{}')"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "UPDATE payment_webhook_events SET processed_at = now() WHERE provider_event_id = 'evt_forged'"
        )


def test_order_has_at_most_one_successful_payment(
    conn: psycopg.Connection, factory: Factory
) -> None:
    order, _ = factory.order(factory.customer())
    _payment(conn, order, "pay_failed_1", status="failed")
    _payment(conn, order, "pay_ok_1")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _payment(conn, order, "pay_ok_2")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _payment(conn, order, "pay_ok_1", status="failed")  # aynı sağlayıcı kimliği


def test_order_totals_must_add_up(conn: psycopg.Connection, factory: Factory) -> None:
    customer = factory.customer()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO orders (customer_id, currency, subtotal_minor, tax_minor, total_minor, payment_provider) "
            "VALUES (%s, 'USD', 1000, 200, 1000, 'test')",
            (customer,),
        )


def test_refund_cannot_exceed_payment(conn: psycopg.Connection, factory: Factory) -> None:
    order, _ = factory.order(factory.customer())
    _payment(conn, order, "pay_1")
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "UPDATE payments SET refunded_minor = 2000 WHERE provider_payment_id = 'pay_1'"
        )


def test_email_outbox_never_stores_license_keys(conn: psycopg.Connection) -> None:
    conn.execute(
        "INSERT INTO email_outbox (dedupe_key, to_email, template, payload) "
        "VALUES ('license:1', 'a@example.com', 'license_delivery', %s)",
        (Jsonb({"license_id": "uuid"}),),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "INSERT INTO email_outbox (dedupe_key, to_email, template) "
            "VALUES ('license:1', 'a@example.com', 'license_delivery')"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO email_outbox (dedupe_key, to_email, template, payload) "
            "VALUES ('license:2', 'a@example.com', 'license_delivery', %s)",
            (Jsonb({"license_key": "ATI-7XK9-PQ82-MN45-ZR61"}),),
        )


def test_customer_email_unique_case_insensitive(conn: psycopg.Connection, factory: Factory) -> None:
    factory.customer("Ali@Example.com")
    with pytest.raises(psycopg.errors.UniqueViolation):
        factory.customer("ali@example.COM")


def test_password_must_be_argon2id(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO customers (email, password_hash) VALUES ('x@example.com', 'düz-parola')"
        )


def test_blocked_customer_needs_timestamp(conn: psycopg.Connection, factory: Factory) -> None:
    customer = factory.customer()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE customers SET status = 'blocked' WHERE id = %s", (customer,))
    conn.execute(
        "UPDATE customers SET status = 'blocked', blocked_at = now(), blocked_reason = 'dolandırıcılık' "
        "WHERE id = %s",
        (customer,),
    )


# --- Yöneticiler ---------------------------------------------------------------------------


def test_admin_cannot_be_active_without_2fa(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO admin_users (email, full_name, password_hash, status) "
            "VALUES ('root@example.com', 'Kök', %s, 'active')",
            (ARGON2_HASH,),
        )
    admin = conn.execute(
        "INSERT INTO admin_users (email, full_name, password_hash) "
        "VALUES ('root@example.com', 'Kök', %s) RETURNING id",
        (ARGON2_HASH,),
    ).fetchone()
    assert admin
    conn.execute(
        "UPDATE admin_users SET status = 'active', totp_secret_enc = %s, totp_confirmed_at = now() "
        "WHERE id = %s",
        (secrets.token_bytes(40), admin[0]),
    )


def test_admin_session_requires_mfa_and_short_lifetime(conn: psycopg.Connection) -> None:
    admin = conn.execute(
        "INSERT INTO admin_users (email, full_name, password_hash) VALUES ('a@example.com', 'A', %s) "
        "RETURNING id",
        (ARGON2_HASH,),
    ).fetchone()
    assert admin
    with pytest.raises(psycopg.errors.NotNullViolation):
        conn.execute(
            "INSERT INTO admin_sessions (admin_id, token_hash, expires_at) "
            "VALUES (%s, %s, now() + interval '1 hour')",
            (admin[0], secrets.token_bytes(32)),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO admin_sessions (admin_id, token_hash, mfa_verified_at, expires_at) "
            "VALUES (%s, %s, now(), now() + interval '30 days')",
            (admin[0], secrets.token_bytes(32)),
        )


def test_effective_permissions_only_for_active_admins(
    conn: psycopg.Connection, scalar: Callable[..., Any]
) -> None:
    admin = conn.execute(
        "INSERT INTO admin_users (email, full_name, password_hash) VALUES ('s@example.com', 'S', %s) "
        "RETURNING id",
        (ARGON2_HASH,),
    ).fetchone()
    assert admin
    conn.execute(
        "INSERT INTO admin_user_roles (admin_id, role_code) VALUES (%s, 'support')", (admin[0],)
    )
    count_sql = "SELECT count(*) FROM admin_effective_permissions WHERE admin_id = %s"
    assert scalar(count_sql, (admin[0],)) == 0  # henüz 2FA kurulmadı -> 'invited'
    conn.execute(
        "UPDATE admin_users SET status = 'active', totp_secret_enc = %s, totp_confirmed_at = now() "
        "WHERE id = %s",
        (secrets.token_bytes(40), admin[0]),
    )
    assert scalar(count_sql, (admin[0],)) == 6  # destek: 5 temel + forum onayı (0014)
    assert (
        scalar(
            "SELECT count(*) FROM admin_effective_permissions WHERE admin_id = %s "
            "AND permission_code = 'payment.refund'",
            (admin[0],),
        )
        == 0
    )


# --- Denetim kaydı ---------------------------------------------------------------------------


def _audit(conn: psycopg.Connection, action: str, details: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_log (actor_type, actor_id, action, target_type, target_id, details) "
        "VALUES ('admin', 'admin-1', %s, 'license', 'l-1', %s)",
        (action, Jsonb(details or {})),
    )


def test_audit_chain_verifies(conn: psycopg.Connection, scalar: Callable[..., Any]) -> None:
    for i in range(10):
        _audit(conn, "license.freeze", {"i": i, "neden": "şüpheli"})
    assert scalar("SELECT audit_log_verify()") is None
    first = conn.execute("SELECT prev_hash FROM audit_log ORDER BY id LIMIT 1").fetchone()
    assert first == (bytes(32),)


def test_audit_log_is_append_only(conn: psycopg.Connection) -> None:
    _audit(conn, "license.cancel")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE audit_log SET actor_id = 'saldırgan'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM audit_log")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("TRUNCATE audit_log")


def test_audit_tamper_detected(conn: psycopg.Connection, scalar: Callable[..., Any]) -> None:
    for i in range(3):
        _audit(conn, "customer.block", {"i": i})
    # Veritabanı süper kullanıcısı tetikleyiciyi devre dışı bırakıp kaydı değiştirse bile:
    conn.execute("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_log_immutable")
    second_id = scalar("SELECT id FROM audit_log ORDER BY id OFFSET 1 LIMIT 1")
    conn.execute(
        "UPDATE audit_log SET details = '{\"i\": 99}' WHERE id = %s",
        (second_id,),
    )
    assert scalar("SELECT audit_log_verify()") == second_id


def test_audit_action_format(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        _audit(conn, "Herhangi Bir Şey")
