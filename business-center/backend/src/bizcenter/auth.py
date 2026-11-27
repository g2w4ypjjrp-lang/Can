"""Supabase Auth JWT doğrulaması. Kullanıcı kimliği yalnızca imzalı tokendan alınır."""

from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status

from .config import Settings


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    claims: dict[str, Any]


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._jwks: jwt.PyJWKClient | None = None
        if not settings.supabase_jwt_secret:
            if not settings.supabase_url:
                raise RuntimeError("BC_SUPABASE_URL veya BC_SUPABASE_JWT_SECRET gerekli")
            self._jwks = jwt.PyJWKClient(
                settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json",
                cache_keys=True,
            )

    def verify(self, token: str) -> CurrentUser:
        try:
            if self._jwks is not None:
                key: Any = self._jwks.get_signing_key_from_jwt(token).key
                algorithms = ["ES256", "RS256"]
            else:
                key, algorithms = self._s.supabase_jwt_secret, ["HS256"]
            claims = jwt.decode(
                token, key, algorithms=algorithms, audience=self._s.supabase_jwt_audience,
                options={"require": ["exp", "sub", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Geçersiz oturum") from exc
        if claims.get("role") != "authenticated":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Geçersiz oturum")
        return CurrentUser(id=claims["sub"], email=claims.get("email"), claims=claims)


def get_verifier(request: Request) -> TokenVerifier:
    return request.app.state.verifier  # type: ignore[no-any-return]


def current_user(request: Request, verifier: TokenVerifier = Depends(get_verifier)) -> CurrentUser:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Oturum gerekli")
    user = verifier.verify(token)
    request.state.user_id = user.id
    return user
