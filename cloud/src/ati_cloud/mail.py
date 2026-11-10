"""E-posta gönderimi: ``email_outbox`` kuyruğu → SMTP (``ati-cloud-mail``).

Uygulama e-postaları doğrudan göndermez; aynı veritabanı işleminde kuyruğa yazar (kayıt, parola
sıfırlama, lisans teslimi). Bu süreç kuyruğu işler:

* Satırlar ``FOR UPDATE SKIP LOCKED`` ile alınır (birden çok gönderici güvenle çalışabilir) ve
  10 dakikalığına "gönderiliyor" olarak kilitlenir; süreç çökerse satır sonra yeniden alınır.
* Geçici hatada artan beklemeyle yeniden denenir (en çok 8 deneme); alıcı reddi gibi kalıcı
  hatada tekrar denenmez.
* Süresi dolmuş bağlantı içeren e-postalar (doğrulama 24 sa, parola sıfırlama 1 sa) gönderilmez.
* Lisans anahtarı e-postaya yazılmaz: müşteri anahtarı panelde parolasını yeniden girerek görür.
* Günlüklere e-posta içeriği ve tam adres yazılmaz.

Sağlayıcı bağımsızdır (SMTP). Önerilen: Resend (``smtp.resend.com``, kullanıcı ``resend``,
parola API anahtarı). Ayarlar: ``ATI_SMTP_*`` ve ``ATI_MAIL_FROM`` (``config.py``).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import html
import logging
import smtplib
import ssl
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Any

from ati_cloud.accounts import Database
from ati_cloud.config import CloudSettings
from ati_cloud.loop import run

log = logging.getLogger("ati_cloud.mail")

MAX_ATTEMPTS = 8
LEASE = timedelta(minutes=10)
BACKOFF_MINUTES = [1, 5, 15, 60, 180, 360, 720]
# Bağlantının geçerlilik süresi (accounts.py VERIFY_TTL / RESET_TTL ile aynı).
EXPIRES = {"verify_email": timedelta(hours=24), "password_reset": timedelta(hours=1)}
SITE = "AI Trading Intelligence"


class PermanentError(Exception):
    """Yeniden denemenin anlamı olmayan hata (alıcı reddedildi, şablon bilinmiyor)."""


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    text: str
    html: str


# --- Şablonlar --------------------------------------------------------------------------------

_FOOTER_TEXT = (
    "\n--\nAI Trading Intelligence · canarslan.net.tr\n"
    "Bu e-posta hesabınızla ilgili bir işlem nedeniyle otomatik gönderildi; "
    "yanıtlamanıza gerek yok."
)


def _html(title: str, paragraphs: list[str], link: str | None, button: str | None) -> str:
    body = "".join(
        f'<p style="margin:0 0 14px;line-height:1.55">{html.escape(p)}</p>' for p in paragraphs
    )
    action = ""
    if link and button:
        safe = html.escape(link, quote=True)
        action = (
            f'<p style="margin:22px 0"><a href="{safe}" style="background:#1d4ed8;color:#ffffff;'
            "padding:11px 20px;border-radius:999px;text-decoration:none;font-weight:600;"
            f'display:inline-block">{html.escape(button)}</a></p>'
            '<p style="margin:0 0 14px;font-size:13px;color:#555">Düğme çalışmazsa bu adresi '
            f'tarayıcınıza yapıştırın:<br><span style="word-break:break-all">{safe}</span></p>'
        )
    return (
        '<!doctype html><html lang="tr"><body style="margin:0;background:#f4f5f7;'
        'font-family:Segoe UI,Arial,sans-serif;color:#111">'
        '<div style="max-width:560px;margin:0 auto;padding:28px 20px">'
        f'<p style="font-weight:700;font-size:15px;margin:0 0 18px">{SITE}</p>'
        '<div style="background:#ffffff;border-radius:14px;padding:26px">'
        f'<h1 style="font-size:20px;margin:0 0 16px">{html.escape(title)}</h1>{body}{action}'
        "</div>"
        '<p style="font-size:12px;color:#666;line-height:1.5;margin:18px 4px 0">'
        "AI Trading Intelligence · canarslan.net.tr<br>Bu e-posta hesabınızla ilgili bir işlem "
        "nedeniyle otomatik gönderildi.</p></div></body></html>"
    )


def _text(title: str, paragraphs: list[str], link: str | None) -> str:
    parts = [title, "", *paragraphs]
    if link:
        parts += ["", link]
    return "\n".join(parts) + "\n" + _FOOTER_TEXT + "\n"


def render(template: str, payload: dict[str, Any], to: str) -> Mail:
    """Kuyruktaki kayıttan e-posta üretir. Bilinmeyen şablon kalıcı hatadır."""
    link = payload.get("link") if isinstance(payload.get("link"), str) else None
    if template == "verify_email":
        title = "E-posta adresinizi doğrulayın"
        subject = f"{title} — {SITE}"
        paragraphs = [
            "Merhaba,",
            "AI Trading Intelligence hesabınızı etkinleştirmek için aşağıdaki bağlantıyı açın. "
            "Bağlantı 24 saat geçerlidir.",
            "Bu kaydı siz yapmadıysanız bu e-postayı dikkate almayın; hesap etkinleşmez.",
        ]
        button = "E-postamı doğrula"
    elif template == "password_reset":
        title = "Parola sıfırlama"
        subject = f"{title} — {SITE}"
        paragraphs = [
            "Merhaba,",
            "Parolanızı sıfırlamak için aşağıdaki bağlantıyı açın. Bağlantı 1 saat geçerlidir ve "
            "yalnızca bir kez kullanılabilir.",
            "Bu isteği siz yapmadıysanız bu e-postayı dikkate almayın; parolanız değişmez.",
        ]
        button = "Yeni parola belirle"
    elif template == "account_exists":
        title = "Bu adresle zaten bir hesabınız var"
        subject = f"Hesabınız zaten var — {SITE}"
        paragraphs = [
            "Merhaba,",
            "Bu e-posta adresiyle yeni bir kayıt denendi; ancak bu adrese bağlı bir hesabınız "
            "zaten var. Aşağıdaki bağlantıdan giriş yapabilirsiniz. Parolanızı hatırlamıyorsanız "
            "giriş sayfasındaki “Parolamı unuttum” adımını kullanın.",
            "Bu denemeyi siz yapmadıysanız bir işlem yapmanıza gerek yok.",
        ]
        button = "Giriş yap"
    elif template == "license_delivery":
        order_no = payload.get("order_no")
        count = len(payload.get("license_ids") or [])
        link = payload.get("panel_url") if isinstance(payload.get("panel_url"), str) else None
        title = "Lisansınız hazır"
        subject = f"Lisansınız hazır — Sipariş #{order_no} — {SITE}"
        paragraphs = [
            "Merhaba,",
            f"#{order_no} numaralı siparişiniz tamamlandı; {count} lisans hesabınıza tanımlandı.",
            "Güvenliğiniz için lisans anahtarı e-postayla gönderilmez. Anahtarınızı müşteri "
            "panelinde, parolanızı yeniden girerek görüntüleyebilirsiniz. Uygulamayı "
            "canarslan.net.tr/indir adresinden indirebilirsiniz.",
            "Kripto varlık işlemleri yüksek risk taşır; AI Trading Intelligence yatırım "
            "tavsiyesi vermez ve kazanç garantisi sunmaz.",
        ]
        button = "Müşteri paneline git"
    else:
        raise PermanentError(f"bilinmeyen şablon: {template}")
    if template != "license_delivery" and not link:
        raise PermanentError(f"{template}: bağlantı yok")
    return Mail(
        to=to,
        subject=subject,
        text=_text(title, paragraphs, link),
        html=_html(title, paragraphs, link, button),
    )


# --- SMTP --------------------------------------------------------------------------------------


def build_message(mail: Mail, settings: CloudSettings) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    msg["Date"] = formatdate(localtime=False)
    domain = parseaddr(settings.mail_from)[1].rpartition("@")[2] or "canarslan.net.tr"
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["Auto-Submitted"] = "auto-generated"
    if settings.mail_reply_to:
        msg["Reply-To"] = settings.mail_reply_to
    msg.set_content(mail.text)
    msg.add_alternative(mail.html, subtype="html")
    return msg


class SmtpSender:
    """Bir toplu gönderim için tek SMTP bağlantısı (bağlam yöneticisi)."""

    def __init__(self, settings: CloudSettings) -> None:
        self.settings = settings
        self.smtp: smtplib.SMTP | None = None

    def __enter__(self) -> SmtpSender:
        s = self.settings
        host = s.smtp_host or ""
        context = ssl.create_default_context()
        if s.smtp_security == "ssl":
            self.smtp = smtplib.SMTP_SSL(host, s.smtp_port, timeout=30, context=context)
        else:
            self.smtp = smtplib.SMTP(host, s.smtp_port, timeout=30)
            if s.smtp_security == "starttls":
                self.smtp.starttls(context=context)
        if s.smtp_username:
            password = s.smtp_password.get_secret_value() if s.smtp_password else ""
            self.smtp.login(s.smtp_username, password)
        return self

    def __exit__(self, *_: object) -> None:
        if self.smtp is not None:
            with contextlib.suppress(smtplib.SMTPException, OSError):
                self.smtp.quit()

    def send(self, message: EmailMessage) -> str:
        assert self.smtp is not None  # noqa: S101 - yalnızca bağlam içinde çağrılır
        try:
            self.smtp.send_message(message)
        except smtplib.SMTPRecipientsRefused as exc:
            raise PermanentError("alıcı reddedildi") from exc
        except smtplib.SMTPResponseException as exc:
            # Gönderen/alan adı/anahtar sorunları ayar hatasıdır: düzeltilince gönderilsin diye
            # kalıcı sayılmaz, artan beklemeyle yeniden denenir.
            if 500 <= exc.smtp_code < 600 and not is_config_error(exc):
                raise PermanentError(f"SMTP {exc.smtp_code}: {smtp_text(exc)}") from exc
            raise
        return str(message["Message-ID"])


# Sağlayıcının hata metninde bu ifadeler geçiyorsa sorun alıcıda değil ayardadır.
CONFIG_HINTS = ("domain", "verif", "sender", "from address", "api key", "not allowed", "testing")


def smtp_text(exc: smtplib.SMTPResponseException) -> str:
    raw = exc.smtp_error
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    return " ".join(text.split())[:200]


def is_config_error(exc: smtplib.SMTPResponseException) -> bool:
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return True
    text = smtp_text(exc).lower()
    return any(hint in text for hint in CONFIG_HINTS)


SenderFactory = Callable[[CloudSettings], Any]


# --- Kuyruk ------------------------------------------------------------------------------------


def _mask(address: str) -> str:
    name, _, domain = address.partition("@")
    return f"{name[:1]}***@{domain}"


def _describe(exc: BaseException) -> str:
    if isinstance(exc, smtplib.SMTPResponseException):
        return f"SMTP {exc.smtp_code}: {smtp_text(exc)}"[:300]
    return f"{type(exc).__name__}: {exc}"[:300]


def _backoff(attempts: int) -> timedelta:
    return timedelta(minutes=BACKOFF_MINUTES[min(attempts - 1, len(BACKOFF_MINUTES) - 1)])


async def process_once(
    db: Database,
    settings: CloudSettings,
    *,
    limit: int = 20,
    sender_factory: SenderFactory = SmtpSender,
) -> dict[str, int]:
    """Zamanı gelmiş en çok ``limit`` e-postayı gönderir. Sayaçları döndürür."""
    stats = {"sent": 0, "retry": 0, "failed": 0, "expired": 0}
    async with db.connection() as conn, conn.transaction():
        cur = await conn.execute(
            "UPDATE email_outbox SET status = 'sending', attempts = attempts + 1, "
            "next_attempt_at = now() + %s WHERE id IN ("
            "  SELECT id FROM email_outbox WHERE status IN ('pending', 'failed', 'sending') "
            "  AND next_attempt_at <= now() AND attempts < %s "
            "  ORDER BY next_attempt_at LIMIT %s FOR UPDATE SKIP LOCKED) "
            "RETURNING id, to_email::text AS to_email, template, payload, attempts, "
            "now() - created_at AS age",
            (LEASE, MAX_ATTEMPTS, limit),
        )
        rows = await cur.fetchall()
    if not rows:
        return stats

    results: list[
        tuple[Any, str, str | None, str | None, int]
    ] = []  # id, durum, msgid, hata, deneme
    ready: list[tuple[dict[str, Any], Mail]] = []
    for row in rows:
        ttl = EXPIRES.get(row["template"])
        if ttl is not None and row["age"] > ttl:
            results.append((row["id"], "expired", None, "bağlantının süresi doldu", MAX_ATTEMPTS))
            continue
        try:
            ready.append(
                (row, render(row["template"], dict(row["payload"] or {}), row["to_email"]))
            )
        except PermanentError as exc:
            results.append((row["id"], "failed", None, str(exc), MAX_ATTEMPTS))

    if ready:
        try:
            outcome = await asyncio.to_thread(_send_batch, ready, settings, sender_factory)
            results.extend(outcome)
        except Exception as exc:  # bağlantı/oturum açma hatası: tümü geçici hata
            log.warning("SMTP bağlantısı kurulamadı: %s", type(exc).__name__)
            for row, _mail in ready:
                results.append((row["id"], "retry", None, _describe(exc), row["attempts"]))

    async with db.connection() as conn, conn.transaction():
        for outbox_id, state, message_id, error, attempts in results:
            if state == "sent":
                await conn.execute(
                    "UPDATE email_outbox SET status = 'sent', sent_at = now(), "
                    "provider_message_id = %s, last_error = NULL WHERE id = %s",
                    (message_id, outbox_id),
                )
                stats["sent"] += 1
            elif state == "retry" and attempts < MAX_ATTEMPTS:
                await conn.execute(
                    "UPDATE email_outbox SET status = 'failed', last_error = %s, "
                    "next_attempt_at = now() + %s WHERE id = %s",
                    (error, _backoff(attempts), outbox_id),
                )
                stats["retry"] += 1
            else:
                await conn.execute(
                    "UPDATE email_outbox SET status = 'failed', attempts = %s, last_error = %s "
                    "WHERE id = %s",
                    (MAX_ATTEMPTS, error, outbox_id),
                )
                stats["expired" if state == "expired" else "failed"] += 1
    return stats


def _send_batch(
    ready: list[tuple[dict[str, Any], Mail]], settings: CloudSettings, factory: SenderFactory
) -> list[tuple[Any, str, str | None, str | None, int]]:
    out: list[tuple[Any, str, str | None, str | None, int]] = []
    with factory(settings) as sender:
        for row, mail in ready:
            try:
                message_id = sender.send(build_message(mail, settings))
                out.append((row["id"], "sent", message_id, None, row["attempts"]))
                log.info("gönderildi: %s → %s", row["template"], _mask(mail.to))
            except PermanentError as exc:
                out.append((row["id"], "failed", None, str(exc), MAX_ATTEMPTS))
                log.warning("kalıcı hata: %s → %s (%s)", row["template"], _mask(mail.to), exc)
            except (smtplib.SMTPException, OSError) as exc:
                out.append((row["id"], "retry", None, _describe(exc), row["attempts"]))
                log.warning("geçici hata: %s → %s", row["template"], _mask(mail.to))
    return out


async def run_forever(settings: CloudSettings, interval_s: float) -> None:
    if not settings.smtp_host:
        log.warning("E-posta sunucusu ayarlı değil (ATI_SMTP_HOST); kuyruk birikir, gönderilmez.")
        # Gözetim betiği yeniden başlatıp durmasın; ayar gelince süreç yeniden açılır.
        await asyncio.Event().wait()
    db = Database(settings.database_dsn, max_size=2)
    log.info("E-posta gönderici başladı (%s:%s)", settings.smtp_host, settings.smtp_port)
    try:
        while True:
            try:
                stats = await process_once(db, settings)
                if any(stats.values()):
                    log.info("kuyruk: %s", stats)
            except Exception:
                log.exception("kuyruk işlenemedi")
            await asyncio.sleep(interval_s)
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ati-cloud-mail", description="E-posta kuyruğu")
    sub = parser.add_subparsers(dest="command", required=True)
    runner = sub.add_parser("run", help="Kuyruğu sürekli işle")
    runner.add_argument("--interval", type=float, default=10.0)
    runner.add_argument("--once", action="store_true", help="Bir kez işle ve çık")
    test = sub.add_parser(
        "test", help="Adım adım teşhis: ayarlar, port, oturum, deneme e-postası, kuyruk"
    )
    test.add_argument("--to", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
    )
    settings = CloudSettings()
    if args.command == "test":
        from ati_cloud.mail_check import diagnose

        print(f"E-posta teşhisi → {_mask(args.to)}")
        sent, steps = diagnose(settings, args.to)
        for step in steps:
            print(step.line())
        verdict = "e-posta gönderimi çalışıyor." if sent else "yukarıdaki HATA satırına bakın."
        print("Sonuç: " + verdict)
        return 0 if sent else 1
    if args.once:

        async def once() -> dict[str, int]:
            db = Database(settings.database_dsn, max_size=2)
            try:
                return await process_once(db, settings)
            finally:
                await db.close()

        print(run(once()))
        return 0
    run(run_forever(settings, args.interval))
    return 0
