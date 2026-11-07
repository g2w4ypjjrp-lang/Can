from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from typing import Any

import psycopg
import pytest

from tests.conftest import Factory


def test_serial_sequence_capacity_is_9_999_999_999(scalar: Callable[..., Any]) -> None:
    assert (
        scalar("SELECT seqmax FROM pg_sequence WHERE seqrelid = 'license_serial_seq'::regclass")
        == 9_999_999_999
    )


def test_serial_sequence_never_cycles(conn: psycopg.Connection, factory: Factory) -> None:
    conn.execute("SELECT setval('license_serial_seq', 9999999999)")
    with pytest.raises(psycopg.errors.SequenceGeneratorLimitExceeded):
        factory.license()


def test_key_hash_is_unique(conn: psycopg.Connection) -> None:
    key_hash = secrets.token_bytes(32)
    sql = (
        "INSERT INTO licenses (key_hash, key_ciphertext, key_hint, plan_code, device_limit, "
        "companion_device_limit) VALUES (%s, %s, 'ATI-****-****-****-AB12', 'd30_1dev', 1, 2)"
    )
    conn.execute(sql, (key_hash, secrets.token_bytes(60)))
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(sql, (key_hash, secrets.token_bytes(60)))


def test_key_hint_never_contains_full_key(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO licenses (key_hash, key_ciphertext, key_hint, plan_code, device_limit, "
            "companion_device_limit) VALUES (%s, %s, 'ATI-7XK9-PQ82-MN45-ZR61', 'd30_1dev', 1, 2)",
            (secrets.token_bytes(32), secrets.token_bytes(60)),
        )


def test_full_lifecycle_is_recorded(
    conn: psycopg.Connection, factory: Factory, scalar: Callable[..., Any]
) -> None:
    customer = factory.customer()
    _, item = factory.order(customer)
    lic = factory.license(status="generated")
    conn.execute("UPDATE licenses SET status = 'ready_for_sale' WHERE id = %s", (lic,))
    factory.sell(lic, customer, item)
    conn.execute(
        "UPDATE licenses SET status = 'active', activated_at = now(), "
        "expires_at = now() + interval '30 days' WHERE id = %s",
        (lic,),
    )
    conn.execute("UPDATE licenses SET status = 'expired' WHERE id = %s", (lic,))
    conn.execute(
        "UPDATE licenses SET status = 'active', expires_at = now() + interval '30 days' WHERE id = %s",
        (lic,),
    )
    history = conn.execute(
        "SELECT from_status::text, to_status::text FROM license_events WHERE license_id = %s ORDER BY id",
        (lic,),
    ).fetchall()
    assert history == [
        (None, "generated"),
        ("generated", "ready_for_sale"),
        ("ready_for_sale", "sold"),
        ("sold", "active"),
        ("active", "expired"),
        ("expired", "active"),
    ]
    assert scalar("SELECT version FROM licenses WHERE id = %s", (lic,)) == 6


@pytest.mark.parametrize(
    ("start", "target"),
    [
        ("ready_for_sale", "active"),  # satılmadan aktif olamaz
        ("ready_for_sale", "expired"),
        ("generated", "active"),
    ],
)
def test_invalid_transitions_rejected(
    conn: psycopg.Connection, factory: Factory, start: str, target: str
) -> None:
    lic = factory.license(status=start)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE licenses SET status = %s WHERE id = %s", (target, lic))


def test_cancelled_is_terminal(conn: psycopg.Connection, factory: Factory) -> None:
    lic = factory.license()
    conn.execute(
        "UPDATE licenses SET status = 'cancelled', cancel_reason = 'test' WHERE id = %s", (lic,)
    )
    for target in ("ready_for_sale", "sold", "active", "frozen"):
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE licenses SET status = %s WHERE id = %s", (target, lic))


def test_sold_license_cannot_be_sold_again(conn: psycopg.Connection, factory: Factory) -> None:
    """Aynı lisans ikinci kez satılamaz: ne havuza döner ne de başka müşteriye geçer."""
    alice, bob = factory.customer(), factory.customer()
    _, item_a = factory.order(alice)
    _, item_b = factory.order(bob)
    lic = factory.license()
    factory.sell(lic, alice, item_a)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE licenses SET status = 'ready_for_sale' WHERE id = %s", (lic,))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "UPDATE licenses SET customer_id = %s, order_item_id = %s WHERE id = %s",
            (bob, item_b, lic),
        )


