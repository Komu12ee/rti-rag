from __future__ import annotations

from typing import Any

from services.postgres_db import get_connection
from services.officer_name_normalizer import build_name_keys

VALID_RTI_ROLES = {"PIO", "FAA"}


BASE_SELECT = """
    SELECT
        oa.assignment_id,
        oa.rti_role,
        oa.rti_role_original,

        o.officer_id,
        o.officer_name,
        o.email,
        o.designation,

        ofc.office_code,
        ofc.office_name,
        ofc.office_address,
        ofc.office_section_name,
        ofc.office_level,

        d.department_code,
        d.department_name,

        dis.district_name

    FROM officer_assignments oa
    JOIN officers o
        ON o.officer_id = oa.officer_id
    JOIN offices ofc
        ON ofc.office_code = oa.office_code
    LEFT JOIN departments d
        ON d.department_code = ofc.department_code
    LEFT JOIN districts dis
        ON dis.district_id = ofc.district_id
"""


def _normalize_role(role: str | None) -> str | None:
    if not role:
        return None

    normalized = role.strip().upper()

    if normalized not in VALID_RTI_ROLES:
        raise ValueError(
            f"Invalid RTI role: {role}. "
            f"Allowed roles: {sorted(VALID_RTI_ROLES)}"
        )

    return normalized


def _safe_limit(limit: int) -> int:
    return max(1, min(int(limit), 50))


