from fastapi import HTTPException, status
from psycopg import errors as pg

_MAP = {
    "not allowed": status.HTTP_403_FORBIDDEN,
    "approval not found": status.HTTP_404_NOT_FOUND,
    "not authenticated": status.HTTP_401_UNAUTHORIZED,
}


def db_error(exc: Exception) -> HTTPException:
    """Veritabanı kural ihlallerini güvenli HTTP hatalarına çevirir (iç ayrıntı sızdırmaz)."""
    if isinstance(exc, pg.RaiseException):
        msg = (exc.diag.message_primary or "").strip()
        return HTTPException(_MAP.get(msg, status.HTTP_409_CONFLICT), msg)
    if isinstance(exc, pg.InsufficientPrivilege):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Yetki yok")
    if isinstance(exc, pg.CheckViolation | pg.UniqueViolation | pg.ForeignKeyViolation):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Geçersiz veri")
    raise exc
