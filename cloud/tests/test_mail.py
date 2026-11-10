"""E-posta gönderimi: kuyruk → SMTP. Gerçek PostgreSQL ve gerçek smtplib (yerel sahte SMTP sunucusu)."""

from __future__ import annotations

import asyncio
import email
import email.policy
import smtplib
import threading
import time
from collections.abc import AsyncIterator, Iterator
from email.message import EmailMessage
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.types.json import Jsonb
from pydantic import SecretStr, ValidationError

from ati_cloud.accounts import Database
from ati_cloud.app import create_app
from ati_cloud.config import CloudSettings
from ati_cloud.mail import MAX_ATTEMPTS, PermanentError, process_once, render

ORIGIN = "http://localhost:3000"
PASSWORD = "Gizli-Parola-2026!"


class SmtpStub:
    """Ayrı iş parçacığında çalışan en küçük SMTP sunucusu (yalnızca test)."""

    def __init__(self) -> None:
        self.messages: list[tuple[list[str], bytes]] = []
        self.auth: list[str] = []
        self.auth_reply = "235 ok"
        self.mail_from_reply = "250 ok"
        self.loop = asyncio.new_event_loop()
        self.port = 0
        ready = threading.Event()

        def serve() -> None:
            asyncio.set_event_loop(self.loop)
            server = self.loop.run_until_complete(asyncio.start_server(self.handle, "127.0.0.1", 0))
            self.port = server.sockets[0].getsockname()[1]
            ready.set()
            self.loop.run_forever()

        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        ready.wait(5)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        def send(line: str) -> None:
            writer.write(f"{line}\r\n".encode())

        send("220 stub ESMTP")
        recipients: list[str] = []
        while True:
            await writer.drain()
            raw = await reader.readline()
            if not raw:
                break
            command = raw.decode().strip()
            upper = command.upper()
            if upper.startswith("EHLO"):
                writer.write(b"250-stub\r\n250 AUTH PLAIN LOGIN\r\n")
            elif upper.startswith("AUTH"):
                self.auth.append(command)
                send(self.auth_reply)
            elif upper.startswith("MAIL FROM"):
                send(self.mail_from_reply)
            elif upper.startswith("RCPT TO"):
                if "reddet" in command:
                    send("550 no such user")
                else:
                    recipients.append(command.split(":", 1)[1].strip(" <>"))
                    send("250 ok")
            elif upper == "DATA":
                send("354 end with .")
                await writer.drain()
                lines: list[bytes] = []
                while (line := await reader.readline()) not in (b".\r\n", b".\n", b""):
                    lines.append(line)
                self.messages.append((recipients, b"".join(lines)))
                recipients = []
                send("250 queued")
            elif upper == "QUIT":
                send("221 bye")
                await writer.drain()
                break
            else:
                send("250 ok")
        writer.close()

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


@pytest.fixture
def smtp() -> Iterator[SmtpStub]:
    stub = SmtpStub()
    yield stub
    stub.stop()


def settings_for(dsn: str, port: int, **extra: Any) -> CloudSettings:
    return CloudSettings(
        environment="test",
        database_url=SecretStr(dsn),
        session_cookie_secure=False,
        smtp_host="127.0.0.1",
        smtp_port=port,
        smtp_security="none",
        smtp_username="resend",
        smtp_password=SecretStr("re_deneme"),
        **extra,
    )


@pytest.fixture
async def db(dsn: str) -> AsyncIterator[Database]:
    database = Database(dsn, max_size=4)
    yield database
    await database.close()


def enqueue(conn: psycopg.Connection, to: str, template: str, payload: dict[str, Any]) -> Any:
    row = conn.execute(
        "INSERT INTO email_outbox (dedupe_key, to_email, template, payload) "
        "VALUES (gen_random_uuid()::text, %s, %s, %s) RETURNING id",
        (to, template, Jsonb(payload)),
    ).fetchone()
    assert row
    return row[0]


def state(conn: psycopg.Connection, outbox_id: Any) -> dict[str, Any]:
    row = conn.execute(
        "SELECT status::text, attempts, next_attempt_at > now() AS later, last_error, "
        "provider_message_id FROM email_outbox WHERE id = %s",
        (outbox_id,),
    ).fetchone()
    assert row
    return dict(zip(["status", "attempts", "later", "error", "message_id"], row, strict=True))


# --- Şablonlar ---------------------------------------------------------------------------------


