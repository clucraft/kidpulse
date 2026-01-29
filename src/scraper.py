"""Playwright-based scraper for Playground."""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from bs4 import BeautifulSoup

from .config import PlaygroundConfig
from .models import Event, EventType, DailySummary

logger = logging.getLogger(__name__)

# Mapping of text patterns to event types
EVENT_PATTERNS = {
    r"checked in": EventType.CHECKIN,
    r"checked out": EventType.CHECKOUT,
    r"breakfast|lunch|dinner|snack|ate|meal|food": EventType.MEAL,
    r"nap started|started napping|fell asleep": EventType.NAP_START,
    r"nap ended|woke up|stopped napping": EventType.NAP_END,
    r"diaper|changed": EventType.DIAPER,
    r"potty|bathroom|toilet": EventType.POTTY,
    r"photo": EventType.PHOTO,
    r"video": EventType.VIDEO,
    r"incident|injury|hurt|accident": EventType.INCIDENT,
    r"medication|medicine": EventType.MEDICATION,
    r"announcement": EventType.ANNOUNCEMENT,
}

SESSION_DIR = Path("session_data")


class PlaygroundScraper:
    """Scraper for Playground childcare app."""

    def __init__(self, config: PlaygroundConfig):
        self.config = config
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        SESSION_DIR.mkdir(exist_ok=True)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self) -> None:
        """Start the browser."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        # Try to load existing session
        storage_path = SESSION_DIR / "storage_state.json"
        if storage_path.exists():
            logger.info("Loading existing session...")
            self.context = await self.browser.new_context(
                storage_state=str(storage_path)
            )
        else:
            self.context = await self.browser.new_context()

        self.page = await self.context.new_page()

    async def close(self) -> None:
        """Close the browser and save session."""
        if self.context:
            storage_path = SESSION_DIR / "storage_state.json"
            await self.context.storage_state(path=str(storage_path))
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, "playwright"):
            await self.playwright.stop()

    async def login(self) -> bool:
        """Login to Playground. Returns True if successful."""
        if not self.page:
            raise RuntimeError("Browser not started")

        logger.info("Navigating to Playground...")
        await self.page.goto(f"{self.config.base_url}/login")

        # Check if already logged in
        if await self._is_logged_in():
            logger.info("Already logged in")
            return True

        logger.info("Logging in...")
        try:
            # Wait for login form
            await self.page.wait_for_selector('input[type="email"], input[name="email"]', timeout=10000)

            # Fill credentials
            await self.page.fill('input[type="email"], input[name="email"]', self.config.email)
            await self.page.fill('input[type="password"]', self.config.password)

            # Click login button
            await self.page.click('button[type="submit"]')

            # Wait for navigation
            await self.page.wait_for_load_state("networkidle", timeout=15000)

            if await self._is_logged_in():
                logger.info("Login successful")
                return True
            else:
                logger.error("Login failed - not redirected to dashboard")
                return False

        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

    async def _is_logged_in(self) -> bool:
        """Check if currently logged in."""
        if not self.page:
            return False

        # Check URL - if we're on the feed/home page, we're logged in
        current_url = self.page.url
        if "/login" in current_url:
            return False

        # Look for common dashboard elements
        try:
            await self.page.wait_for_selector('[data-testid="feed"], .feed, .home, .dashboard', timeout=3000)
            return True
        except:
            return False

    async def get_daily_events(self, date: Optional[datetime] = None) -> DailySummary:
        """Scrape events for a given day (defaults to today)."""
        if not self.page:
            raise RuntimeError("Browser not started")

        if date is None:
            date = datetime.now()

        summary = DailySummary(date=date)

        logger.info(f"Fetching events for {date.strftime('%Y-%m-%d')}...")

        # Navigate to the feed/activity page
        await self.page.goto(f"{self.config.base_url}/feed")
        await self.page.wait_for_load_state("networkidle")

        # Wait for feed content to load
        try:
            await self.page.wait_for_selector('.feed-item, .activity-item, [data-testid="activity"]', timeout=10000)
        except:
            logger.warning("No feed items found - page structure may have changed")

        # Get page content and parse
        content = await self.page.content()
        events = self._parse_events(content, date)

        for event in events:
            summary.add_event(event)

        logger.info(f"Found {summary.event_count} events")
        return summary

    def _parse_events(self, html: str, date: datetime) -> list[Event]:
        """Parse events from HTML content."""
        soup = BeautifulSoup(html, "lxml")
        events = []

        # Look for activity/feed items - selectors may need adjustment based on actual structure
        # These are common patterns for activity feeds
        selectors = [
            ".feed-item",
            ".activity-item",
            "[data-testid='activity']",
            ".event-card",
            ".post",
            ".activity",
        ]

        items = []
        for selector in selectors:
            items.extend(soup.select(selector))

        for item in items:
            event = self._parse_event_item(item, date)
            if event:
                events.append(event)

        return events

    def _parse_event_item(self, item, date: datetime) -> Optional[Event]:
        """Parse a single event item."""
        try:
            # Extract text content
            text = item.get_text(separator=" ", strip=True)
            if not text:
                return None

            # Try to extract time
            time_match = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)?", text, re.IGNORECASE)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                ampm = time_match.group(3)
                if ampm and ampm.lower() == "pm" and hour != 12:
                    hour += 12
                elif ampm and ampm.lower() == "am" and hour == 12:
                    hour = 0
                timestamp = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                timestamp = date

            # Determine event type
            event_type = EventType.UNKNOWN
            text_lower = text.lower()
            for pattern, etype in EVENT_PATTERNS.items():
                if re.search(pattern, text_lower):
                    event_type = etype
                    break

            # Try to extract child name (usually at the start or in a specific element)
            child_name = None
            name_elem = item.select_one(".child-name, .student-name, [data-testid='child-name']")
            if name_elem:
                child_name = name_elem.get_text(strip=True)

            # Check for media
            media_url = None
            img = item.select_one("img")
            if img and img.get("src"):
                media_url = img["src"]
                if event_type == EventType.UNKNOWN:
                    event_type = EventType.PHOTO

            video = item.select_one("video")
            if video and video.get("src"):
                media_url = video["src"]
                event_type = EventType.VIDEO

            return Event(
                event_type=event_type,
                timestamp=timestamp,
                description=text[:200],  # Truncate long descriptions
                child_name=child_name,
                media_url=media_url,
            )

        except Exception as e:
            logger.warning(f"Failed to parse event item: {e}")
            return None

    async def screenshot(self, path: str = "debug_screenshot.png") -> None:
        """Take a screenshot for debugging."""
        if self.page:
            await self.page.screenshot(path=path)
            logger.info(f"Screenshot saved to {path}")
