"""Haber başlık ve özetlerinin Türkçeye çevrilmesi (yönetim paneli → Coin haberleri → Çeviri).

* **MyMemory** (varsayılan): ücretsiz, anahtar gerekmez. Anonim kullanımda günlük ~5.000 karakter;
  panelde bir e-posta yazılırsa ~50.000 karaktere çıkar (MyMemory'nin kuralı). Başlık + özet ~400
  karakter olduğundan günde onlarca haber çevrilir.
* **DeepL** (isteğe bağlı): DeepL API Free anahtarı (ayda 500.000 karakter ücretsiz) panelden
  girilir; şifreli saklanır, ekrana yalnızca son 4 karakteri yazılır.

Yalnızca başlık ve kısa özet çevrilir; haberin tamamı kopyalanmaz (telif hakkı). Haberin
tamamı kaynak bağlantısındadır.
"""

from __future__ import annotations

import base64
import contextlib
import html
from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

import httpx

from ati_cloud.admin.security import SecretBox

SETTINGS_KEY = "news_translation"
SECRET_AAD = "news-translation|deepl"  # noqa: S105 - şifreleme bağlamı, gizli değer değil
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
MAX_CHARS = 480  # MyMemory istek başına ~500 bayt


class TranslationError(Exception):
    pass


class Translator(Protocol):
    name: str

    async def translate(self, texts: Sequence[str], source: str) -> list[str]: ...


class MyMemory:
    name = "mymemory"

    def __init__(self, client: httpx.AsyncClient, email: str | None = None) -> None:
        self._client = client
        self._email = email

    async def translate(self, texts: Sequence[str], source: str) -> list[str]:
        out: list[str] = []
        for text in texts:
            if not text.strip():
                out.append(text)
                continue
            params: dict[str, str] = {"q": text[:MAX_CHARS], "langpair": f"{source}|tr"}
            if self._email:
                params["de"] = self._email
            response = await self._client.get(MYMEMORY_URL, params=params)
            response.raise_for_status()
            body = response.json()
            if body.get("quotaFinished"):
                raise TranslationError("MyMemory günlük çeviri kotası doldu; yarın devam eder")
            status = body.get("responseStatus")
            translated = (body.get("responseData") or {}).get("translatedText")
            if status not in (200, "200") or not isinstance(translated, str) or not translated:
                raise TranslationError(f"MyMemory çeviri yapamadı ({body.get('responseDetails')})")
            out.append(html.unescape(translated).strip())
        return out


class DeepL:
    name = "deepl"

    def __init__(self, client: httpx.AsyncClient, key: str) -> None:
        self._client = client
        self._key = key
        free = key.endswith(":fx")
        self._url = (
            "https://api-free.deepl.com/v2/translate"
            if free
            else "https://api.deepl.com/v2/translate"
        )

    async def translate(self, texts: Sequence[str], source: str) -> list[str]:
        payload = {"text": list(texts), "target_lang": "TR", "source_lang": source.upper()}
        response = await self._client.post(
            self._url, json=payload, headers={"Authorization": f"DeepL-Auth-Key {self._key}"}
        )
        if response.status_code in (401, 403):
            raise TranslationError("DeepL anahtarı geçersiz")
        if response.status_code == 456:
            raise TranslationError("DeepL aylık çeviri kotası doldu")
        response.raise_for_status()
        items = response.json().get("translations") or []
        if len(items) != len(texts):
            raise TranslationError("DeepL beklenmeyen yanıt verdi")
        return [str(i.get("text", "")).strip() for i in items]


def describe(exc: Exception) -> str:
    if isinstance(exc, TranslationError):
        return str(exc)
    if isinstance(exc, httpx.TimeoutException):
        return "Çeviri servisi zamanında yanıt vermedi"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Çeviri servisi hata döndü (HTTP {exc.response.status_code})"
    if isinstance(exc, httpx.TransportError):
        return "Çeviri servisine bağlanılamadı"
    return type(exc).__name__


async def load_settings(conn: Any) -> dict[str, Any]:
    cur = await conn.execute("SELECT value FROM system_settings WHERE key = %s", (SETTINGS_KEY,))
    row = await cur.fetchone()
    value = row["value"] if row and isinstance(row["value"], dict) else {}
    return {
        "enabled": bool(value.get("enabled", True)),
        "provider": value.get("provider") if value.get("provider") in ("mymemory", "deepl")
        else "mymemory",
        "email": value.get("email") or None,
        "deepl": value.get("deepl") if isinstance(value.get("deepl"), dict) else None,
    }  # fmt: skip


def public_view(settings: dict[str, Any]) -> dict[str, Any]:
    deepl = settings.get("deepl")
    return {
        "enabled": settings["enabled"],
        "provider": settings["provider"],
        "email": settings["email"],
        "deepl_key_hint": deepl.get("hint") if deepl else None,
    }


@contextlib.asynccontextmanager
async def translator_from(
    settings: dict[str, Any], box: SecretBox | None
) -> AsyncIterator[Translator | None]:
    """Ayarlara göre çevirmen (kapalıysa None). DeepL seçili ama anahtar yoksa MyMemory."""
    if not settings["enabled"]:
        yield None
        return
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        deepl = settings.get("deepl")
        if settings["provider"] == "deepl" and deepl and box is not None:
            key = box.open(base64.b64decode(deepl["enc"]), SECRET_AAD).decode()
            yield DeepL(client, key)
        else:
            yield MyMemory(client, settings.get("email"))
