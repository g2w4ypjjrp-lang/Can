"""Cihaz kimliği: bilgisayar parmak izi (özet) ve lisans cihaz anahtarı.

Parmak izi, işletim sisteminin makine kimliğinin SHA-256 özetidir; kimliğin kendisi buluta
gönderilmez. Aynı bilgisayara yeniden kurulumda aynı kalır (lisansta yeni yer tüketmez).
Cihaz anahtarı (Ed25519) şifreli kasadadır; lisans istekleri bununla imzalanır.
"""

from __future__ import annotations

import hashlib
import secrets
import sys
from pathlib import Path

from ati_engine.security.vault import SecretVault


def machine_id() -> str | None:
    if sys.platform == "win32":  # pragma: no cover - Windows CI'da çalışır
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                return str(value) or None
        except OSError:
            return None
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            text = Path(path).read_text(encoding="ascii").strip()
        except OSError:
            continue
        if text:
            return text
    return None


async def device_fingerprint(vault: SecretVault, *, override: str | None = None) -> bytes:
    """32 baytlık parmak izi. Makine kimliği okunamazsa kuruluma özel kalıcı kimlik kullanılır."""
    ident = override or machine_id()
    if ident is None:
        stored = await vault.get("license.install_id")
        if stored is None:
            value = secrets.token_hex(16)
            await vault.put("license.install_id", value)
        else:
            value = stored.get_secret_value()
        ident = f"install:{value}"
    return hashlib.sha256(f"ati-device-v1|{ident}".encode()).digest()
