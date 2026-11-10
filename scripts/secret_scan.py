#!/usr/bin/env python3
"""Depoda gizli bilgi taraması (Aşama 18). Harici araç gerektirmez; CI'da her gönderimde çalışır.

    python3 scripts/secret_scan.py            # izlenen dosyalar (çalışma ağacı)
    python3 scripts/secret_scan.py --history  # ek olarak tüm git geçmişi (eklenen satırlar)

Aranır: özel anahtar blokları (PEM/OpenSSH), bulut ve hizmet belirteçleri (AWS, GitHub, Slack,
Stripe, Google), API anahtarı / gizli anahtar atamaları, gerçek ortam dosyalarında (``.env``)
doldurulmuş gizli değişkenler. Bulgu varsa çıkış kodu 1'dir; bulgu metni maskelenerek ve parmak
iziyle (değerin SHA-256 özetinin ilk 16 hanesi) yazılır (çıktı gizli bilgiyi sızdırmaz).

Bilinçli test değerleri iki yolla işaretlenir: satıra ``secret-scan: allow`` yazmak ya da parmak
izini gerekçesiyle ``.secretscanignore`` dosyasına eklemek. Geçmişe girmiş test değerleri için
yalnızca ikincisi işe yarar (geçmiş değiştirilemez).
"""

from __future__ import annotations

import argparse
import hashlib
import math
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

ALLOW_MARKER = "secret-scan: allow"

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("özel anahtar", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY")),
    ("AWS erişim anahtarı", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub belirteci", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b")),
    ("Slack belirteci", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Stripe canlı anahtarı", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b")),
    ("Google API anahtarı", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Anthropic/OpenAI anahtarı", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{32,}\b")),
    (
        "API anahtarı ataması",
        re.compile(
            r"""(?ix)(?:api[_-]?key|api[_-]?secret|secret[_-]?key|merchant[_-]?(?:key|salt)
            |access[_-]?token|private[_-]?key)["']?\s*[:=]\s*["']([A-Za-z0-9+/=_\-]{24,})["']"""
        ),
    ),
]
# Gerçek ortam dosyalarında doldurulmuş gizli değişkenler (örnek dosyalar hariç).
ENV_SECRET = re.compile(
    r"^\s*(?:export\s+)?[A-Z0-9_]*(?:SECRET|PASSWORD|PEPPER|KEK|SIGNING_KEY|TOKEN|API_KEY)[A-Z0-9_]*"
    r"\s*=\s*['\"]?([^'\"\s#]{8,})"
)
PLACEHOLDER = re.compile(r"(?i)(change|ornek|örnek|example|placeholder|xxxx|dummy|<|\$\{|test)")
BINARY_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".icns", ".webp", ".pdf", ".woff", ".woff2",
    ".ttf", ".zip", ".gz", ".lock", ".sqlite", ".db", ".pyc",
)  # fmt: skip
SKIP_PATHS = ("node_modules/", ".venv/", "target/", ".next/")


IGNORE_FILE = ".secretscanignore"


@dataclass(frozen=True)
class Finding:
    where: str
    line: int
    kind: str
    excerpt: str
    fingerprint: str = ""

    def __str__(self) -> str:
        return f"{self.where}:{self.line}: {self.kind}: {self.excerpt} [parmak izi {self.fingerprint}]"


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.strip().encode()).hexdigest()[:16]


def load_ignored(path: str = IGNORE_FILE) -> set[str]:
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        return set()
    return {ln.split()[0] for ln in lines if ln.strip() and not ln.lstrip().startswith("#")}


def entropy(text: str) -> float:
    counts = {c: text.count(c) for c in set(text)}
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values())


def mask(value: str) -> str:
    value = value.strip()
    return value[:4] + "…" if len(value) > 8 else "…"


def is_env_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (name == ".env" or name.startswith(".env.") or name.endswith(".env")) and not (
        name.endswith(".example") or ".example" in name or name.endswith(".sample")
    )


def scan_line(path: str, number: int, line: str) -> Iterator[Finding]:
    if ALLOW_MARKER in line:
        return
    for kind, pattern in PATTERNS:
        match = pattern.search(line)
        if not match:
            continue
        value = match.group(match.lastindex or 0)
        if kind == "API anahtarı ataması" and (PLACEHOLDER.search(value) or entropy(value) < 3.5):
            continue
        yield Finding(path, number, kind, mask(value), fingerprint(value))
    if is_env_file(path):
        match = ENV_SECRET.search(line)
        if match and not PLACEHOLDER.search(match.group(1)):
            value = match.group(1)
            yield Finding(path, number, "ortam dosyasında gizli değer", mask(value), fingerprint(value))


