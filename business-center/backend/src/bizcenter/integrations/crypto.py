"""Entegrasyon tokenlarının şifrelenmesi (Fernet: AES-128-CBC + HMAC). Anahtar yalnızca sunucu ortamında."""

from cryptography.fernet import Fernet, InvalidToken


class TokenCipher:
    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError("BC_TOKEN_ENCRYPTION_KEY tanımlı değil")
        self._f = Fernet(key.encode())

    def encrypt(self, value: str) -> bytes:
        return self._f.encrypt(value.encode())

    def decrypt(self, blob: bytes) -> str:
        try:
            return self._f.decrypt(bytes(blob)).decode()
        except InvalidToken as exc:
            raise ValueError("Token çözülemedi (anahtar değişmiş olabilir)") from exc


def new_key() -> str:
    return Fernet.generate_key().decode()