def test_one_license_per_order_unit(conn: psycopg.Connection, factory: Factory) -> None:
    """Ödeme bildirimi iki kez işlense bile aynı sipariş birimine ikinci lisans atanamaz."""
    customer = factory.customer()
    _, item = factory.order(customer, quantity=2)
    first, second, third = factory.license(), factory.license(), factory.license()
    factory.sell(first, customer, item, unit=1)
    factory.sell(second, customer, item, unit=2)
    with pytest.raises(psycopg.errors.UniqueViolation):
        factory.sell(third, customer, item, unit=1)
    with pytest.raises(psycopg.errors.CheckViolation):
        factory.sell(third, customer, item, unit=3)  # kalemde yalnızca 2 lisans var


def test_sold_requires_owner(conn: psycopg.Connection, factory: Factory) -> None:
    lic = factory.license()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE licenses SET status = 'sold', sold_at = now() WHERE id = %s", (lic,))


def test_freeze_and_unfreeze_restores_previous_state(
    conn: psycopg.Connection, factory: Factory, scalar: Callable[..., Any]
) -> None:
    customer = factory.customer()
    _, item = factory.order(customer)
    lic = factory.license()
    factory.sell(lic, customer, item)
    conn.execute(
        "UPDATE licenses SET status = 'active', activated_at = now(), "
        "expires_at = now() + interval '30 days' WHERE id = %s",
        (lic,),
    )
    conn.execute(
        "UPDATE licenses SET status = 'frozen', frozen_reason = 'şüpheli kullanım' WHERE id = %s",
        (lic,),
    )
    assert (
        scalar("SELECT status_before_freeze::text FROM licenses WHERE id = %s", (lic,)) == "active"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE licenses SET status = 'sold' WHERE id = %s", (lic,))
    conn.execute("UPDATE licenses SET status = 'active' WHERE id = %s", (lic,))
    row = conn.execute(
        "SELECT frozen_at, status_before_freeze, frozen_reason FROM licenses WHERE id = %s", (lic,)
    ).fetchone()
    assert row == (None, None, None)
    reasons = conn.execute(
        "SELECT details->>'frozen_reason' FROM license_events WHERE license_id = %s AND to_status = 'frozen'",
        (lic,),
    ).fetchone()
    assert reasons == ("şüpheli kullanım",)


def test_key_material_is_immutable(conn: psycopg.Connection, factory: Factory) -> None:
    lic = factory.license()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "UPDATE licenses SET key_hash = %s WHERE id = %s", (secrets.token_bytes(32), lic)
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE licenses SET serial = serial + 1 WHERE id = %s", (lic,))


def test_actor_is_recorded_in_history(dsn: str, factory: Factory) -> None:
    lic = factory.license()
    with psycopg.connect(dsn) as tx:
        tx.execute("SET LOCAL ati.actor_type = 'admin'")
        tx.execute("SET LOCAL ati.actor_id = 'admin-42'")
        tx.execute("UPDATE licenses SET status = 'cancelled' WHERE id = %s", (lic,))
        tx.commit()
    row = factory.conn.execute(
        "SELECT actor_type::text, actor_id FROM license_events WHERE license_id = %s AND to_status = 'cancelled'",
        (lic,),
    ).fetchone()
    assert row == ("admin", "admin-42")


def test_license_events_are_append_only(conn: psycopg.Connection, factory: Factory) -> None:
    factory.license()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM license_events")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE license_events SET actor_id = 'x'")


def test_pool_allocation_is_race_free(dsn: str, factory: Factory) -> None:
    """İki eşzamanlı satış aynı havuz lisansını alamaz (FOR UPDATE SKIP LOCKED deseni)."""
    customer = factory.customer()
    _, item = factory.order(customer, quantity=2)
    pool = {factory.license(), factory.license()}
    barrier = threading.Barrier(2)
    taken: list[Any] = []
    errors: list[BaseException] = []

    def worker(unit: int) -> None:
        try:
            with psycopg.connect(dsn) as tx:
                barrier.wait()
                row = tx.execute(
                    "SELECT id FROM licenses WHERE status = 'ready_for_sale' AND plan_code = 'd30_1dev' "
                    "ORDER BY serial LIMIT 1 FOR UPDATE SKIP LOCKED"
                ).fetchone()
                assert row is not None
                tx.execute(
                    "UPDATE licenses SET status = 'sold', customer_id = %s, order_item_id = %s, "
                    "order_item_unit = %s, sold_at = now() WHERE id = %s",
                    (customer, item, unit, row[0]),
                )
                tx.commit()
                taken.append(row[0])
        except BaseException as exc:  # pragma: no cover - teşhis için
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(unit,)) for unit in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors
    assert set(taken) == pool