def test_templates_render_links_and_escape_content() -> None:
    link = "https://canarslan.net.tr/eposta-dogrula?token=abc&x=<b>"
    mail = render("verify_email", {"link": link, "locale": "tr"}, "can@example.com")
    assert "doğrulayın" in mail.subject and link in mail.text
    assert "token=abc&amp;x=&lt;b&gt;" in mail.html and "<b>" not in mail.html
    for template in ("password_reset", "account_exists"):
        rendered = render(template, {"link": "https://canarslan.net.tr/giris"}, "a@example.com")
        assert "https://canarslan.net.tr/giris" in rendered.text
    delivery = render(
        "license_delivery",
        {
            "order_no": 1042,
            "license_ids": ["a", "b"],
            "panel_url": "https://canarslan.net.tr/panel",
        },
        "a@example.com",
    )
    assert "#1042" in delivery.subject and "2 lisans" in delivery.text
    assert "kazanç garantisi sunmaz" in delivery.text and "ATI-" not in delivery.text
    with pytest.raises(PermanentError):
        render("bilinmeyen", {}, "a@example.com")
    with pytest.raises(PermanentError):
        render("verify_email", {}, "a@example.com")


# --- Gerçek SMTP ile uçtan uca ------------------------------------------------------------------


async def test_registration_email_is_delivered_over_smtp(
    dsn: str, smtp: SmtpStub, conn: psycopg.Connection
) -> None:
    settings = settings_for(dsn, smtp.port)
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", headers={"Origin": ORIGIN}
    ) as http:
        response = await http.post(
            "/v1/auth/register",
            json={"email": "Can@Example.com", "password": PASSWORD, "accept_terms": True},
        )
        assert response.status_code == 202
    stats = await process_once(app.state.db, settings)
    again = await process_once(app.state.db, settings)  # gönderilen tekrar gönderilmez
    await app.state.db.close()
    assert stats == {"sent": 1, "retry": 0, "failed": 0, "expired": 0}
    assert again["sent"] == 0

    assert len(smtp.messages) == 1
    recipients, raw = smtp.messages[0]
    assert recipients == ["can@example.com"]
    message = email.message_from_bytes(raw, _class=EmailMessage, policy=email.policy.default)
    assert str(message["Subject"]).startswith("E-posta adresinizi doğrulayın")
    assert message["From"] == "AI Trading Intelligence <bildirim@canarslan.net.tr>"
    assert message.get_content_type() == "multipart/alternative"
    text = message.get_body(("plain",))
    assert text is not None and "/eposta-dogrula?token=" in text.get_content()
    assert smtp.auth and smtp.auth[0].upper().startswith("AUTH PLAIN")

    row = conn.execute(
        "SELECT status::text, sent_at IS NOT NULL, provider_message_id FROM email_outbox"
    ).fetchone()
    assert row is not None and row[0] == "sent" and row[1] and row[2] == message["Message-ID"]


async def test_rejected_recipient_is_not_retried(
    dsn: str, smtp: SmtpStub, db: Database, conn: psycopg.Connection
) -> None:
    good = enqueue(conn, "iyi@example.com", "password_reset", {"link": "https://x.test/s"})
    bad = enqueue(conn, "reddet@example.com", "password_reset", {"link": "https://x.test/s"})
    stats = await process_once(db, settings_for(dsn, smtp.port))
    assert stats["sent"] == 1 and stats["failed"] == 1
    assert state(conn, good)["status"] == "sent"
    rejected = state(conn, bad)
    assert rejected["status"] == "failed" and rejected["attempts"] == MAX_ATTEMPTS


async def test_unreachable_server_is_retried_later(
    dsn: str, db: Database, conn: psycopg.Connection
) -> None:
    import socket

    with socket.socket() as sock:  # kapalı bir port
        sock.bind(("127.0.0.1", 0))
        closed = sock.getsockname()[1]
    outbox = enqueue(conn, "a@example.com", "account_exists", {"link": "https://x.test/giris"})
    settings = settings_for(dsn, closed)
    stats = await process_once(db, settings)
    assert stats["retry"] == 1
    first = state(conn, outbox)
    assert first["status"] == "failed" and first["attempts"] == 1 and first["later"]
    assert "ConnectionRefused" in first["error"]
    # Bekleme süresi dolmadan tekrar denenmez.
    assert await process_once(db, settings) == {"sent": 0, "retry": 0, "failed": 0, "expired": 0}


async def test_expired_links_and_stale_leases(
    dsn: str, smtp: SmtpStub, db: Database, conn: psycopg.Connection
) -> None:
    old = enqueue(conn, "eski@example.com", "verify_email", {"link": "https://x.test/v"})
    conn.execute(
        "UPDATE email_outbox SET created_at = now() - interval '2 days' WHERE id = %s", (old,)
    )
    # Gönderirken çöken bir süreçten kalan kilit: süresi geçince yeniden alınır.
    stuck = enqueue(conn, "takili@example.com", "account_exists", {"link": "https://x.test/g"})
    conn.execute(
        "UPDATE email_outbox SET status = 'sending', attempts = 1, "
        "next_attempt_at = now() - interval '1 minute' WHERE id = %s",
        (stuck,),
    )
    stats = await process_once(db, settings_for(dsn, smtp.port))
    assert stats == {"sent": 1, "retry": 0, "failed": 0, "expired": 1}
    assert state(conn, old)["status"] == "failed" and "süresi" in state(conn, old)["error"]
    assert state(conn, stuck)["status"] == "sent" and state(conn, stuck)["attempts"] == 2
    assert [r for r, _ in smtp.messages] == [["takili@example.com"]]


