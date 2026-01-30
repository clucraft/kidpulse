"""FastAPI web application for KidPulse."""

import asyncio
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

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

# Mount static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# Global state
_config: Optional[Config] = None
_scrape_lock = asyncio.Lock()
_next_scrape_time: Optional[str] = None
_serializer: Optional[URLSafeTimedSerializer] = None

SESSION_COOKIE = "kidpulse_session"
SESSION_MAX_AGE = 86400 * 7  # 7 days


def set_config(config: Config) -> None:
    """Set the global configuration."""
    global _config, _serializer
    _config = config
    _serializer = URLSafeTimedSerializer(config.auth.secret)


def set_next_scrape_time(time_str: str) -> None:
    """Set the next scheduled scrape time."""
    global _next_scrape_time
    _next_scrape_time = time_str


def get_config() -> Config:
    """Get the global configuration."""
    if not _config:
        raise HTTPException(status_code=500, detail="Configuration not loaded")
    return _config


# ============== Auth Helpers ==============

def create_session_token(username: str) -> str:
    """Create a signed session token."""
    return _serializer.dumps({"user": username})


def verify_session_token(token: str) -> Optional[str]:
    """Verify a session token and return the username, or None if invalid."""
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("user")
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request) -> Optional[str]:
    """Get the current user from session cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return verify_session_token(token)


def require_auth(request: Request) -> str:
    """Dependency that requires authentication."""
    config = get_config()

    # If auth is disabled, allow access
    if not config.auth.enabled:
        return "anonymous"

    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def check_auth_or_redirect(request: Request) -> Optional[RedirectResponse]:
    """Check auth and return redirect response if not authenticated."""
    config = get_config()

    if not config.auth.enabled:
        return None

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return None


# ============== Auth Endpoints ==============

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    """Login page."""
    config = get_config()

    # If auth disabled or already logged in, redirect to dashboard
    if not config.auth.enabled or get_current_user(request):
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
    })


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Process login."""
    config = get_config()

    if username == config.auth.username and password == config.auth.password:
        token = create_session_token(username)
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
        return response

    return RedirectResponse(url="/login?error=Invalid+credentials", status_code=302)