def find_by_email(email: str) -> list[dict[str, Any]]:
    """Exact email lookup for active PIO/FAA assignments."""
    email = email.strip().lower()

    if not email:
        return []

    sql = f"""
        {BASE_SELECT}
        WHERE oa.is_active = TRUE
          AND LOWER(o.email) = %s
        ORDER BY oa.rti_role, ofc.office_name
        LIMIT 20;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (email,))
            return list(cur.fetchall())

NAME_CANDIDATE_FLOOR = 0.52


def find_officer_profiles_by_email(
    email: str,
    rti_role: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Return one grouped officer profile instead of repeated office assignments.
    """
    email = email.strip().lower()
    role = _normalize_role(rti_role)
    limit = _safe_limit(limit)

    if not email:
        return []

    sql = """
        SELECT
            oa.rti_role,
            o.officer_id,
            o.officer_name,
            o.email,
            o.designation,

            ARRAY_AGG(
                DISTINCT dis.district_name
                ORDER BY dis.district_name
            ) FILTER (
                WHERE dis.district_name IS NOT NULL
                  AND dis.district_name <> ''
            ) AS district_names,

            ARRAY_AGG(
                DISTINCT d.department_name
                ORDER BY d.department_name
            ) FILTER (
                WHERE d.department_name IS NOT NULL
                  AND d.department_name <> ''
            ) AS department_names,

            COUNT(DISTINCT ofc.office_code) AS assigned_office_count,

            ARRAY_AGG(
                DISTINCT ofc.office_code
                ORDER BY ofc.office_code
            ) AS office_codes,

            (
                ARRAY_AGG(
                    DISTINCT ofc.office_name
                    ORDER BY ofc.office_name
                ) FILTER (
                    WHERE ofc.office_name IS NOT NULL
                      AND ofc.office_name <> ''
                )
            )[1:5] AS sample_office_names,

            'EXACT_EMAIL' AS match_type,
            1.0::float AS match_score

        FROM officer_assignments oa
        JOIN officers o
            ON o.officer_id = oa.officer_id
        JOIN offices ofc
            ON ofc.office_code = oa.office_code
        LEFT JOIN departments d
            ON d.department_code = ofc.department_code
        LEFT JOIN districts dis
            ON dis.district_id = ofc.district_id

        WHERE oa.is_active = TRUE
          AND LOWER(o.email) = %s
          AND (%s::text IS NULL OR oa.rti_role = %s::text)

        GROUP BY
            oa.rti_role,
            COALESCE(
                NULLIF(LOWER(o.email), ''),
                'no-email-' || o.officer_id::TEXT
            ),
            COALESCE(
                NULLIF(o.officer_name_search_key, ''),
                'no-name-' || o.officer_id::TEXT
            )

        ORDER BY
            oa.rti_role,
            o.officer_name

        LIMIT %s;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (email, role, role, limit))
            return list(cur.fetchall())


def search_officer_profiles_by_name(
    name_query: str,
    rti_role: str | None = None,
    district: str | None = None,
    department: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """
    Production-safe name lookup.

    Search order inside SQL:
    1. Exact Latin-normalized match
    2. Exact loose key match
    3. pg_trgm fuzzy match

    Example:
    Rajesh Kumar Rathor
    Rajesh Kumar Rathore
    राजेश कुमार राठौर
    """
    role = _normalize_role(rti_role)
    limit = _safe_limit(limit)

    keys = build_name_keys(name_query)

    if len(keys.normalized) < 4:
        return []

    conditions = ["oa.is_active = TRUE"]
    filter_params: list[Any] = []

    if role:
        conditions.append("oa.rti_role = %s")
        filter_params.append(role)

    if district:
        conditions.append(
            "LOWER(COALESCE(dis.district_name, '')) = LOWER(%s)"
        )
        filter_params.append(district.strip())

    if department:
        conditions.append(
            "LOWER(COALESCE(d.department_name, '')) = LOWER(%s)"
        )
        filter_params.append(department.strip())

    where_clause = " AND ".join(conditions)

    sql = f"""
        WITH candidate_officers AS (
            SELECT
                o.*,

                CASE
                    WHEN COALESCE(
                        o.officer_name_latin_normalized,
                        ''
                    ) = %s
                    THEN 'EXACT_NORMALIZED'

                    WHEN COALESCE(
                        o.officer_name_search_key,
                        ''
                    ) = %s
                    THEN 'EXACT_LOOSE_KEY'

                    ELSE 'FUZZY'
                END AS match_type,

                GREATEST(
                    similarity(
                        COALESCE(
                            o.officer_name_latin_normalized,
                            ''
                        ),
                        %s
                    ),
                    similarity(
                        COALESCE(
                            o.officer_name_search_key,
                            ''
                        ),
                        %s
                    )
                ) AS match_score

            FROM officers o

            WHERE
                COALESCE(
                    o.officer_name_latin_normalized,
                    ''
                ) = %s

                OR COALESCE(
                    o.officer_name_search_key,
                    ''
                ) = %s

                OR similarity(
                    COALESCE(
                        o.officer_name_latin_normalized,
                        ''
                    ),
                    %s
                ) >= %s

                OR similarity(
                    COALESCE(
                        o.officer_name_search_key,
                        ''
                    ),
                    %s
                ) >= %s
        )

        SELECT
            oa.rti_role,
            o.officer_id,
            o.officer_name,
            o.email,
            o.designation,
            o.match_type,
            o.match_score,

            ARRAY_AGG(
                DISTINCT dis.district_name
                ORDER BY dis.district_name
            ) FILTER (
                WHERE dis.district_name IS NOT NULL
                  AND dis.district_name <> ''
            ) AS district_names,

            ARRAY_AGG(
                DISTINCT d.department_name
                ORDER BY d.department_name
            ) FILTER (
                WHERE d.department_name IS NOT NULL
                  AND d.department_name <> ''
            ) AS department_names,

            COUNT(DISTINCT ofc.office_code) AS assigned_office_count,

            ARRAY_AGG(
                DISTINCT ofc.office_code
                ORDER BY ofc.office_code
            ) AS office_codes,

            (
                ARRAY_AGG(
                    DISTINCT ofc.office_name
                    ORDER BY ofc.office_name
                ) FILTER (
                    WHERE ofc.office_name IS NOT NULL
                      AND ofc.office_name <> ''
                )
            )[1:5] AS sample_office_names

        FROM candidate_officers o
        JOIN officer_assignments oa
            ON oa.officer_id = o.officer_id
        JOIN offices ofc
            ON ofc.office_code = oa.office_code
        LEFT JOIN departments d
            ON d.department_code = ofc.department_code
        LEFT JOIN districts dis
            ON dis.district_id = ofc.district_id

        WHERE {where_clause}

        GROUP BY
            oa.rti_role,
            o.officer_id,
            o.officer_name,
            o.email,
            o.designation,
            o.match_type,
            o.match_score

        ORDER BY
            CASE o.match_type
                WHEN 'EXACT_NORMALIZED' THEN 1
                WHEN 'EXACT_LOOSE_KEY' THEN 2
                ELSE 3
            END,
            o.match_score DESC,
            o.officer_name

        LIMIT %s;
    """

    params: list[Any] = [
        # Candidate SELECT
        keys.normalized,
        keys.search_key,
        keys.normalized,
        keys.search_key,

        # Candidate WHERE
        keys.normalized,
        keys.search_key,
        keys.normalized,
        NAME_CANDIDATE_FLOOR,
        keys.search_key,
        NAME_CANDIDATE_FLOOR,

        # Assignment-level filters
        *filter_params,

        # Final limit
        limit,
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())
        

def find_by_office_code(
    office_code: str,
    rti_role: str | None = None,
) -> list[dict[str, Any]]:
    """Find active PIO/FAA assignments for one official office code."""
    office_code = office_code.strip()
    role = _normalize_role(rti_role)

    if not office_code:
        return []

    sql = f"""
        {BASE_SELECT}
        WHERE oa.is_active = TRUE
          AND ofc.office_code = %s
          AND (%s::text IS NULL OR oa.rti_role = %s::text)
        ORDER BY oa.rti_role, o.officer_name
        LIMIT 20;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (office_code, role, role))
            return list(cur.fetchall())


