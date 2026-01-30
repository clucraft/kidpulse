"""SQLite storage for KidPulse data."""

import json
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo
import aiosqlite

from ..models import DailySummary

logger = logging.getLogger(__name__)


def _now() -> datetime:
    """Get current time in configured timezone."""
    tz_name = os.getenv("TZ", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)

DB_PATH = Path("session_data/kidpulse.db")


async def init_db() -> None:
    """Initialize the database schema."""
    DB_PATH.parent.mkdir(exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                date TEXT PRIMARY KEY,
                data JSON NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scrape_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                success INTEGER NOT NULL,
                message TEXT,
                events_count INTEGER
            )
        """)
        await db.commit()


async def save_summary(summary: DailySummary) -> None:
    """Save a daily summary to the database."""
    date_str = summary.date.strftime("%Y-%m-%d")
    now = _now().strftime("%Y-%m-%d %H:%M:%S")
    data = json.dumps(summary.to_dict())

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO summaries (date, data, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
        """, (date_str, data, now, now))
        await db.commit()

    logger.info(f"Saved summary for {date_str}")


async def get_summary(date_obj: date) -> Optional[dict]:
    """Get a summary for a specific date."""
    date_str = date_obj.strftime("%Y-%m-%d")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT data, updated_at FROM summaries WHERE date = ?",
            (date_str,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "data": json.loads(row["data"]),
                    "updated_at": row["updated_at"]
                }
    return None


async def get_available_dates(limit: int = 30) -> list[str]:
    """Get list of dates with data."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT date FROM summaries ORDER BY date DESC LIMIT ?",
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def log_scrape(success: bool, message: str = None, events_count: int = 0) -> None:
    """Log a scrape attempt."""
    now = _now().strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO scrape_log (timestamp, success, message, events_count)
            VALUES (?, ?, ?, ?)
        """, (now, 1 if success else 0, message, events_count))
        await db.commit()


async def get_last_scrape() -> Optional[dict]:
    """Get the last scrape log entry."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM scrape_log ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
    return None


async def get_scrape_history(limit: int = 20) -> list[dict]:
    """Get recent scrape history."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM scrape_log ORDER BY id DESC LIMIT ?",
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
