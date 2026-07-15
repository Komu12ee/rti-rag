import socket
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEBUI_DIR = ROOT / "FG" / "05_webui"
sys.path.insert(0, str(WEBUI_DIR))

from services.section4_web_verification import (  # noqa: E402
    BUILTIN_APPROVED_DOMAINS,
    Section4Config,
    SecurityError,
    normalize_hostname,
    resolve_public_addresses,
    validate_content_type,
    validate_public_url,
)
from services.section4_web_verification.security import enforce_content_length  # noqa: E402


def _resolver(address):
    def resolve(host, port, type=socket.SOCK_STREAM):
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, type, 6, "", (address, port))]

    return resolve


def test_approved_https_url_is_normalised_and_resolved():
    validated = validate_public_url(
        "https://WWW.CIC.GOV.IN./search?q=rti#fragment",
        BUILTIN_APPROVED_DOMAINS,
        resolver=_resolver("93.184.216.34"),
    )

    assert validated.hostname == "www.cic.gov.in"
    assert validated.url == "https://www.cic.gov.in/search?q=rti"
    assert validated.resolved_addresses == ("93.184.216.34",)


@pytest.mark.parametrize(
    "url",
    [
        "http://cic.gov.in/",
        "ftp://cic.gov.in/file",
        "https://evil.example/",
        "https://cic.gov.in@evil.example/",
        "https://user:password@cic.gov.in/",
        "https://cic.gov.in:8443/",
    ],
)
def test_unsafe_or_unapproved_urls_are_rejected(url):
    with pytest.raises(SecurityError):
        validate_public_url(
            url,
            BUILTIN_APPROVED_DOMAINS,
            resolver=_resolver("93.184.216.34"),
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/",
        "https://127.0.0.1/",
        "https://169.254.169.254/latest/meta-data/",
        "https://10.1.2.3/",
        "https://[::1]/",
    ],
)
def test_local_metadata_and_private_literals_are_rejected(url):
    with pytest.raises(SecurityError):
        validate_public_url(
            url,
            {*BUILTIN_APPROVED_DOMAINS, "localhost", "127.0.0.1", "169.254.169.254", "10.1.2.3", "::1"},
            resolver=_resolver("93.184.216.34"),
        )


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.8", "172.16.2.3", "192.168.1.2", "169.254.169.254", "::1", "fe80::1"],
)
def test_approved_hostname_resolving_to_non_public_ip_is_rejected(address):
    with pytest.raises(SecurityError) as error:
        validate_public_url(
            "https://cic.gov.in/",
            BUILTIN_APPROVED_DOMAINS,
            resolver=_resolver(address),
        )

    assert error.value.code == "NON_PUBLIC_ADDRESS"


def test_all_dns_answers_must_be_public():
    def mixed_resolver(host, port, type=socket.SOCK_STREAM):
        return [
            (socket.AF_INET, type, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, type, 6, "", ("10.0.0.1", port)),
        ]

    with pytest.raises(SecurityError):
        resolve_public_addresses("cic.gov.in", resolver=mixed_resolver)


def test_hostname_matching_is_exact_not_suffix_based():
    with pytest.raises(SecurityError) as error:
        validate_public_url(
            "https://cic.gov.in.evil.example/",
            BUILTIN_APPROVED_DOMAINS,
            resolver=_resolver("93.184.216.34"),
        )

    assert error.value.code == "HOST_NOT_ALLOWED"


def test_mime_and_size_guards():
    assert validate_content_type("application/pdf; charset=binary") == "application/pdf"
    assert validate_content_type("text/html; charset=utf-8") == "text/html"

    with pytest.raises(SecurityError) as mime_error:
        validate_content_type("application/x-msdownload")
    assert mime_error.value.code == "MIME_NOT_ALLOWED"

    enforce_content_length("1024", 1024)
    with pytest.raises(SecurityError) as size_error:
        enforce_content_length("1025", 1024)
    assert size_error.value.code == "RESPONSE_TOO_LARGE"


def test_environment_allow_list_cannot_expand_reviewed_domains():
    config = Section4Config.from_env(
        {
            "SECTION4_ALLOWED_DOMAINS": "cic.gov.in,evil.example",
            "SECTION4_CACHE_PATH": "C:/tmp/section4-test-cache.sqlite3",
        }
    )

    assert config.allowed_domains == frozenset({"cic.gov.in"})
    assert normalize_hostname("CIC.GOV.IN.") == "cic.gov.in"
