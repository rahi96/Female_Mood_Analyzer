"""MySQL database utility for read-only queries."""

from __future__ import annotations

import queue
import threading
from contextlib import contextmanager
from typing import Any
import logging

import httpx
import pymysql
from pymysql.cursors import DictCursor

from ai.config import settings

logger = logging.getLogger(__name__)

# Reuse TCP connections to remote RDS instead of a fresh handshake per query -
# a single endpoint can issue 10+ sequential queries, which was previously
# opening 10+ new connections and causing multi-second/timeout latency.
_POOL_MAX_SIZE = 20
_pool: "queue.LifoQueue[pymysql.connections.Connection]" = queue.LifoQueue(maxsize=_POOL_MAX_SIZE)
_pool_lock = threading.Lock()
_pool_size = 0


def _create_connection() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        cursorclass=DictCursor,
        connect_timeout=10,  # Prevent indefinite hanging on connection
        read_timeout=15,     # Prevent hanging on query results
        write_timeout=15,    # Prevent hanging on query execution
    )


@contextmanager
def get_connection():
    """Get a pooled MySQL connection context manager."""
    global _pool_size
    conn = None
    try:
        conn = _pool.get_nowait()
        conn.ping(reconnect=True)  # Discard stale/dropped connections transparently
    except queue.Empty:
        with _pool_lock:
            _pool_size += 1
        conn = _create_connection()

    try:
        yield conn
    except Exception:
        # Connection may be in a bad state after an error - don't return it to the pool
        try:
            conn.close()
        finally:
            with _pool_lock:
                _pool_size -= 1
        raise
    else:
        try:
            _pool.put_nowait(conn)
        except queue.Full:
            conn.close()
            with _pool_lock:
                _pool_size -= 1


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


def get_active_journey(user_id: int, journey_title: str) -> dict[str, Any] | None:
    """Resolve a user's profile_id/journey_id for a named journey via life_journey_profile.

    This is the multi-journey source of truth (a profile can have several
    active journeys at once, e.g. Beauty + Pregnancy + Lifelong Thriving).
    profiles.life_stage_id is a single legacy scalar and cannot represent
    that, so journey-specific endpoints (pregnancy, postpartum, perimenopause,
    etc.) must gate on this join instead of on life_stage_id or on the mere
    presence of rows in their own data tables.

    Returns {profile_id, journey_id, journey_title} or None if the journey
    is not active for this user.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.id AS profile_id, lj.id AS journey_id, lj.title AS journey_title
            FROM profiles p
            JOIN life_journey_profile ljp ON ljp.profile_id = p.id
            JOIN life_journeys lj ON lj.id = ljp.life_journey_id
            WHERE p.user_id = %s AND lj.title = %s
            LIMIT 1
            """,
            (user_id, journey_title),
        )
        return cursor.fetchone()


def get_active_journey_by_ids(user_id: int, journey_ids: list[int]) -> dict[str, Any] | None:
    """Same as get_active_journey but matches on journey id instead of title.

    Use this when the same real-world journey is represented by more than one
    life_journeys row (e.g. duplicate/legacy title variants) so callers don't
    have to pick a single title string and risk missing users linked to the
    other variant.
    """
    if not journey_ids:
        return None
    with get_connection() as conn:
        cursor = conn.cursor()
        placeholders = ",".join(["%s"] * len(journey_ids))
        cursor.execute(
            f"""
            SELECT p.id AS profile_id, lj.id AS journey_id, lj.title AS journey_title
            FROM profiles p
            JOIN life_journey_profile ljp ON ljp.profile_id = p.id
            JOIN life_journeys lj ON lj.id = ljp.life_journey_id
            WHERE p.user_id = %s AND lj.id IN ({placeholders})
            LIMIT 1
            """,
            (user_id, *journey_ids),
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


def query_db(query: str, params: tuple = None) -> list[dict[str, Any]]:
    """Execute a generic SELECT query and return results as list of dicts."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            return list(cursor.fetchall())
    except pymysql.OperationalError as e:
        # Database connection failed - MUST use real AWS data only, no fallback
        logger.error(f"Database connection failed ({e}). Cannot proceed without AWS RDS data.")
        raise RuntimeError(f"Database connection error: {e}. AWS RDS is unavailable.")
    except Exception as e:
        # Query execution failed - MUST use real AWS data only, no fallback
        logger.error(f"Database query failed ({e}). Cannot proceed without AWS RDS data.")
        raise RuntimeError(f"Database query error: {e}. Cannot execute AWS RDS query.")


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
