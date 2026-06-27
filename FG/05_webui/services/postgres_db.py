from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row


def get_database_config() -> dict[str, object]:
    """
    Read PostgreSQL settings from environment variables.
    Never hardcode credentials in source code.
    """
    password = os.getenv("POSTGRES_PASSWORD")

    if not password:
        raise RuntimeError(
            "POSTGRES_PASSWORD is not set. "
            "Set PostgreSQL environment variables before starting Flask."
        )

    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "dbname": os.getenv("POSTGRES_DB", "cg_rti_registry"),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": password,
        "row_factory": dict_row,
        "connect_timeout": 10,
    }


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    """
    Open one safe PostgreSQL connection for a request or test.
    The connection closes automatically after use.
    """
    config = get_database_config()

    with psycopg.connect(**config) as connection:
        yield connection


def test_database_connection() -> dict[str, object]:
    """
    Small health check. Does not modify database data.
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_database() AS database_name,
                    current_user AS database_user,
                    COUNT(*) AS active_assignments
                FROM officer_assignments
                WHERE is_active = TRUE;
                """
            )
            row = cursor.fetchone()

    return dict(row)