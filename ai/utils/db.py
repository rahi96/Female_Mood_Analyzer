"""MySQL database utility for read-only queries."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import httpx
import pymysql
from pymysql.cursors import DictCursor

from ai.config import settings


@contextmanager
def get_connection():
    """Get a MySQL connection context manager."""
    conn = pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        cursorclass=DictCursor,
    )
    try:
        yield conn
    finally:
        conn.close()


def get_user_profile(user_id: int) -> dict[str, Any] | None:
    """Fetch user profile from users + profiles tables."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT u.*, p.*
            FROM users u
            LEFT JOIN profiles p ON u.id = p.user_id
            WHERE u.id = %s
            """,
            (user_id,),
        )
        return cursor.fetchone()


def get_current_cycle(user_id: int) -> dict[str, Any] | None:
    """Fetch current (incomplete) menstrual cycle for user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM menstrual_cycles
            WHERE user_id = %s AND is_completed = 0
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        )
        return cursor.fetchone()


def get_bbt_logs(user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """Fetch BBT logs for user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM bbt_logs
            WHERE user_id = %s
            ORDER BY log_date DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        return list(cursor.fetchall())


def get_opk_logs(cycle_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """Fetch OPK logs for a cycle."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM opk_logs
            WHERE cycle_id = %s
            ORDER BY log_date DESC
            LIMIT %s
            """,
            (cycle_id, limit),
        )
        return list(cursor.fetchall())


def get_mucus_logs(cycle_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """Fetch cervical mucus logs for a cycle."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM cervical_mucus_logs
            WHERE cycle_id = %s
            ORDER BY log_date DESC
            LIMIT %s
            """,
            (cycle_id, limit),
        )
        return list(cursor.fetchall())


def get_period_logs(user_id: int, limit: int = 12) -> list[dict[str, Any]]:
    """Fetch period/menstrual cycle history for user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM menstrual_cycles
            WHERE user_id = %s
            ORDER BY period_start_date DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        return list(cursor.fetchall())


def get_health_logs(user_id: int, limit: int = 60) -> list[dict[str, Any]]:
    """Fetch health logs for user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM health_logs
            WHERE user_id = %s
            ORDER BY log_date DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        return list(cursor.fetchall())


def get_skin_scans(user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch skin scans for user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM skin_scans
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        return list(cursor.fetchall())


def get_lab_reports(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch lab reports for user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM lab_reports
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        return list(cursor.fetchall())


def get_snapshot(user_id: int) -> dict[str, Any]:
    """
    Fetch complete snapshot data for user (replaces Laravel /snapshot API).
    Returns combined data from multiple tables.
    """
    profile = get_user_profile(user_id)
    cycle = get_current_cycle(user_id)
    cycle_id = cycle["id"] if cycle else None

    return {
        "user_id": user_id,
        "profile": profile,
        "current_cycle": cycle,
        "bbt_logs": get_bbt_logs(user_id),
        "opk_logs": get_opk_logs(cycle_id) if cycle_id else [],
        "mucus_logs": get_mucus_logs(cycle_id) if cycle_id else [],
        "period_logs": get_period_logs(user_id),
    }


def user_exists(user_id: int) -> bool:
    """Check if user exists in users table."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        return cursor.fetchone() is not None


def fetch_calendar_inputs_from_backend(user_id: int) -> dict[str, Any]:
    """
    Fetch cycle calendar inputs from Laravel backend.
    Returns raw backend response with calendar input data.
    """
    url = f"{settings.BACKEND_URL}/cycle-calendar-inputs/{user_id}"
    
    try:
        response = httpx.get(url, timeout=15.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise Exception(f"Backend API error: {exc.response.status_code} - {exc.response.text}")
    except httpx.RequestError as exc:
        raise Exception(f"Failed to connect to backend: {exc}")