async def test_parallel_senders_do_not_send_twice(
    dsn: str, db: Database, conn: psycopg.Connection
) -> None:
    for i in range(12):
        enqueue(conn, f"k{i}@example.com", "account_exists", {"link": "https://x.test/g"})
    sent: list[str] = []
    lock = threading.Lock()

    class SlowSender:
        def __init__(self, _settings: CloudSettings) -> None: ...

        def __enter__(self) -> SlowSender:
            return self

        def __exit__(self, *_: object) -> None: ...

        def send(self, message: EmailMessage) -> str:
            time.sleep(0.02)
            with lock:
                sent.append(str(message["To"]))
            return "<id@test>"

    settings = settings_for(dsn, 1)
    results = await asyncio.gather(
        process_once(db, settings, limit=5, sender_factory=SlowSender),
        process_once(db, settings, limit=5, sender_factory=SlowSender),
        process_once(db, settings, limit=5, sender_factory=SlowSender),
    )
    assert sum(r["sent"] for r in results) == 12
    assert sorted(sent) == sorted(f"k{i}@example.com" for i in range(12))


def test_production_requires_encrypted_smtp_and_valid_sender() -> None:
    from tests.test_app import SITE

    base = {
        "environment": "production",
        "database_url": SecretStr("postgresql://u:p@127.0.0.1/ati"),
        **SITE,
    }
    with pytest.raises(ValidationError, match="SMTP"):
        CloudSettings(**base, smtp_host="smtp.resend.com", smtp_security="none")
    with pytest.raises(ValidationError, match="ATI_MAIL_FROM"):
        CloudSettings(**base, mail_from="AI Trading Intelligence")
    ok = CloudSettings(**base, smtp_host="smtp.resend.com", smtp_port=465, smtp_security="ssl")
    assert ok.smtp_security == "ssl"


def test_smtp_errors_are_classified() -> None:
    from ati_cloud.mail import SmtpSender

    class Refusing:
        def send_message(self, _m: EmailMessage) -> None:
            raise smtplib.SMTPRecipientsRefused({"a@b": (550, b"no")})

    class Busy:
        def send_message(self, _m: EmailMessage) -> None:
            raise smtplib.SMTPDataError(451, b"try later")

    sender = SmtpSender.__new__(SmtpSender)
    message = EmailMessage()
    sender.smtp = Refusing()  # type: ignore[assignment]
    with pytest.raises(PermanentError):
        sender.send(message)
    sender.smtp = Busy()  # type: ignore[assignment]
    with pytest.raises(smtplib.SMTPDataError):
        sender.send(message)


# --- Teşhis (ati-cloud-mail test) -------------------------------------------------------------


def lines(steps: list[Any]) -> str:
    return "\n".join(step.line() for step in steps)


def mark_stuck(conn: psycopg.Connection, outbox_id: Any, error: str) -> None:
    conn.execute(
        "UPDATE email_outbox SET status = 'failed', attempts = %s, last_error = %s WHERE id = %s",
        (MAX_ATTEMPTS, error, outbox_id),
    )


async def test_diagnosis_succeeds_and_requeues_stuck_mail(
    dsn: str, smtp: SmtpStub, db: Database
) -> None:
    """Ayar düzelince teşhis deneme e-postası gönderir ve ayar hatası yüzünden takılmış
    e-postaları yeniden kuyruğa alır; alıcı reddi ve süresi dolmuş bağlantı alınmaz."""
    from ati_cloud.mail_check import diagnose

    with psycopg.connect(dsn, autocommit=True) as conn:
        stuck = enqueue(
            conn, "takildi@ornek.com", "account_exists", {"link": "https://x.test/giris"}
        )
        mark_stuck(conn, stuck, "SMTP 550: The canarslan.net.tr domain is not verified")
        refused = enqueue(conn, "yok@ornek.com", "account_exists", {"link": "https://x.test/giris"})
        mark_stuck(conn, refused, "alıcı reddedildi")
    settings = settings_for(dsn, smtp.port)
    sent, steps = await asyncio.to_thread(diagnose, settings, "yonetici@ornek.com")
    text = lines(steps)
    assert sent, text
    assert "[HATA]" not in text.split("Kuyruk:")[0]
    assert "Deneme e-postası sağlayıcıya teslim edildi" in text
    assert "1 takılmış e-posta" in text
    assert "re_deneme" not in text  # API anahtarı yazdırılmaz
    assert smtp.messages[-1][0] == ["yonetici@ornek.com"]

    assert (await process_once(db, settings))["sent"] == 1
    with psycopg.connect(dsn) as conn:
        assert state(conn, stuck)["status"] == "sent"
        assert state(conn, refused)["status"] == "failed"


