from __future__ import annotations

import threading
import uuid

import psycopg
import pytest

from tests.conftest import Factory


def _sold_license(factory: Factory, plan: str = "d30_1dev") -> tuple[uuid.UUID, uuid.UUID]:
    customer = factory.customer()
    _, item = factory.order(customer, plan=plan)
    lic = factory.license(plan=plan)
    factory.sell(lic, customer, item)
    return lic, customer


def test_device_limit_enforced_per_platform(factory: Factory, conn: psycopg.Connection) -> None:
    lic, customer = _sold_license(factory, plan="d30_2dev")
    factory.activate(lic, factory.device(customer, "windows"))
    factory.activate(lic, factory.device(customer, "windows"))
    with pytest.raises(psycopg.errors.CheckViolation, match="Cihaz limiti"):
        factory.activate(lic, factory.device(customer, "windows"))
    # iOS eşlikçi cihazlar ayrı limitle sayılır (varsayılan 2).
    factory.activate(lic, factory.device(customer, "ios"))
    factory.activate(lic, factory.device(customer, "ios"))
    with pytest.raises(psycopg.errors.CheckViolation, match="Cihaz limiti"):
        factory.activate(lic, factory.device(customer, "ios"))


def test_deactivation_frees_a_slot(factory: Factory, conn: psycopg.Connection) -> None:
    lic, customer = _sold_license(factory)
    activation = factory.activate(lic, factory.device(customer))
    with pytest.raises(psycopg.errors.CheckViolation):
        factory.activate(lic, factory.device(customer))
    conn.execute(
        "UPDATE license_activations SET deactivated_at = now(), deactivated_by = 'customer' "
        "WHERE id = %s",
        (activation,),
    )
    factory.activate(lic, factory.device(customer))


def test_cannot_activate_someone_elses_license(factory: Factory) -> None:
    lic, _ = _sold_license(factory)
    stranger = factory.customer()
    with pytest.raises(psycopg.errors.CheckViolation, match="aynı müşteriye"):
        factory.activate(lic, factory.device(stranger))


@pytest.mark.parametrize("status", ["ready_for_sale", "generated"])
def test_unsold_license_cannot_be_activated(factory: Factory, status: str) -> None:
    lic = factory.license(status=status)
    customer = factory.customer()
    with pytest.raises(psycopg.errors.CheckViolation):
        factory.activate(lic, factory.device(customer))


def test_frozen_license_cannot_be_activated(factory: Factory, conn: psycopg.Connection) -> None:
    lic, customer = _sold_license(factory)
    conn.execute("UPDATE licenses SET status = 'frozen' WHERE id = %s", (lic,))
    with pytest.raises(psycopg.errors.CheckViolation, match="frozen"):
        factory.activate(lic, factory.device(customer))


def test_revoked_device_cannot_be_activated(factory: Factory, conn: psycopg.Connection) -> None:
    lic, customer = _sold_license(factory)
    device = factory.device(customer)
    conn.execute("UPDATE devices SET revoked_at = now() WHERE id = %s", (device,))
    with pytest.raises(psycopg.errors.CheckViolation, match="iptal"):
        factory.activate(lic, device)


def test_concurrent_activations_cannot_exceed_limit(dsn: str, factory: Factory) -> None:
    lic, customer = _sold_license(factory)  # 1 Windows cihazı hakkı
    devices = [factory.device(customer) for _ in range(5)]
    barrier = threading.Barrier(len(devices))
    successes: list[uuid.UUID] = []
    failures: list[str] = []
    lock = threading.Lock()

    def worker(device: uuid.UUID) -> None:
        with psycopg.connect(dsn, autocommit=True) as c:
            barrier.wait()
            try:
                c.execute(
                    "INSERT INTO license_activations (license_id, device_id) VALUES (%s, %s)",
                    (lic, device),
                )
            except psycopg.errors.CheckViolation as exc:
                with lock:
                    failures.append(str(exc))
            else:
                with lock:
                    successes.append(device)

    threads = [threading.Thread(target=worker, args=(d,)) for d in devices]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert len(successes) == 1
    assert len(failures) == 4


def test_pairing_rules(factory: Factory, conn: psycopg.Connection) -> None:
    customer, other = factory.customer(), factory.customer()
    pc, phone = factory.device(customer, "windows"), factory.device(customer, "ios")
    conn.execute(
        "INSERT INTO device_pairings (engine_device_id, companion_device_id) VALUES (%s, %s)",
        (pc, phone),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "INSERT INTO device_pairings (engine_device_id, companion_device_id) VALUES (%s, %s)",
            (pc, phone),
        )
    with pytest.raises(psycopg.errors.CheckViolation, match="Windows"):
        conn.execute(
            "INSERT INTO device_pairings (engine_device_id, companion_device_id) VALUES (%s, %s)",
            (phone, pc),
        )
    with pytest.raises(psycopg.errors.CheckViolation, match="aynı müşteriye"):
        conn.execute(
            "INSERT INTO device_pairings (engine_device_id, companion_device_id) VALUES (%s, %s)",
            (pc, factory.device(other, "ios")),
        )
