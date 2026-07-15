from __future__ import annotations

import ipaddress
import socket
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class SecurityError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    hostname: str
    port: int
    resolved_addresses: tuple[str, ...]


Resolver = Callable[..., list[Any]]


def normalize_hostname(hostname: str) -> str:
    value = unicodedata.normalize("NFKC", str(hostname or "")).strip().rstrip(".")
    if not value or any(character.isspace() for character in value):
        raise SecurityError("INVALID_HOST", "URL hostname is missing or malformed.")
    if "%" in value or "\\" in value:
        raise SecurityError("INVALID_HOST", "Encoded or backslash hostnames are rejected.")
    try:
        return value.encode("idna").decode("ascii").casefold()
    except UnicodeError as error:
        raise SecurityError("INVALID_HOST", "URL hostname is not valid IDNA.") from error


def _require_public_ip(address: str) -> str:
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError as error:
        raise SecurityError("DNS_INVALID_ADDRESS", "DNS returned an invalid address.") from error

    if not parsed.is_global:
        raise SecurityError(
            "NON_PUBLIC_ADDRESS",
            "Private, loopback, link-local, reserved, and metadata addresses are rejected.",
        )
    return str(parsed)


def resolve_public_addresses(
    hostname: str,
    *,
    port: int = 443,
    resolver: Resolver = socket.getaddrinfo,
) -> tuple[str, ...]:
    host = normalize_hostname(hostname)
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        literal = None

    if literal is not None:
        return (_require_public_ip(str(literal)),)

    try:
        answers = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError as error:
        raise SecurityError("DNS_FAILURE", "Approved hostname could not be resolved.") from error

    addresses: list[str] = []
    for answer in answers:
        try:
            raw_address = answer[4][0]
        except (IndexError, TypeError):
            continue
        public_address = _require_public_ip(str(raw_address))
        if public_address not in addresses:
            addresses.append(public_address)

    if not addresses:
        raise SecurityError("DNS_NO_ADDRESSES", "Approved hostname resolved to no usable address.")
    return tuple(addresses)


def _normalised_allowed_domains(domains: Iterable[str]) -> frozenset[str]:
    normalised: set[str] = set()
    for domain in domains:
        try:
            normalised.add(normalize_hostname(domain))
        except SecurityError:
            continue
    return frozenset(normalised)


def validate_public_url(
    url: str,
    allowed_domains: Iterable[str],
    *,
    resolver: Resolver = socket.getaddrinfo,
    allow_http: bool = False,
) -> ValidatedURL:
    raw_url = unicodedata.normalize("NFKC", str(url or "")).strip()
    if not raw_url or len(raw_url) > 2048:
        raise SecurityError("INVALID_URL", "URL is empty or exceeds the length limit.")
    if any(ord(character) < 32 or character == "\\" for character in raw_url):
        raise SecurityError("INVALID_URL", "Control characters and backslashes are rejected.")

    try:
        parsed = urlsplit(raw_url)
        parsed_port = parsed.port
    except ValueError as error:
        raise SecurityError("INVALID_URL", "URL could not be parsed safely.") from error

    schemes = {"https", "http"} if allow_http else {"https"}
    if parsed.scheme.casefold() not in schemes:
        raise SecurityError("INVALID_SCHEME", "Only approved HTTPS URLs are accepted.")
    if parsed.username is not None or parsed.password is not None:
        raise SecurityError("USERINFO_REJECTED", "URLs containing user information are rejected.")
    if not parsed.hostname:
        raise SecurityError("INVALID_HOST", "URL hostname is required.")

    hostname = normalize_hostname(parsed.hostname)
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        raise SecurityError("NON_PUBLIC_ADDRESS", "Localhost URLs are rejected.")

    try:
        literal = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        literal = None
    if literal is not None:
        _require_public_ip(str(literal))

    allowed = _normalised_allowed_domains(allowed_domains)
    if hostname not in allowed:
        raise SecurityError("HOST_NOT_ALLOWED", "URL hostname is not on the approved source list.")

    default_port = 443 if parsed.scheme.casefold() == "https" else 80
    port = parsed_port or default_port
    if port != default_port:
        raise SecurityError("PORT_NOT_ALLOWED", "Non-default URL ports are rejected.")

    addresses = resolve_public_addresses(hostname, port=port, resolver=resolver)
    netloc = hostname
    canonical = urlunsplit(
        (parsed.scheme.casefold(), netloc, parsed.path or "/", parsed.query, "")
    )
    return ValidatedURL(
        url=canonical,
        hostname=hostname,
        port=port,
        resolved_addresses=addresses,
    )


def validate_content_type(
    content_type: str | None,
    *,
    allowed: Iterable[str] = (
        "text/html",
        "application/xhtml+xml",
        "application/pdf",
        "application/xml",
        "text/xml",
    ),
) -> str:
    mime = str(content_type or "").split(";", 1)[0].strip().casefold()
    if mime not in {item.casefold() for item in allowed}:
        raise SecurityError("MIME_NOT_ALLOWED", "Response MIME type is not allowed.")
    return mime


def enforce_content_length(content_length: str | int | None, maximum: int) -> None:
    if maximum < 1:
        raise ValueError("maximum must be positive")
    if content_length in (None, ""):
        return
    try:
        size = int(content_length)
    except (TypeError, ValueError) as error:
        raise SecurityError("INVALID_CONTENT_LENGTH", "Response Content-Length is invalid.") from error
    if size < 0 or size > maximum:
        raise SecurityError("RESPONSE_TOO_LARGE", "Response exceeds the configured size limit.")

