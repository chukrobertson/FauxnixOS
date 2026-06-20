from __future__ import annotations

import hmac
import ipaddress
import os
from urllib.parse import urlencode

from fastapi import Request
from starlette.responses import JSONResponse, RedirectResponse


ACCESS_TOKEN_ENV = "ARCHIVIST_ACCESS_TOKEN"
ACCESS_COOKIE = "archivist_access"
ACCESS_QUERY_PARAM = "access_token"


def configured_access_token() -> str:
    return (os.getenv(ACCESS_TOKEN_ENV) or "").strip()


def is_loopback_host(host: str | None) -> bool:
    normalized = (host or "").strip().split("%", 1)[0]
    if normalized.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(normalized)
        if ip.is_loopback or ip.is_private:
            return True
        # Tailscale uses 100.64.0.0/10 (CGNAT range)
        if ip.version == 4:
            return ipaddress.IPv4Address(normalized) in ipaddress.IPv4Network("100.64.0.0/10")
        return False
    except ValueError:
        return False


def access_token_matches(expected: str, provided: str | None) -> bool:
    return bool(expected and provided and hmac.compare_digest(expected, provided))


def provided_access_token(request: Request) -> str:
    authorization = request.headers.get("authorization") or ""
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return (
        (request.headers.get("x-archivist-token") or "").strip()
        or (request.cookies.get(ACCESS_COOKIE) or "").strip()
        or (request.query_params.get(ACCESS_QUERY_PARAM) or "").strip()
    )


def _url_without_access_token(request: Request) -> str:
    query = urlencode(
        [
            (key, value)
            for key, value in request.query_params.multi_items()
            if key != ACCESS_QUERY_PARAM
        ]
    )
    return str(request.url.replace(query=query))


async def private_access_middleware(request: Request, call_next):
    client_host = request.client.host if request.client else ""
    if is_loopback_host(client_host):
        return await call_next(request)

    expected = configured_access_token()
    provided = provided_access_token(request)
    if not access_token_matches(expected, provided):
        return JSONResponse(
            {
                "detail": (
                    "Remote Archivist access is disabled or the access token is invalid. "
                    f"Set {ACCESS_TOKEN_ENV} before binding beyond localhost."
                )
            },
            status_code=403,
        )

    if request.method == "GET" and request.url.path == "/" and request.query_params.get(ACCESS_QUERY_PARAM):
        response = RedirectResponse(_url_without_access_token(request), status_code=303)
        response.set_cookie(
            ACCESS_COOKIE,
            provided,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
        )
        return response

    return await call_next(request)