@app.get("/logout")
async def logout():
    """Log out and clear session."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/auth/magic/{token}")
async def magic_login(token: str):
    """Magic link login - validates token and creates session."""
    config = get_config()

    # Validate the magic token
    if not await storage.validate_magic_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired magic link")

    # Mark token as used (optional - could allow reuse within validity period)
    # await storage.mark_token_used(token)

    # Create session and redirect to dashboard
    session_token = create_session_token(config.auth.username)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


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
            "auth_enabled": _config.auth.enabled if _config else False,
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


@app.get("/api/children")
async def get_children():
    """Get list of all children."""
    children = await storage.get_all_children()
    return {"children": children}


@app.get("/api/stats/{child_name}")
async def get_child_stats(child_name: str, days: int = 14):
    """Get historical stats for a child for charting."""
    stats = await storage.get_child_stats(child_name, days)
    return {"child": child_name, "days": stats}


@app.post("/api/scrape")
async def trigger_scrape(background_tasks: BackgroundTasks, notify: bool = False):
    """Manually trigger a scrape. Notifications disabled by default for manual scrapes."""
    if _scrape_lock.locked():
        raise HTTPException(status_code=409, detail="Scrape already in progress")

    if not _config:
        raise HTTPException(status_code=500, detail="Configuration not loaded")

    background_tasks.add_task(run_scrape, notify)
    return {"message": "Scrape started", "notify": notify}


@app.post("/api/magic-link")
async def create_magic_link():
    """Create a magic login link (valid for 24 hours)."""
    if not _config:
        raise HTTPException(status_code=500, detail="Configuration not loaded")

    if not _config.auth.enabled:
        raise HTTPException(status_code=400, detail="Authentication is not enabled")

    token = await storage.create_magic_token(hours_valid=24)
    magic_link = f"{_config.base_url}/auth/magic/{token}"
    return {"magic_link": magic_link, "expires_in": "24 hours"}


@app.post("/api/notify")
async def send_manual_notification():
    """Send a notification with today's summary."""
    if not _config:
        raise HTTPException(status_code=500, detail="Configuration not loaded")

    today = date.today()
    result = await storage.get_summary(today)

    if not result or not result.get("data"):
        raise HTTPException(status_code=404, detail="No data for today to send")

    # Rebuild summary from stored data
    from ..models import DailySummary
    summary = DailySummary.from_dict(result["data"])

    ntfy = NtfyNotifier(_config.ntfy) if _config.ntfy.enabled else None
    telegram = TelegramNotifier(_config.telegram) if _config.telegram.enabled else None
    notification_manager = NotificationManager(ntfy=ntfy, telegram=telegram)

    # Generate magic link if auth is enabled
    magic_link = None
    if _config.auth.enabled:
        token = await storage.create_magic_token(hours_valid=24)
        magic_link = f"{_config.base_url}/auth/magic/{token}"

    await notification_manager.send_summary(summary, magic_link=magic_link)
    return {"message": "Notification sent", "magic_link_included": magic_link is not None}


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

                # Split events by date and save separate summaries for each date
                summaries_by_date = await storage.split_and_save_by_date(summary)

                # Count total events across all dates
                total_events = sum(
                    len(child.bottles) + len(child.diapers) +
                    len(child.naps) + len(child.fluids) + len(child.meals) +
                    (1 if child.sign_in else 0) + (1 if child.sign_out else 0)
                    for child in summary.children.values()
                )

                dates_saved = list(summaries_by_date.keys())
                await storage.log_scrape(True, f"Found {total_events} events for dates: {', '.join(dates_saved)}", total_events)

                # Send notifications if requested (only for today's summary)
                if notify and total_events > 0:
                    today_str = date.today().isoformat()
                    if today_str in summaries_by_date:
                        ntfy = NtfyNotifier(_config.ntfy) if _config.ntfy.enabled else None
                        telegram = TelegramNotifier(_config.telegram) if _config.telegram.enabled else None
                        notification_manager = NotificationManager(ntfy=ntfy, telegram=telegram)

                        # Generate magic link for notifications
                        magic_link = None
                        if _config.auth.enabled:
                            token = await storage.create_magic_token(hours_valid=24)
                            magic_link = f"{_config.base_url}/auth/magic/{token}"

                        # Send notification for today's events only
                        today_summary = summaries_by_date[today_str]
                        await notification_manager.send_summary(today_summary, magic_link=magic_link)

                logger.info(f"Scrape completed: {total_events} events for {len(dates_saved)} date(s)")

        except Exception as e:
            logger.exception(f"Scrape failed: {e}")
            await storage.log_scrape(False, str(e))


# ============== Web Dashboard ==============

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    # Check authentication
    redirect = await check_auth_or_redirect(request)
    if redirect:
        return redirect

    today = date.today()
    yesterday = today - timedelta(days=1)
    summary = await storage.get_summary(today)
    last_scrape = await storage.get_last_scrape()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "today": today.isoformat(),
        "yesterday": yesterday.isoformat(),
        "summary": summary["data"] if summary else None,
        "updated_at": summary["updated_at"] if summary else None,
        "last_scrape": last_scrape,
        "next_scheduled": _next_scrape_time,
        "config": _config,
        "user": get_current_user(request),
    })


@app.get("/day/{date_str}", response_class=HTMLResponse)
async def day_view(request: Request, date_str: str):
    """View a specific day's data."""
    # Check authentication
    redirect = await check_auth_or_redirect(request)
    if redirect:
        return redirect

    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    today = date.today()
    yesterday = today - timedelta(days=1)
    summary = await storage.get_summary(date_obj)
    last_scrape = await storage.get_last_scrape()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "today": today.isoformat(),
        "yesterday": yesterday.isoformat(),
        "summary": summary["data"] if summary else None,
        "updated_at": summary["updated_at"] if summary else None,
        "last_scrape": last_scrape,
        "next_scheduled": _next_scrape_time,
        "config": _config,
        "viewing_date": date_str,
        "user": get_current_user(request),
    })