async def test_diagnosis_finds_blocked_port_and_suggests_open_one(dsn: str, smtp: SmtpStub) -> None:
    from ati_cloud.mail_check import diagnose

    class Sock:
        def close(self) -> None: ...

    def connect(address: tuple[str, int], _timeout: float) -> Sock:
        if address[1] == 2465:
            return Sock()
        raise TimeoutError("engelli")

    settings = settings_for(dsn, 465)
    sent, steps = await asyncio.to_thread(diagnose, settings, "a@ornek.com", connect=connect)
    text = lines(steps)
    assert not sent
    assert "[HATA] 127.0.0.1:465 bağlantısı kurulamadı" in text
    assert "Açık portlar: 2465" in text and "Port: 2465" in text


async def test_diagnosis_explains_rejected_key_and_unverified_domain(
    dsn: str, smtp: SmtpStub
) -> None:
    from ati_cloud.mail_check import diagnose

    settings = settings_for(dsn, smtp.port)
    smtp.auth_reply = "535 Invalid API key"
    sent, steps = await asyncio.to_thread(diagnose, settings, "a@ornek.com")
    assert not sent and "Oturum açılamadı (SMTP 535: Invalid API key)" in lines(steps)
    assert "API Keys" in lines(steps)

    smtp.auth_reply = "235 ok"
    smtp.mail_from_reply = "550 The canarslan.net.tr domain is not verified"
    sent, steps = await asyncio.to_thread(diagnose, settings, "a@ornek.com")
    text = lines(steps)
    assert not sent and "Gönderen adresi reddedildi (SMTP 550" in text
    assert "'Verified' olmalı" in text


async def test_unverified_sender_keeps_mail_retryable(
    dsn: str, smtp: SmtpStub, db: Database
) -> None:
    """Gönderen alan adı doğrulanmamışsa (ayar hatası) e-posta kaybolmaz, yeniden denenir."""
    smtp.mail_from_reply = "550 The canarslan.net.tr domain is not verified"
    with psycopg.connect(dsn, autocommit=True) as conn:
        outbox_id = enqueue(
            conn, "musteri@ornek.com", "account_exists", {"link": "https://x.test/giris"}
        )
    stats = await process_once(db, settings_for(dsn, smtp.port))
    assert stats["retry"] == 1 and stats["failed"] == 0
    with psycopg.connect(dsn) as conn:
        row = state(conn, outbox_id)
    assert row["status"] == "failed" and row["attempts"] == 1 and row["later"]
    assert "domain is not verified" in row["error"]


def test_config_errors_are_not_permanent() -> None:
    from ati_cloud.mail import SmtpSender

    class Raising:
        def __init__(self, exc: Exception) -> None:
            self.exc = exc

        def send_message(self, _m: EmailMessage) -> None:
            raise self.exc

    sender = SmtpSender.__new__(SmtpSender)
    sender.smtp = Raising(smtplib.SMTPDataError(550, b"The domain is not verified"))  # type: ignore[assignment]
    with pytest.raises(smtplib.SMTPDataError):
        sender.send(EmailMessage())
    sender.smtp = Raising(smtplib.SMTPDataError(552, b"Message too large"))  # type: ignore[assignment]
    with pytest.raises(PermanentError, match="552: Message too large"):
        sender.send(EmailMessage())


def test_cli_test_command_prints_steps(
    dsn: str, smtp: SmtpStub, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from ati_cloud.mail import main

    for key, value in {
        "ATI_ENVIRONMENT": "test",
        "ATI_DATABASE_URL": dsn,
        "ATI_SMTP_HOST": "127.0.0.1",
        "ATI_SMTP_PORT": str(smtp.port),
        "ATI_SMTP_SECURITY": "none",
        "ATI_SMTP_USERNAME": "resend",
        "ATI_SMTP_PASSWORD": "re_deneme",
    }.items():
        monkeypatch.setenv(key, value)
    assert main(["test", "--to", "yonetici@ornek.com"]) == 0
    out = capsys.readouterr().out
    assert "E-posta teşhisi → y***@ornek.com" in out
    assert "Sonuç: e-posta gönderimi çalışıyor." in out
