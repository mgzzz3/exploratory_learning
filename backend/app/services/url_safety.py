from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


Resolver = Callable[[str], Awaitable[Sequence[str]]]

TRACKING_QUERY_NAMES = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
}
SENSITIVE_QUERY_NAMES = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "code",
    "key",
    "password",
    "signature",
    "token",
}
LOCAL_HOST_SUFFIXES = (".internal", ".local", ".localhost")


class InvalidSourceUrlError(ValueError):
    code = "INVALID_SOURCE_URL"


async def resolve_host_addresses(hostname: str) -> Sequence[str]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(
        hostname,
        None,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )
    return tuple(dict.fromkeys(record[4][0] for record in records))


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_global


def _normalized_host(hostname: str) -> str:
    try:
        return hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise InvalidSourceUrlError("网页地址的站点域名无效") from exc


async def normalize_public_url(
    value: str,
    *,
    resolver: Resolver = resolve_host_addresses,
) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise InvalidSourceUrlError("网页地址格式无效") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise InvalidSourceUrlError("只支持公开 HTTP(S) 网页")
    if parsed.username is not None or parsed.password is not None:
        raise InvalidSourceUrlError("网页地址不能包含用户凭证")
    if not parsed.hostname:
        raise InvalidSourceUrlError("网页地址缺少站点域名")

    hostname = _normalized_host(parsed.hostname)
    if hostname == "localhost" or hostname.endswith(LOCAL_HOST_SUFFIXES):
        raise InvalidSourceUrlError("网页地址必须指向公开站点")

    try:
        literal_address = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        literal_address = None

    if literal_address is not None:
        addresses: Sequence[str] = (str(literal_address),)
    else:
        try:
            addresses = await resolver(hostname)
        except Exception as exc:
            raise InvalidSourceUrlError("无法确认网页地址指向公开站点") from exc

    if not addresses or any(not _is_public_address(item) for item in addresses):
        raise InvalidSourceUrlError("网页地址必须指向公开站点")

    try:
        port = parsed.port
    except ValueError as exc:
        raise InvalidSourceUrlError("网页地址端口无效") from exc

    if ":" in hostname:
        netloc = f"[{hostname}]"
    else:
        netloc = hostname
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{netloc}:{port}"

    safe_query: list[tuple[str, str]] = []
    for name, query_value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered_name = name.lower()
        if lowered_name in SENSITIVE_QUERY_NAMES:
            raise InvalidSourceUrlError("网页地址包含不允许的敏感查询参数")
        if lowered_name.startswith("utm_") or lowered_name in TRACKING_QUERY_NAMES:
            continue
        safe_query.append((name, query_value))

    return urlunsplit(
        (
            scheme,
            netloc,
            parsed.path,
            urlencode(safe_query, doseq=True),
            "",
        )
    )
