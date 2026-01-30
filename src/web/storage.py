"""SQLite storage for KidPulse data."""

import json
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo
import aiosqlite

from ..models import DailySummary, ChildSummary

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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS magic_tokens (
                token TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0
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


async def split_and_save_by_date(summary: DailySummary) -> dict[str, DailySummary]:
    """Split a summary by event dates and save separate summaries for each date.

    Returns a dict mapping date strings to their DailySummary objects.
    """
    from collections import defaultdict

    # Group events by date for each child
    events_by_date: dict[str, dict[str, ChildSummary]] = defaultdict(dict)

    for child_name, child in summary.children.items():
        # Process ALL sign_in events (from multi-day feeds)
        for sign_in_time in child.sign_in_events:
            date_str = sign_in_time.date().isoformat()
            if child_name not in events_by_date[date_str]:
                events_by_date[date_str][child_name] = ChildSummary(name=child_name)
            events_by_date[date_str][child_name].sign_in = sign_in_time

        # Process ALL sign_out events (from multi-day feeds)
        for sign_out_time in child.sign_out_events:
            date_str = sign_out_time.date().isoformat()
            if child_name not in events_by_date[date_str]:
                events_by_date[date_str][child_name] = ChildSummary(name=child_name)
            events_by_date[date_str][child_name].sign_out = sign_out_time

        # Process bottles
        for bottle in child.bottles:
            date_str = bottle.time.date().isoformat()
            if child_name not in events_by_date[date_str]:
                events_by_date[date_str][child_name] = ChildSummary(name=child_name)
            events_by_date[date_str][child_name].bottles.append(bottle)

        # Process fluids
        for fluid in child.fluids:
            date_str = fluid.time.date().isoformat()
            if child_name not in events_by_date[date_str]:
                events_by_date[date_str][child_name] = ChildSummary(name=child_name)
            events_by_date[date_str][child_name].fluids.append(fluid)

        # Process diapers
        for diaper in child.diapers:
            date_str = diaper.time.date().isoformat()
            if child_name not in events_by_date[date_str]:
                events_by_date[date_str][child_name] = ChildSummary(name=child_name)
            events_by_date[date_str][child_name].diapers.append(diaper)

        # Process naps
        for nap in child.naps:
            date_str = nap.start_time.date().isoformat()
            if child_name not in events_by_date[date_str]:
                events_by_date[date_str][child_name] = ChildSummary(name=child_name)
            events_by_date[date_str][child_name].naps.append(nap)

        # Process meals
        for meal in child.meals:
            date_str = meal.time.date().isoformat()
            if child_name not in events_by_date[date_str]:
                events_by_date[date_str][child_name] = ChildSummary(name=child_name)
            events_by_date[date_str][child_name].meals.append(meal)

    # Create and save summaries for each date
    result = {}
    for date_str, children in events_by_date.items():
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        daily_summary = DailySummary(date=date_obj)
        daily_summary.children = children

        # Merge with existing data for this date (don't overwrite)
        existing = await get_summary(date_obj.date())
        if existing and existing.get("data"):
            existing_data = existing["data"]
            for child_name, existing_child in existing_data.get("children", {}).items():
                if child_name in daily_summary.children:
                    # Merge: keep existing sign_in/out if new ones are missing
                    new_child = daily_summary.children[child_name]
                    if not new_child.sign_in and existing_child.get("sign_in"):
                        new_child.sign_in = datetime.fromisoformat(existing_child["sign_in"])
                    if not new_child.sign_out and existing_child.get("sign_out"):
                        new_child.sign_out = datetime.fromisoformat(existing_child["sign_out"])

        await save_summary(daily_summary)
        result[date_str] = daily_summary
        logger.info(f"Split and saved {len(children)} children's events for {date_str}")

    return result


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


async def get_child_stats(child_name: str, days: int = 14) -> list[dict]:
    """Get historical stats for a child for charting.

    Returns daily aggregated stats for the specified number of days.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT date, data FROM summaries ORDER BY date DESC LIMIT ?",
            (days,)
        ) as cursor:
            rows = await cursor.fetchall()

    stats = []
    first_name = child_name.split()[0].lower()

    for row in rows:
        date_str = row[0]
        data = json.loads(row[1])

        # Find this child's data
        child_data = None
        for name, child in data.get("children", {}).items():
            if name.split()[0].lower() == first_name:
                child_data = child
                break

        if child_data:
            totals = child_data.get("totals", {})
            stats.append({
                "date": date_str,
                "nap_minutes": totals.get("nap_minutes", 0) or 0,
                "wet_diapers": totals.get("wet_diapers", 0) or 0,
                "bm_diapers": totals.get("bm_diapers", 0) or 0,
                "bottle_oz": totals.get("bottle_oz", 0) or 0,
                "fluids_oz": totals.get("fluids_oz", 0) or 0,
                "meals_count": totals.get("meals_count", 0) or 0,
            })
        else:
            # No data for this child on this date
            stats.append({
                "date": date_str,
                "nap_minutes": 0,
                "wet_diapers": 0,
                "bm_diapers": 0,
                "bottle_oz": 0,
                "fluids_oz": 0,
                "meals_count": 0,
            })

    # Reverse to get chronological order (oldest first)
    stats.reverse()
    return stats


async def get_all_children() -> list[str]:
    """Get list of all child names from the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT data FROM summaries ORDER BY date DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                data = json.loads(row[0])
                return list(data.get("children", {}).keys())
    return []


async def create_magic_token(hours_valid: int = 24) -> str:
    """Create a magic login token that expires after specified hours."""
    import secrets
    from datetime import timedelta

    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(hours=hours_valid)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO magic_tokens (token, created_at, expires_at, used)
            VALUES (?, ?, ?, 0)
        """, (token, now.isoformat(), expires.isoformat()))
        await db.commit()

    return token


async def validate_magic_token(token: str) -> bool:
    """Validate a magic token. Returns True if valid and not expired."""
    now = _now()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT expires_at, used FROM magic_tokens WHERE token = ?",
            (token,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False

            expires_at = datetime.fromisoformat(row["expires_at"])
            # Make expires_at timezone-aware if it isn't
            if expires_at.tzinfo is None:
                tz_name = os.getenv("TZ", "UTC")
                try:
                    tz = ZoneInfo(tz_name)
                except Exception:
                    tz = ZoneInfo("UTC")
                expires_at = expires_at.replace(tzinfo=tz)

            if row["used"] or now > expires_at:
                return False

            return True


async def mark_token_used(token: str) -> None:
    """Mark a magic token as used."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE magic_tokens SET used = 1 WHERE token = ?",
            (token,)
        )
        await db.commit()


async def cleanup_expired_tokens() -> None:
    """Remove expired magic tokens."""
    now = _now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM magic_tokens WHERE expires_at < ?",
            (now,)
        )
        await db.commit()
