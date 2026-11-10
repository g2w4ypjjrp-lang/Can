"""Sunucu dışı yedek: şifreleme, AWS SigV4 imzası (botocore ile üretilmiş referansa karşı) ve
yükleme. Ağ yok: S3 uyumlu depo httpx.MockTransport ile taklit edilir."""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from cryptography.exceptions import InvalidTag
from pydantic import SecretStr

from ati_cloud.offsite import OffsiteSettings, decrypt, encrypt, main, sign_v4, upload

KEY = base64.b64encode(bytes(range(32))).decode()


def settings() -> OffsiteSettings:
    return OffsiteSettings(
        endpoint="https://hesap.r2.cloudflarestorage.com",
        bucket="ati-yedek",
        access_key="AKIDEXAMPLE",
        secret_key=SecretStr("wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"),
        encryption_key=SecretStr(KEY),
    )


def test_signature_matches_botocore_reference() -> None:
    """Referans: botocore 1.40.0 S3SigV4Auth, aynı istek ve zaman (bölge "auto")."""
    body = b"sifreli-yedek-icerigi"
    headers = sign_v4(
        method="PUT",
        url="https://hesap.r2.cloudflarestorage.com/ati-yedek/yedekler/ati-20261110-0330.dump.enc",
        headers={"content-type": "application/octet-stream"},
        payload_hash=hashlib.sha256(body).hexdigest(),
        access_key="AKIDEXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        region="auto",
        now=datetime(2026, 11, 10, 3, 30, tzinfo=UTC),
    )
    assert headers["x-amz-date"] == "20261110T033000Z"
    assert headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20261110/auto/s3/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date, "
        "Signature=e26ab7a776860cbcfe9be1b896b8af91acae6fbee3be3833cc75ffda945d5567"
    )


def test_encryption_roundtrip_and_tamper_detection() -> None:
    key = os.urandom(32)
    blob = encrypt(b"pg_dump verisi", key, "ati-1.dump.enc")
    assert b"pg_dump" not in blob and blob.startswith(b"ATIB1")
    assert decrypt(blob, key, "ati-1.dump.enc") == b"pg_dump verisi"
    with pytest.raises(InvalidTag):  # başka yedeğin adıyla açılamaz
        decrypt(blob, key, "ati-2.dump.enc")
    with pytest.raises(InvalidTag):  # değiştirilmiş içerik
        decrypt(blob[:-1] + bytes([blob[-1] ^ 1]), key, "ati-1.dump.enc")
    with pytest.raises(ValueError, match="ATI"):
        decrypt(b"duz-metin", key, "x")


def test_upload_encrypts_signs_and_reports_errors(tmp_path: Path) -> None:
    dump = tmp_path / "ati-20261110-0330.dump"
    dump.write_bytes(b"gizli musteri verisi" * 100)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        key = upload(dump, settings(), client=client)
    assert key == "yedekler/ati-20261110-0330.dump.enc"
    request = seen[0]
    assert request.method == "PUT"
    assert str(request.url).endswith("/ati-yedek/yedekler/ati-20261110-0330.dump.enc")
    assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert request.headers["x-amz-content-sha256"] == hashlib.sha256(request.content).hexdigest()
    assert b"gizli musteri" not in request.content  # depoya şifreli gider
    assert decrypt(request.content, bytes(range(32)), "ati-20261110-0330.dump.enc").startswith(
        b"gizli musteri"
    )

    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(403, text="Denied"))
        ) as c,
        pytest.raises(RuntimeError, match="403"),
    ):
        upload(dump, settings(), client=c)
    with pytest.raises(ValueError, match="ayarlı değil"):
        upload(dump, OffsiteSettings(), client=None)


def test_cli_new_key_and_decrypt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["new-key"]) == 0
    assert len(base64.b64decode(capsys.readouterr().out.strip())) == 32
    monkeypatch.setenv("ATI_OFFSITE_ENCRYPTION_KEY", KEY)
    enc = tmp_path / "ati-1.dump.enc"
    enc.write_bytes(encrypt(b"veri", bytes(range(32)), "ati-1.dump.enc"))
    out = tmp_path / "ati-1.dump"
    assert main(["decrypt", str(enc), str(out)]) == 0 and out.read_bytes() == b"veri"
    monkeypatch.setenv("ATI_OFFSITE_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    assert main(["decrypt", str(enc), str(tmp_path / "x")]) == 1  # yanlış anahtar
