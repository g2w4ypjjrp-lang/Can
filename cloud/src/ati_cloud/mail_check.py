"""E-posta gönderiminin adım adım teşhisi (``ati-cloud-mail test --to <adres>``).

Sunucu yöneticisinin anlayacağı Türkçe çıktı verir; her adım başarısızsa nedenini ve ne
yapılacağını yazar:

1. Ayarlar (sunucu, port, güvenlik, kullanıcı, parola tanımlı mı, gönderen adresi)
2. Sunucu adının çözülmesi (DNS)
3. Porta bağlantı. Kurulamıyorsa diğer SMTP portları denenir: birçok VDS sağlayıcısı 465/587'yi
   kapatır; Resend 2465 (SSL) ve 2587 (STARTTLS) portlarını da kabul eder.
4. TLS ve oturum açma (API anahtarı)
5. Deneme e-postası (gönderen alan adı doğrulanmış mı, alıcı kabul edildi mi)
6. Kuyruk durumu (bekleyen/başarısız sayıları, son hata). Gönderim başarılıysa ayar hatası
   yüzünden takılan e-postalar yeniden kuyruğa alınır.

Parola/API anahtarı hiçbir zaman yazdırılmaz.
"""

from __future__ import annotations

import smtplib
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any

from ati_cloud.accounts import Database
from ati_cloud.config import CloudSettings
from ati_cloud.loop import run

SMTP_PORTS = {465: "ssl", 587: "starttls", 2465: "ssl", 2587: "starttls"}
REQUEUE_WINDOW = "3 days"


@dataclass
class Step:
    ok: bool
    title: str
    detail: str = ""

    def line(self) -> str:
        mark = "[ OK ]" if self.ok else "[HATA]"
        return f"{mark} {self.title}" + (f"\n       {self.detail}" if self.detail else "")


Connector = Callable[[tuple[str, int], float], Any]


def _connect(address: tuple[str, int], timeout: float) -> Any:
    return socket.create_connection(address, timeout=timeout)


def _reachable(host: str, port: int, connect: Connector, timeout: float) -> bool:
    try:
        connect((host, port), timeout).close()
    except OSError:
        return False
    return True


def _hint_for(text: str) -> str:
    low = text.lower()
    if "testing" in low or "own email" in low:
        return (
            "Resend alan adınız doğrulanmadan yalnızca kendi adresinize gönderir. "
            "Resend → Domains → canarslan.net.tr durumu 'Verified' olmalı."
        )
    if "domain" in low or "verif" in low:
        return (
            "Gönderen alan adı sağlayıcıda doğrulanmamış. Resend → Domains → canarslan.net.tr "
            "'Verified' olmalı; Cloudflare DNS kayıtlarını Resend'in gösterdiğiyle karşılaştırın."
        )
    if "api key" in low or "invalid" in low or "auth" in low:
        return "API anahtarı geçersiz ya da silinmiş. Resend → API Keys → yeni anahtar oluşturun."
    return ""


def _settings_step(settings: CloudSettings) -> Step:
    missing = []
    if not settings.smtp_host:
        missing.append("SMTP sunucusu (ATI_SMTP_HOST)")
    if settings.smtp_username and not settings.smtp_password:
        missing.append("API anahtarı / parola (ATI_SMTP_PASSWORD)")
    sender = parseaddr(settings.mail_from)[1]
    if "@" not in sender:
        missing.append("gönderen adresi (ATI_MAIL_FROM)")
    if missing:
        return Step(
            False,
            "Ayarlar eksik: " + ", ".join(missing),
            "Sunucuda: yonet.ps1 eposta-ayarla",
        )
    return Step(
        True,
        f"Ayarlar: {settings.smtp_host}:{settings.smtp_port} ({settings.smtp_security}), "
        f"kullanıcı {settings.smtp_username or '-'}, anahtar tanımlı, gönderen {sender}",
    )


