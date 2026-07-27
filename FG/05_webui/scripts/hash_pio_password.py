"""Generate a PBKDF2 password hash for data/pio_users.json.

Usage:
    python FG/05_webui/scripts/hash_pio_password.py

The password is read without echo and is never written to disk by this tool.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import secrets


ITERATIONS = 210_000


def main() -> None:
    password = getpass.getpass("PIO password (12-128 characters): ")
    if not 12 <= len(password) <= 128:
        raise SystemExit("Password must be between 12 and 128 characters.")
    if not any(char.isalpha() for char in password) or not any(
        char.isdigit() for char in password
    ):
        raise SystemExit("Password must contain at least one letter and one number.")
    confirm = getpass.getpass("Confirm password: ")
    if not secrets.compare_digest(password, confirm):
        raise SystemExit("Passwords do not match.")

    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, ITERATIONS
    )
    print("$".join((
        "pbkdf2_sha256",
        str(ITERATIONS),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    )))


if __name__ == "__main__":
    main()