def scan_text(path: str, text: str) -> Iterator[Finding]:
    for number, line in enumerate(text.splitlines(), start=1):
        yield from scan_line(path, number, line)


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True, text=True
    ).stdout
    return [p for p in out.split("\0") if p]


def scan_worktree(paths: Iterable[str]) -> Iterator[Finding]:
    for path in paths:
        if path.endswith(BINARY_SUFFIXES) or any(s in path for s in SKIP_PATHS):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        yield from scan_text(path, text)


def scan_history() -> Iterator[Finding]:
    """Tüm geçmişte eklenmiş satırlar (sonradan silinen gizli bilgi de geçmişte kalır)."""
    proc = subprocess.Popen(
        ["git", "log", "--all", "-p", "--no-color", "--unified=0", "--format=commit %H"],
        stdout=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    assert proc.stdout is not None
    commit, path, number = "", "", 0
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        if line.startswith("commit "):
            commit = line[7:19]
        elif line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            number = int(match.group(1)) if match else 0
        elif line.startswith("+") and not line.startswith("+++"):
            if not path.endswith(BINARY_SUFFIXES) and not any(s in path for s in SKIP_PATHS):
                yield from scan_line(f"{commit}:{path}", number, line[1:])
            number += 1
    proc.wait()


def self_test() -> int:
    """Tarayıcının gerçekten yakaladığını kanıtlar. Örnekler çalışma anında birleştirilir; bu
    dosyanın kendisi gizli bilgi içermez."""
    j = "".join
    must_find = {
        "özel anahtar": j(["-----BEGIN ", "PRIVATE KEY-----"]),
        "openssh": j(["-----BEGIN OPENSSH ", "PRIVATE KEY-----"]),
        "aws": j(["AKIA", "Q3EGRZ7PWNXH4K2M"]),
        "github": j(["ghp_", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"]),
        "stripe": j(["sk_live_", "51HqXyZaBcDeFgHiJkLmNoPq"]),
        "api ataması": j(['binance_api_key = "', "vQ7rT2mX9kL4pZ8nW3cY6bH1jF5dS0aG", '"']),
        "paytr": j(['"merchant_key": "', "Zx81LqPw0Rt5Yb3Kc7Vn2Mj9Hg4Fd6Sa", '"']),
    }
    must_ignore = {
        "yer tutucu": 'api_key = "your-api-key-placeholder-xxxxxxxx"',
        "düşük entropi": 'secret_key = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"',
        "izinli": j(["AKIA", "Q3EGRZ7PWNXH4K2M  # ", ALLOW_MARKER, " (örnek)"]),
        "olağan metin": "Lisans anahtarı ATI-****-****-****-ZR61 biçimindedir.",
    }
    failures = [k for k, v in must_find.items() if not list(scan_line("ornek.py", 1, v))]
    failures += [k for k, v in must_ignore.items() if list(scan_line("ornek.py", 1, v))]
    env_hit = list(scan_line(".env", 1, j(["ATI_LICENSE_PEPPER=", "q9Wm2Rt7Yx4Lp8Kz"])))
    env_example = list(scan_line("cloud.env.example", 1, j(["ATI_LICENSE_PEPPER=", "q9Wm2Rt7"])))
    if not env_hit or env_example:
        failures.append("ortam dosyası")
    if any(j(["q9Wm2", "Rt7Yx4Lp8Kz"]) in str(f) for f in env_hit):
        failures.append("maskeleme")
    aws = list(scan_line("ornek.py", 1, must_find["aws"]))
    if not aws or aws[0].fingerprint != fingerprint(j(["AKIA", "Q3EGRZ7PWNXH4K2M"])):
        failures.append("parmak izi")
    print("Öz sınama:", "başarısız: " + ", ".join(failures) if failures else "tamam", file=sys.stderr)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--history", action="store_true", help="git geçmişini de tara")
    parser.add_argument("--self-test", action="store_true", help="tarayıcının kendini sınaması")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    findings = list(scan_worktree(tracked_files()))
    if args.history:
        seen = {(f.where, f.line) for f in findings}
        findings += [f for f in scan_history() if (f.where, f.line) not in seen]
    ignored = load_ignored()
    findings = [f for f in findings if f.fingerprint not in ignored]
    for finding in findings:
        print(finding)
    scope = "izlenen dosyalar + git geçmişi" if args.history else "izlenen dosyalar"
    print(f"Gizli bilgi taraması ({scope}): {len(findings)} bulgu", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
