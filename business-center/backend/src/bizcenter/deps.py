from fastapi import Request

from .db import Database


def get_db(request: Request) -> Database:
    return request.app.state.db  # type: ignore[no-any-return]
