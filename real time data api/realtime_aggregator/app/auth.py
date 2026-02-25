from __future__ import annotations
import hmac
from fastapi import Depends, Security
from fastapi.security import APIKeyHeader
from app.config import settings
from app.exceptions import AppError


class AuthenticationError(AppError):
    status_code = 401
    error_code = "UNAUTHORIZED"


_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    if not api_key or not hmac.compare_digest(api_key, settings.API_KEY):
        raise AuthenticationError("Invalid or missing API key")
    return api_key