def search_active_officers(
    search_text: str | None = None,
    rti_role: str | None = None,
    district: str | None = None,
    department: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Search active officer assignments using safe parameterized SQL.

    Supports partial Hindi/English office, officer, district,
    department, email, and designation matching.
    """
    role = _normalize_role(rti_role)
    limit = _safe_limit(limit)

    conditions = ["oa.is_active = TRUE"]
    params: list[Any] = []

    if role:
        conditions.append("oa.rti_role = %s")
        params.append(role)

    if district:
        conditions.append("LOWER(COALESCE(dis.district_name, '')) = LOWER(%s)")
        params.append(district.strip())

    if department:
        conditions.append(
            "LOWER(COALESCE(d.department_name, '')) = LOWER(%s)"
        )
        params.append(department.strip())

    if search_text:
        pattern = f"%{search_text.strip()}%"

        conditions.append(
            """
            (
                o.officer_name ILIKE %s
                OR o.email ILIKE %s
                OR o.designation ILIKE %s
                OR ofc.office_name ILIKE %s
                OR ofc.office_address ILIKE %s
                OR ofc.office_section_name ILIKE %s
                OR d.department_name ILIKE %s
                OR dis.district_name ILIKE %s
            )
            """
        )
        params.extend([pattern] * 8)

    where_clause = " AND ".join(conditions)

    sql = f"""
        {BASE_SELECT}
        WHERE {where_clause}
        ORDER BY
            oa.rti_role,
            dis.district_name,
            d.department_name,
            ofc.office_name,
            o.officer_name
        LIMIT %s;
    """

    params.append(limit)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())
        
def search_active_officer_summaries(
    search_text: str | None = None,
    rti_role: str | None = None,
    district: str | None = None,
    department: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Broad officer-list search.

    Groups multiple office registrations for the same officer into
    one chatbot-friendly summary. Do not use for exact office-code lookup.
    """
    role = _normalize_role(rti_role)
    limit = _safe_limit(limit)

    conditions = ["oa.is_active = TRUE"]
    params: list[Any] = []

    if role:
        conditions.append("oa.rti_role = %s")
        params.append(role)

    if district:
        conditions.append(
            "LOWER(COALESCE(dis.district_name, '')) = LOWER(%s)"
        )
        params.append(district.strip())

    if department:
        conditions.append(
            "LOWER(COALESCE(d.department_name, '')) = LOWER(%s)"
        )
        params.append(department.strip())

    if search_text:
        pattern = f"%{search_text.strip()}%"

        conditions.append(
            """
            (
                o.officer_name ILIKE %s
                OR o.email ILIKE %s
                OR o.designation ILIKE %s
                OR ofc.office_name ILIKE %s
                OR ofc.office_address ILIKE %s
                OR ofc.office_section_name ILIKE %s
                OR d.department_name ILIKE %s
                OR dis.district_name ILIKE %s
            )
            """
        )
        params.extend([pattern] * 8)

    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT
            oa.rti_role,

            o.officer_id,
            o.officer_name,
            o.email,
            o.designation,

            d.department_name,
            dis.district_name,

            COUNT(DISTINCT ofc.office_code) AS office_count,

            ARRAY_AGG(
                DISTINCT ofc.office_code
                ORDER BY ofc.office_code
            ) AS office_codes,

            ARRAY_AGG(
                DISTINCT ofc.office_name
                ORDER BY ofc.office_name
            ) FILTER (
                WHERE ofc.office_name IS NOT NULL
                  AND ofc.office_name <> ''
            ) AS office_names

        FROM officer_assignments oa
        JOIN officers o
            ON o.officer_id = oa.officer_id
        JOIN offices ofc
            ON ofc.office_code = oa.office_code
        LEFT JOIN departments d
            ON d.department_code = ofc.department_code
        LEFT JOIN districts dis
            ON dis.district_id = ofc.district_id

        WHERE {where_clause}

        GROUP BY
            oa.rti_role,
            o.officer_id,
            o.officer_name,
            o.email,
            o.designation,
            d.department_name,
            dis.district_name

        ORDER BY
            o.officer_name NULLS LAST,
            o.email NULLS LAST

        LIMIT %s;
    """

    params.append(limit)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())  
def search_officer_directory_summaries(
    search_text: str | None = None,
    rti_role: str | None = None,
    district: str | None = None,
    department: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Broad directory search.

    Groups repeated office assignments under the same officer email.
    Use this for broad list questions such as:
    'Show FAA in Balrampur School Education Department'.

    Do NOT use it for an exact office-code or exact school query.
    """
    role = _normalize_role(rti_role)
    limit = _safe_limit(limit)

    conditions = ["oa.is_active = TRUE"]
    params: list[Any] = []

    if role:
        conditions.append("oa.rti_role = %s")
        params.append(role)

    if district:
        conditions.append(
            "LOWER(COALESCE(dis.district_name, '')) = LOWER(%s)"
        )
        params.append(district.strip())

    if department:
        conditions.append(
            "LOWER(COALESCE(d.department_name, '')) = LOWER(%s)"
        )
        params.append(department.strip())

    if search_text:
        pattern = f"%{search_text.strip()}%"

        conditions.append(
            """
            (
                o.officer_name ILIKE %s
                OR o.email ILIKE %s
                OR o.designation ILIKE %s
                OR ofc.office_name ILIKE %s
                OR ofc.office_address ILIKE %s
                OR ofc.office_section_name ILIKE %s
                OR d.department_name ILIKE %s
                OR dis.district_name ILIKE %s
            )
            """
        )
        params.extend([pattern] * 8)

    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT
            oa.rti_role,

            COALESCE(
                NULLIF(LOWER(o.email), ''),
                NULLIF(LOWER(o.officer_name), ''),
                'unknown-' || o.officer_id::TEXT
            ) AS officer_group_key,

            MAX(o.officer_name) AS officer_name,
            MAX(o.email) AS email,

            ARRAY_AGG(
                DISTINCT o.designation
                ORDER BY o.designation
            ) FILTER (
                WHERE o.designation IS NOT NULL
                  AND o.designation <> ''
            ) AS designations,

            MAX(d.department_name) AS department_name,
            MAX(dis.district_name) AS district_name,

            COUNT(DISTINCT ofc.office_code) AS assigned_office_count,

            (
                ARRAY_AGG(
                DISTINCT ofc.office_name
                ORDER BY ofc.office_name
            ) FILTER (
                WHERE ofc.office_name IS NOT NULL
                AND ofc.office_name <> ''
            )
            )[1:5] AS sample_office_names

        FROM officer_assignments oa
        JOIN officers o
            ON o.officer_id = oa.officer_id
        JOIN offices ofc
            ON ofc.office_code = oa.office_code
        LEFT JOIN departments d
            ON d.department_code = ofc.department_code
        LEFT JOIN districts dis
            ON dis.district_id = ofc.district_id

        WHERE {where_clause}

        GROUP BY
            oa.rti_role,
            COALESCE(
                NULLIF(LOWER(o.email), ''),
                NULLIF(LOWER(o.officer_name), ''),
                'unknown-' || o.officer_id::TEXT
            )

        ORDER BY
            MAX(o.officer_name) NULLS LAST,
            MAX(o.email) NULLS LAST

        LIMIT %s;
    """

    params.append(limit)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

