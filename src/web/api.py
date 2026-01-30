"""FastAPI web application for KidPulse."""

import asyncio
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..config import Config
from ..scraper import PlaygroundScraper
from ..notifiers import NtfyNotifier, TelegramNotifier, NotificationManager
from . import storage

logger = logging.getLogger(__name__)

app = FastAPI(
    title="KidPulse API",
    description="Daily event scraper for Playground childcare app",
    version="1.0.0",
)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# Global state
_config: Optional[Config] = None
_scrape_lock = asyncio.Lock()
_next_scrape_time: Optional[str] = None


def set_config(config: Config) -> None:
    """Set the global configuration."""
    global _config
    _config = config


def set_next_scrape_time(time_str: str) -> None:
    """Set the next scheduled scrape time."""
    global _next_scrape_time
    _next_scrape_time = time_str


# ============== API Endpoints ==============

@app.get("/api/status")
async def get_status():
    """Get the current scraper status."""
    last_scrape = await storage.get_last_scrape()
    return {
        "status": "running",
        "last_scrape": last_scrape,
        "next_scheduled": _next_scrape_time,
        "config": {
            "ntfy_enabled": _config.ntfy.enabled if _config else False,
            "telegram_enabled": _config.telegram.enabled if _config else False,
            "summary_time": _config.summary_time if _config else None,
        } if _config else None,
    }


@app.get("/api/summary/today")
async def get_today_summary():
    """Get today's summary."""
    today = date.today()
    result = await storage.get_summary(today)
    if not result:
        return {"date": today.isoformat(), "data": None, "message": "No data for today yet"}
    return {"date": today.isoformat(), **result}


@app.get("/api/summary/{date_str}")
async def get_summary_by_date(date_str: str):
    """Get summary for a specific date (YYYY-MM-DD)."""
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    result = await storage.get_summary(date_obj)
    if not result:
        raise HTTPException(status_code=404, detail=f"No data for {date_str}")
    return {"date": date_str, **result}


@app.get("/api/history")
async def get_history(limit: int = 30):
    """Get list of available dates with data."""
    dates = await storage.get_available_dates(limit)
    return {"dates": dates, "count": len(dates)}


@app.get("/api/scrape-log")
async def get_scrape_log(limit: int = 20):
    """Get recent scrape history."""
    history = await storage.get_scrape_history(limit)
    return {"history": history}


@app.post("/api/scrape")
async def trigger_scrape(background_tasks: BackgroundTasks, notify: bool = True):
    """Manually trigger a scrape."""
    if _scrape_lock.locked():
        raise HTTPException(status_code=409, detail="Scrape already in progress")

    if not _config:
        raise HTTPException(status_code=500, detail="Configuration not loaded")

    background_tasks.add_task(run_scrape, notify)
    return {"message": "Scrape started", "notify": notify}


async def run_scrape(notify: bool = True) -> None:
    """Run the scraper (called as background task)."""
    async with _scrape_lock:
        try:
            async with PlaygroundScraper(_config.playground, _config.ai) as scraper:
                if not await scraper.login():
                    await storage.log_scrape(False, "Login failed")
                    logger.error("Scrape failed: login failed")
                    return

                summary = await scraper.get_daily_events(timezone=_config.timezone)

                # Count total events
                total_events = sum(
                    len(child.bottles) + len(child.diapers) +
                    len(child.naps) + len(child.fluids) +
                    (1 if child.sign_in else 0) + (1 if child.sign_out else 0)
                    for child in summary.children.values()
                )

                # Save to database
                await storage.save_summary(summary)
                await storage.log_scrape(True, f"Found {total_events} events", total_events)

                # Send notifications if requested
                if notify and total_events > 0:
                    ntfy = NtfyNotifier(_config.ntfy) if _config.ntfy.enabled else None
                    telegram = TelegramNotifier(_config.telegram) if _config.telegram.enabled else None
                    notification_manager = NotificationManager(ntfy=ntfy, telegram=telegram)
                    await notification_manager.send_summary(summary)

                logger.info(f"Scrape completed: {total_events} events")

        except Exception as e:
            logger.exception(f"Scrape failed: {e}")
            await storage.log_scrape(False, str(e))


# ============== Web Dashboard ==============

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    today = date.today()
    summary = await storage.get_summary(today)
    last_scrape = await storage.get_last_scrape()
    available_dates = await storage.get_available_dates(7)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "today": today.isoformat(),
        "summary": summary["data"] if summary else None,
        "updated_at": summary["updated_at"] if summary else None,
        "last_scrape": last_scrape,
        "next_scheduled": _next_scrape_time,
        "available_dates": available_dates,
        "config": _config,
    })


@app.get("/day/{date_str}", response_class=HTMLResponse)
async def day_view(request: Request, date_str: str):
    """View a specific day's data."""
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    summary = await storage.get_summary(date_obj)
    last_scrape = await storage.get_last_scrape()
    available_dates = await storage.get_available_dates(7)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "today": date_str,
        "summary": summary["data"] if summary else None,
        "updated_at": summary["updated_at"] if summary else None,
        "last_scrape": last_scrape,
        "next_scheduled": _next_scrape_time,
        "available_dates": available_dates,
        "config": _config,
        "viewing_date": date_str,
    })