def check_smtp(
    settings: CloudSettings,
    to: str,
    *,
    connect: Connector = _connect,
    timeout: float = 10.0,
) -> list[Step]:
    """SMTP tarafını adım adım dener; ilk başarısız adımda durur."""
    from ati_cloud.mail import Mail, SmtpSender, _html, _text, build_message, smtp_text

    steps = [_settings_step(settings)]
    if not steps[-1].ok:
        return steps
    host, port = settings.smtp_host or "", settings.smtp_port

    try:
        socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        steps.append(Step(True, f"Sunucu adı çözüldü: {host}"))
    except OSError:
        steps.append(
            Step(
                False,
                f"Sunucu adı çözülemedi: {host}",
                "Sunucunun internet/DNS bağlantısını ve adın yazımını kontrol edin.",
            )
        )
        return steps

    if not _reachable(host, port, connect, timeout):
        others = [p for p in SMTP_PORTS if p != port and _reachable(host, p, connect, timeout)]
        detail = f"Sunucu sağlayıcınız (VDS) {port} numaralı portu engelliyor olabilir."
        if others:
            detail += (
                f" Açık portlar: {', '.join(map(str, others))}. Çözüm: yonet.ps1 eposta-ayarla → "
                f"Port: {others[0]}"
            )
        else:
            detail += (
                " Hiçbir SMTP portu açık değil: sağlayıcınızdan giden 465/587/2465/2587 "
                "bağlantılarının açılmasını isteyin; Windows Güvenlik Duvarı giden kurallarını da "
                "kontrol edin."
            )
        steps.append(Step(False, f"{host}:{port} bağlantısı kurulamadı", detail))
        return steps
    steps.append(Step(True, f"{host}:{port} bağlantısı açık"))

    try:
        sender = SmtpSender(settings).__enter__()
    except smtplib.SMTPAuthenticationError as exc:
        steps.append(
            Step(
                False,
                f"Oturum açılamadı (SMTP {exc.smtp_code}: {smtp_text(exc)})",
                "API anahtarı yanlış, silinmiş ya da gönderme izni yok. Resend → API Keys → "
                "yeni anahtar ('Sending access') → yonet.ps1 eposta-ayarla. Kullanıcı adı "
                "'resend' olmalı.",
            )
        )
        return steps
    except (ssl.SSLError, smtplib.SMTPServerDisconnected, ConnectionError) as exc:
        expected = SMTP_PORTS.get(port)
        mismatch = expected is not None and expected != settings.smtp_security
        steps.append(
            Step(
                False,
                f"Şifreli bağlantı kurulamadı ({type(exc).__name__})",
                f"Port ile güvenlik türü uyuşmuyor olabilir: 465/2465 = ssl, 587/2587 = starttls "
                f"(şu an {port} = {settings.smtp_security}"
                + (f", olması gereken {expected}" if mismatch else "")
                + "). yonet.ps1 eposta-ayarla ile yeniden ayarlayın.",
            )
        )
        return steps
    except smtplib.SMTPException as exc:
        steps.append(Step(False, f"SMTP sunucusu hata verdi: {exc}"))
        return steps
    except OSError as exc:
        steps.append(Step(False, f"Bağlantı koptu: {type(exc).__name__}: {exc}"))
        return steps
    steps.append(Step(True, "Şifreli bağlantı ve oturum açma başarılı (API anahtarı geçerli)"))

    mail = Mail(
        to=to,
        subject="Deneme e-postası — AI Trading Intelligence",
        text=_text("E-posta gönderimi çalışıyor", ["Bu bir deneme e-postasıdır."], None),
        html=_html("E-posta gönderimi çalışıyor", ["Bu bir deneme e-postasıdır."], None, None),
    )
    try:
        assert sender.smtp is not None  # noqa: S101
        sender.smtp.send_message(build_message(mail, settings))
        steps.append(
            Step(
                True,
                "Deneme e-postası sağlayıcıya teslim edildi",
                "Gelen kutusunu ve İstenmeyen/Spam klasörünü kontrol edin. Gelmezse "
                "Resend → Emails sayfasında durumuna bakın.",
            )
        )
    except smtplib.SMTPRecipientsRefused as exc:
        code, raw = next(iter(exc.recipients.values()))
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        steps.append(Step(False, f"Alıcı reddedildi (SMTP {code}: {text[:200]})", _hint_for(text)))
    except smtplib.SMTPResponseException as exc:
        text = smtp_text(exc)
        title = (
            "Gönderen adresi reddedildi"
            if isinstance(exc, smtplib.SMTPSenderRefused)
            else "Gönderim reddedildi"
        )
        steps.append(Step(False, f"{title} (SMTP {exc.smtp_code}: {text})", _hint_for(text)))
    except (smtplib.SMTPException, OSError) as exc:
        steps.append(Step(False, f"Gönderim yarıda kaldı: {type(exc).__name__}: {exc}"))
    finally:
        sender.__exit__(None, None, None)
    return steps


async def queue_report(settings: CloudSettings, *, requeue: bool) -> list[Step]:
    """Kuyruk özeti. ``requeue`` ise ayar hatası yüzünden takılmış son e-postalar yeniden
    denenir."""
    db = Database(settings.database_dsn, max_size=1)
    try:
        async with db.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT status::text AS status, count(*) AS n FROM email_outbox GROUP BY status"
                )
            ).fetchall()
            counts = {str(r["status"]): int(r["n"]) for r in rows}
            last = await (
                await conn.execute(
                    "SELECT last_error FROM email_outbox WHERE last_error IS NOT NULL "
                    "AND status <> 'sent' ORDER BY created_at DESC LIMIT 1"
                )
            ).fetchone()
            requeued = 0
            if requeue:
                async with conn.transaction():
                    cur = await conn.execute(
                        "UPDATE email_outbox SET status = 'pending', attempts = 0, "
                        "next_attempt_at = now() WHERE status = 'failed' "
                        "AND created_at > now() - %s::interval "
                        "AND coalesce(last_error, '') NOT LIKE %s "
                        "AND coalesce(last_error, '') <> %s",
                        (REQUEUE_WINDOW, "alıcı reddedildi%", "bağlantının süresi doldu"),
                    )
                    requeued = cur.rowcount
    except Exception as exc:  # veritabanı kapalıysa SMTP teşhisi yine de işe yarar
        return [Step(False, f"Kuyruk okunamadı (veritabanı): {type(exc).__name__}")]
    finally:
        await db.close()

    pending = counts.get("pending", 0) + counts.get("sending", 0)
    failed = counts.get("failed", 0)
    summary = f"Kuyruk: gönderilen {counts.get('sent', 0)}, bekleyen {pending}, başarısız {failed}"
    steps = [
        Step(
            failed == 0 or requeued > 0,
            summary,
            f"Son hata: {last['last_error']}" if last else "",
        )
    ]
    if requeued:
        steps.append(
            Step(
                True,
                f"{requeued} takılmış e-posta yeniden gönderilmek üzere kuyruğa alındı",
                "E-posta servisi birkaç saniye içinde gönderir "
                "(yonet.ps1 durum: Eposta 'Running' olmalı).",
            )
        )
    return steps


def diagnose(
    settings: CloudSettings, to: str, *, connect: Connector = _connect
) -> tuple[bool, list[Step]]:
    steps = check_smtp(settings, to, connect=connect)
    sent = all(s.ok for s in steps)
    steps += run(queue_report(settings, requeue=sent))
    return sent, steps
