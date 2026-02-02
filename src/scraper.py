"""Playwright-based scraper for Playground."""

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from .config import PlaygroundConfig, AIConfig
from .models import (
    DailySummary,
    ChildSummary,
    DiaperEvent,
    BottleEvent,
    FluidsEvent,
    NappingEvent,
    EatingEvent,
    EventType,
    Event,
)
from .ai_parser import AIParser

logger = logging.getLogger(__name__)

SESSION_DIR = Path("session_data")


class PlaygroundScraper:
    """Scraper for Playground childcare app."""

    def __init__(self, config: PlaygroundConfig, ai_config: Optional[AIConfig] = None):
        self.config = config
        self.ai_config = ai_config
        self.ai_parser = AIParser(ai_config) if ai_config else None
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
        await self.page.goto(f"{self.config.base_url}/signin")
        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(3)  # Wait for React to render and any redirects

        # Check current URL - if not on signin page, we're logged in
        current_url = self.page.url
        logger.info(f"Current URL after signin navigation: {current_url}")

        if "/signin" not in current_url:
            logger.info("Redirected away from signin - already logged in")
            return True

        # Check if login form exists - if not, we're already logged in
        email_input = await self.page.query_selector('input[placeholder*="Email" i]')

        if not email_input:
            logger.info("No login form found - assuming logged in")
            await self.screenshot("no_form_found.png")
            return True

        logger.info("Login form found, filling credentials...")
        try:
            # Fill credentials
            await email_input.fill(self.config.email)

            password_input = await self.page.query_selector('input[placeholder*="Password" i]')
            if password_input:
                await password_input.fill(self.config.password)

            # Click login button
            login_btn = await self.page.query_selector('button:has-text("Log in")')
            if login_btn:
                await login_btn.click()

            # Wait for page to process login
            await asyncio.sleep(5)
            await self.page.wait_for_load_state("networkidle", timeout=10000)

            logger.info("Login submitted, proceeding...")
            return True

        except Exception as e:
            # Even if there was an error, check if we ended up logged in
            logger.warning(f"Login operation had issue: {e}")
            await self.screenshot("login_issue.png")

            # Check if we're now on a non-signin page (meaning login worked)
            current_url = self.page.url
            if "/signin" not in current_url:
                logger.info(f"Despite error, now at {current_url} - login likely succeeded")
                return True

            # Check if login form is gone
            email_input = await self.page.query_selector('input[placeholder*="Email" i]')
            if not email_input:
                logger.info("Login form gone - assuming login succeeded")
                return True

            logger.error("Login truly failed")
            return False

    async def get_daily_events(self, date: Optional[datetime] = None, timezone: str = "America/New_York") -> DailySummary:
        """Scrape events for all children for a given day (defaults to today)."""
        if not self.page:
            raise RuntimeError("Browser not started")

        if date is None:
            # Use configured timezone for "today"
            tz = ZoneInfo(timezone)
            date = datetime.now(tz)
            logger.info(f"Using timezone {timezone}, current date: {date.strftime('%Y-%m-%d %H:%M')}")

        summary = DailySummary(date=date)

        # Navigate to the feed page
        if self.config.organization:
            feed_url = f"{self.config.base_url}/app/{self.config.organization}/parent/feed"
            logger.info(f"Navigating to feed: {feed_url}")
            await self.page.goto(feed_url)
        else:
            # Try to find and click Feed link, or navigate to current URL's feed
            logger.info("Looking for feed page...")
            current_url = self.page.url

            # If already on a feed page, stay there
            if "/feed" in current_url:
                logger.info(f"Already on feed: {current_url}")
            else:
                # Try clicking Feed in navigation
                try:
                    await self.page.click('text="Feed"', timeout=5000)
                except:
                    # Try navigating to /feed from current app URL
                    if "/app/" in current_url:
                        base_app_url = current_url.split("/parent")[0] if "/parent" in current_url else current_url.rstrip("/")
                        feed_url = f"{base_app_url}/parent/feed"
                        logger.info(f"Navigating to: {feed_url}")
                        await self.page.goto(feed_url)

        # Wait for page to load (don't use networkidle - feed may have continuous polling)
        await self.page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(5)  # Give React time to render feed content

        # Get list of children (tabs)
        children = await self._get_child_tabs()
        logger.info(f"Found {len(children)} children: {children}")

        # Scrape each child's feed
        for i, child_name in enumerate(children):
            logger.info(f"Scraping events for {child_name}...")

            # Always click the tab to ensure we're on the right child's feed
            # (don't assume the first child is selected by default)
            clicked = await self._select_child_tab(child_name)
            if not clicked:
                logger.warning(f"Failed to select tab for {child_name}, skipping")
                continue
            await asyncio.sleep(2)  # Wait for feed to fully update

            child_summary = await self._scrape_child_feed(child_name, date)
            summary.children[child_name] = child_summary

        # Note: Events may span multiple dates. The storage layer will split
        # events by their actual date and save separate summaries.
        return summary

    async def _get_child_tabs(self) -> list[str]:
        """Get list of child names from tabs."""
        try:
            # Look for tab elements - adjust selector based on actual structure
            tabs = await self.page.query_selector_all('[role="tab"], .child-tab, button[class*="tab"]')

            children = []
            for tab in tabs:
                text = await tab.inner_text()
                text = text.strip()
                if text and not text.lower() in ["feed", "home", "calendar", "chat"]:
                    children.append(text)

            # If no tabs found, try to get child name from header or first feed item
            if not children:
                # Try getting from the page content
                content = await self.page.content()
                # Look for patterns like "Ezra Aschenberg" in tabs area
                tab_area = await self.page.query_selector('[class*="tab"], nav')
                if tab_area:
                    tab_text = await tab_area.inner_text()
                    # Split by common separators and filter
                    parts = re.split(r'[\n\t]+', tab_text)
                    for part in parts:
                        part = part.strip()
                        if part and len(part.split()) >= 2 and not part.lower() in ["feed", "home"]:
                            children.append(part)

            return children if children else ["Child"]

        except Exception as e:
            logger.warning(f"Could not get child tabs: {e}")
            return ["Child"]

    async def _select_child_tab(self, child_name: str) -> bool:
        """Click on a child's tab to show their feed. Returns True if clicked."""
        try:
            # Try to find and click the tab with the child's name
            tab = await self.page.query_selector(f'[role="tab"]:has-text("{child_name}")')
            if tab:
                await tab.click()
                logger.info(f"Clicked tab for {child_name}")
                await asyncio.sleep(2)  # Wait for feed to update
                return True

            # Alternative: look for any clickable element with the child's name
            tab = await self.page.query_selector(f'button:has-text("{child_name}")')
            if tab:
                await tab.click()
                logger.info(f"Clicked button for {child_name}")
                await asyncio.sleep(2)
                return True

            # Try text-based selector
            await self.page.click(f'text="{child_name}"')
            logger.info(f"Clicked text for {child_name}")
            await asyncio.sleep(2)
            return True

        except Exception as e:
            logger.warning(f"Could not select tab for {child_name}: {e}")
            return False

    async def _scroll_to_load_all_content(self, max_scrolls: int = 2) -> None:
        """Scroll down to trigger lazy loading of feed content.

        Args:
            max_scrolls: Maximum number of viewport-height scrolls (default 2 pages)
        """
        try:
            viewport_height = await self.page.evaluate("window.innerHeight")

            for i in range(max_scrolls):
                # Scroll down one viewport height
                await self.page.evaluate(f"window.scrollBy(0, {viewport_height})")
                logger.info(f"Scrolled down page {i + 1}/{max_scrolls}")

                # Wait for content to load
                await asyncio.sleep(2)

            # Scroll back to top so we capture everything from the beginning
            await self.page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1)

            logger.info("Finished scrolling to load content")

        except Exception as e:
            logger.warning(f"Error during scroll: {e}")

    async def _scrape_child_feed(self, child_name: str, date: datetime) -> ChildSummary:
        """Scrape the feed for a single child."""
        child = ChildSummary(name=child_name)
        today_str = date.strftime("%b %d, %Y")
        today_short = date.strftime("%b %d")

        # Scroll down to load all lazy-loaded content
        await self._scroll_to_load_all_content()

        # Take a debug screenshot of the feed for this child
        safe_name = child_name.replace(" ", "_").lower()
        await self.screenshot(f"feed_{safe_name}.png")

        # Get the full page text for AI parsing or fallback
        full_text = await self.page.inner_text('body')

        # Try AI parsing first if enabled
        if self.ai_parser and self.ai_config and self.ai_config.enabled:
            logger.info("Attempting AI-powered feed parsing...")
            try:
                ai_result = await self.ai_parser.parse_feed(full_text, child_name, date)
                if ai_result and (ai_result.bottles or ai_result.diapers or ai_result.naps or ai_result.fluids or ai_result.sign_in or ai_result.sign_out):
                    logger.info(f"AI parsing successful: {len(ai_result.bottles)} bottles, {len(ai_result.diapers)} diapers, {len(ai_result.naps)} naps")
                    return ai_result
                else:
                    logger.warning("AI parsing returned no events, falling back to regex")
            except Exception as e:
                logger.warning(f"AI parsing failed: {e}, falling back to regex")

        # Fallback to regex-based parsing
        logger.info("Using regex-based feed parsing...")

        # Get all feed items - look for cards that contain event data
        feed_items = await self.page.query_selector_all('[class*="MuiCard"], [class*="MuiPaper"], [class*="card"]')

        if len(feed_items) < 3:
            feed_items = await self.page.query_selector_all('div:has-text("Occurred at"), div:has-text("From Jan"), div:has-text("From Feb")')

        if len(feed_items) < 3:
            main_content = await self.page.query_selector('main')
            if main_content:
                feed_items = await main_content.query_selector_all(':scope > div > div > div')

        if len(feed_items) < 3:
            logger.info("Using full page content parsing...")
            logger.debug(f"Page content sample: {full_text[:1000]}")
            return self._parse_full_feed_text(full_text, child, date)

        logger.info(f"Found {len(feed_items)} potential feed items")

        for item in feed_items:
            try:
                text = await item.inner_text()
                if not text.strip():
                    continue

                if len(text) > 50:
                    logger.debug(f"Feed item text: {text[:100]}...")

                # Parse all feed items - extract date from content instead of filtering
                # Check for any date pattern to ensure it's an event (not navigation/header)
                if re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}", text):
                    await self._parse_feed_item(text, child, date)

            except Exception as e:
                logger.debug(f"Error parsing feed item: {e}")
                continue

        return child

    def _parse_full_feed_text(self, full_text: str, child: ChildSummary, date: datetime) -> ChildSummary:
        """Parse events from full page text when individual items can't be found."""
        today_str = date.strftime("%b %d, %Y")

        # Split by common patterns that separate feed items
        # Look for lines containing "Recorded by" which starts each item
        lines = full_text.split('\n')
        current_item = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # If we hit a new event header (Sign Out, Diaper, Bottle, etc.)
            if any(header in line for header in ['Sign Out', 'Sign In', 'Diaper', 'Bottle', 'Fluids', 'Napping']):
                # Process previous item if it exists and is from today
                if current_item:
                    item_text = '\n'.join(current_item)
                    if today_str in item_text or date.strftime("%b %d") in item_text:
                        self._parse_feed_item_sync(item_text, child, date)
                current_item = [line]
            else:
                current_item.append(line)

        # Don't forget the last item
        if current_item:
            item_text = '\n'.join(current_item)
            if today_str in item_text or date.strftime("%b %d") in item_text:
                self._parse_feed_item_sync(item_text, child, date)

        return child

    def _parse_feed_item_sync(self, text: str, child: ChildSummary, date: datetime) -> None:
        """Synchronous version of feed item parsing."""
        text_lower = text.lower()
        child_name_lower = child.name.lower()

        # Skip events that explicitly mention a DIFFERENT child's name
        name_patterns = re.findall(r'(?:Sign (?:In|Out))[^·]*·\s*([A-Z][a-z]+\s+[A-Z][a-z]+)', text)
        if name_patterns:
            for found_name in name_patterns:
                if found_name.lower() != child_name_lower:
                    logger.debug(f"Skipping event for {found_name}, not {child.name}")
                    return

        # Filter by classroom based on "Recorded by" text
        recorded_by_match = re.search(r'Recorded by\s+([^·\n]+)', text)
        if recorded_by_match:
            recorder = recorded_by_match.group(1).strip().rstrip('.')

            child_classrooms = {
                "ezra": ["Infant C"],
                "killian": ["Older P"],
            }

            first_name = child.name.split()[0].lower()
            expected_classrooms = child_classrooms.get(first_name, [])

            if expected_classrooms:
                is_classroom_event = any(classroom in recorder for classroom in expected_classrooms)
                known_classrooms = ["Infant", "Older", "Toddler", "Pre-K", "Preschool"]
                is_parent_event = not any(c in recorder for c in known_classrooms)

                if not is_classroom_event and not is_parent_event:
                    logger.debug(f"Skipping event recorded by '{recorder}', not {child.name}'s classroom")
                    return

        # Extract timestamp
        timestamp = self._extract_timestamp(text, date)

        # Check for Sign In/Out events - must match the actual event card structure:
        # "Sign Out · Name" -> "Recorded by ..." -> "Occurred at [TIMESTAMP]"
        # Requiring "Recorded by" prevents matching nav text + unrelated event timestamps
        sign_out_match = re.search(
            r"Sign\s+Out\s*·[\s\S]{1,150}?Recorded by[\s\S]{1,100}?Occurred at\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM))",
            text,
            re.IGNORECASE
        )
        sign_in_match = re.search(
            r"Sign\s+In\s*·[\s\S]{1,150}?Recorded by[\s\S]{1,100}?Occurred at\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM))",
            text,
            re.IGNORECASE
        )

        if sign_out_match:
            # Extract the timestamp specifically from the Sign Out event
            sign_out_time = self._parse_timestamp_string(sign_out_match.group(1))
            if sign_out_time and sign_out_time not in child.sign_out_events:
                child.sign_out_events.append(sign_out_time)
                logger.info(f"Parsed sign out: {sign_out_time}")

        if sign_in_match:
            # Extract the timestamp specifically from the Sign In event
            sign_in_time = self._parse_timestamp_string(sign_in_match.group(1))
            if sign_in_time and sign_in_time not in child.sign_in_events:
                child.sign_in_events.append(sign_in_time)
                logger.info(f"Parsed sign in: {sign_in_time}")

        elif "diaper" in text_lower:
            # Debug: log the raw text being parsed as diaper
            logger.info(f"DIAPER CANDIDATE - timestamp={timestamp}, text_length={len(text)}")
            logger.info(f"  TEXT START: {text[:300]}")
            logger.info(f"  TEXT END: {text[-200:]}")
            diaper = self._parse_diaper(text, timestamp)
            if diaper:
                # Deduplicate by timestamp
                existing_times = {d.time for d in child.diapers}
                if diaper.time not in existing_times:
                    child.diapers.append(diaper)
                    logger.info(f"Parsed diaper: {diaper.diaper_type} at {timestamp}")

        elif "bottle" in text_lower:
            bottle = self._parse_bottle(text, timestamp)
            if bottle:
                # Deduplicate by timestamp
                existing_times = {b.time for b in child.bottles}
                if bottle.time not in existing_times:
                    child.bottles.append(bottle)
                    logger.info(f"Parsed bottle: {bottle.ounces_consumed}oz at {timestamp}")

        elif "fluids" in text_lower:
            fluids = self._parse_fluids(text, timestamp)
            if fluids:
                # Deduplicate by timestamp
                existing_times = {f.time for f in child.fluids}
                if fluids.time not in existing_times:
                    child.fluids.append(fluids)
                    logger.info(f"Parsed fluids: {fluids.ounces}oz at {timestamp}")

        elif "napping" in text_lower or "nap" in text_lower:
            nap = self._parse_napping(text, date)
            if nap:
                # Deduplicate by start time
                existing_times = {n.start_time for n in child.naps}
                if nap.start_time not in existing_times:
                    child.naps.append(nap)
                    logger.info(f"Parsed nap: {nap.start_time} - {nap.end_time}")

        elif "eating" in text_lower:
            meal = self._parse_eating(text, timestamp)
            if meal:
                # Deduplicate by timestamp
                existing_times = {m.time for m in child.meals}
                if meal.time not in existing_times:
                    child.meals.append(meal)
                    logger.info(f"Parsed meal: {meal.meal_items[:50]}... at {timestamp}")

    async def _parse_feed_item(self, text: str, child: ChildSummary, date: datetime) -> None:
        """Parse a single feed item and add to child summary."""
        text_lower = text.lower()
        child_name_lower = child.name.lower()

        # Skip events that explicitly mention a DIFFERENT child's name
        name_patterns = re.findall(r'(?:Sign (?:In|Out))[^·]*·\s*([A-Z][a-z]+\s+[A-Z][a-z]+)', text)
        if name_patterns:
            for found_name in name_patterns:
                if found_name.lower() != child_name_lower:
                    logger.debug(f"Skipping event for {found_name}, not {child.name}")
                    return

        # Filter by classroom based on "Recorded by" text
        # Each child has a specific classroom teacher/identifier
        recorded_by_match = re.search(r'Recorded by\s+([^·\n]+)', text)
        if recorded_by_match:
            recorder = recorded_by_match.group(1).strip().rstrip('.')

            # Determine which classroom this child belongs to based on their name
            # This maps children to their classroom identifiers
            child_classrooms = {
                "ezra": ["Infant C"],
                "killian": ["Older P"],
            }

            # Get this child's expected classrooms
            first_name = child.name.split()[0].lower()
            expected_classrooms = child_classrooms.get(first_name, [])

            # If we know this child's classroom, only accept events from that classroom
            # Also allow events recorded by parents (names like "Kyle A", "Sarah A")
            if expected_classrooms:
                is_classroom_event = any(classroom in recorder for classroom in expected_classrooms)
                # Parent names are typically "FirstName LastInitial" format (e.g., "Kyle A", "Sarah A")
                # They are NOT classroom names like "Infant C" or "Older P"
                known_classrooms = ["Infant", "Older", "Toddler", "Pre-K", "Preschool"]
                is_parent_event = not any(c in recorder for c in known_classrooms)

                if not is_classroom_event and not is_parent_event:
                    # This event is from a different classroom
                    logger.debug(f"Skipping event recorded by '{recorder}', not {child.name}'s classroom")
                    return

        # Extract timestamp from text
        timestamp = self._extract_timestamp(text, date)

        # Check for Sign In/Out events - must match the actual event card structure:
        # "Sign Out · Name" -> "Recorded by ..." -> "Occurred at [TIMESTAMP]"
        # Requiring "Recorded by" prevents matching nav text + unrelated event timestamps
        sign_out_match = re.search(
            r"Sign\s+Out\s*·[\s\S]{1,150}?Recorded by[\s\S]{1,100}?Occurred at\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM))",
            text,
            re.IGNORECASE
        )
        sign_in_match = re.search(
            r"Sign\s+In\s*·[\s\S]{1,150}?Recorded by[\s\S]{1,100}?Occurred at\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM))",
            text,
            re.IGNORECASE
        )

        if sign_out_match:
            # Extract the timestamp specifically from the Sign Out event
            sign_out_time = self._parse_timestamp_string(sign_out_match.group(1))
            if sign_out_time and sign_out_time not in child.sign_out_events:
                child.sign_out_events.append(sign_out_time)
                logger.info(f"Parsed sign out: {sign_out_time}")

        if sign_in_match:
            # Extract the timestamp specifically from the Sign In event
            sign_in_time = self._parse_timestamp_string(sign_in_match.group(1))
            if sign_in_time and sign_in_time not in child.sign_in_events:
                child.sign_in_events.append(sign_in_time)
                logger.info(f"Parsed sign in: {sign_in_time}")

        elif "diaper" in text_lower:
            # Debug: log the raw text being parsed as diaper
            logger.info(f"DIAPER CANDIDATE - timestamp={timestamp}, text_length={len(text)}")
            logger.info(f"  TEXT START: {text[:300]}")
            logger.info(f"  TEXT END: {text[-200:]}")
            diaper = self._parse_diaper(text, timestamp)
            if diaper:
                # Deduplicate by timestamp
                existing_times = {d.time for d in child.diapers}
                if diaper.time not in existing_times:
                    child.diapers.append(diaper)
                    logger.info(f"Parsed diaper: {diaper.diaper_type} at {timestamp}")

        elif "bottle" in text_lower:
            bottle = self._parse_bottle(text, timestamp)
            if bottle:
                # Deduplicate by timestamp
                existing_times = {b.time for b in child.bottles}
                if bottle.time not in existing_times:
                    child.bottles.append(bottle)
                    logger.info(f"Parsed bottle: {bottle.ounces_consumed}oz {bottle.milk_type} at {timestamp}")

        elif "fluids" in text_lower:
            fluids = self._parse_fluids(text, timestamp)
            if fluids:
                # Deduplicate by timestamp
                existing_times = {f.time for f in child.fluids}
                if fluids.time not in existing_times:
                    child.fluids.append(fluids)
                    logger.info(f"Parsed fluids: {fluids.ounces}oz at {timestamp}")

        elif "nap" in text_lower:
            nap = self._parse_napping(text, date)
            if nap:
                # Deduplicate by start time
                existing_times = {n.start_time for n in child.naps}
                if nap.start_time not in existing_times:
                    child.naps.append(nap)
                    logger.info(f"Parsed nap: {nap.start_time} - {nap.end_time}")

        elif "eating" in text_lower:
            meal = self._parse_eating(text, timestamp)
            if meal:
                # Deduplicate by timestamp
                existing_times = {m.time for m in child.meals}
                if meal.time not in existing_times:
                    child.meals.append(meal)
                    logger.info(f"Parsed meal: {meal.meal_items[:50]}... at {timestamp}")

    def _parse_eating(self, text: str, timestamp: datetime) -> Optional[EatingEvent]:
        """Parse eating/meal event from text."""
        # Extract meal items from "Meal items: ..." pattern
        items_match = re.search(r"Meal items?:\s*([^\n]+)", text, re.IGNORECASE)
        meal_items = items_match.group(1).strip() if items_match else "Unknown"

        # Try to determine meal type from context or time
        meal_type = None
        hour = timestamp.hour
        if hour < 10:
            meal_type = "Breakfast"
        elif hour < 14:
            meal_type = "Lunch"
        elif hour < 17:
            meal_type = "Snack"
        else:
            meal_type = "Dinner"

        return EatingEvent(time=timestamp, meal_items=meal_items, meal_type=meal_type)

    def _parse_timestamp_string(self, ts_str: str) -> Optional[datetime]:
        """Parse a timestamp string like 'Jan 30, 2026 7:24 AM' into a datetime."""
        try:
            match = re.match(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)",
                ts_str.strip(),
                re.IGNORECASE
            )
            if not match:
                return None

            month_str = match.group(1)
            day = int(match.group(2))
            year = int(match.group(3))
            hour = int(match.group(4))
            minute = int(match.group(5))
            ampm = match.group(6).upper()

            months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                      "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
            month = months.get(month_str.lower(), 1)

            if ampm == "PM" and hour != 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0

            return datetime(year, month, day, hour, minute, 0)
        except Exception:
            return None

    def _extract_timestamp(self, text: str, date: datetime) -> datetime:
        """Extract timestamp from feed item text."""
        # Look for full date+time pattern "Jan 29, 2026 3:06 PM"
        full_match = re.search(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)",
            text,
            re.IGNORECASE
        )
        if full_match:
            month_str = full_match.group(1)
            day = int(full_match.group(2))
            year = int(full_match.group(3))
            hour = int(full_match.group(4))
            minute = int(full_match.group(5))
            ampm = full_match.group(6).upper()

            # Convert month name to number
            months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                      "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
            month = months.get(month_str.lower(), 1)

            if ampm == "PM" and hour != 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0

            return datetime(year, month, day, hour, minute, 0)

        # Look for simpler time pattern "3:06 PM" (use provided date)
        time_match = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)", text, re.IGNORECASE)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            ampm = time_match.group(3).upper()
            if ampm == "PM" and hour != 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0
            return date.replace(hour=hour, minute=minute, second=0, microsecond=0)

        return date

    def _parse_diaper(self, text: str, timestamp: datetime) -> Optional[DiaperEvent]:
        """Parse diaper event from text."""
        # Determine type: Wet, BM, or Dry
        text_lower = text.lower()
        if "bm" in text_lower or "bowel" in text_lower:
            diaper_type = "BM"
        elif "wet" in text_lower:
            diaper_type = "Wet"
        elif "dry" in text_lower:
            diaper_type = "Dry"
        else:
            diaper_type = "Unknown"

        # Extract notes (anything descriptive like "Very watery")
        notes = None
        notes_patterns = [
            r"(very\s+\w+)",
            r"notes?[:\s]+([^\n]+)",
        ]
        for pattern in notes_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                notes = match.group(1).strip()
                break

        return DiaperEvent(time=timestamp, diaper_type=diaper_type, notes=notes)

    def _parse_bottle(self, text: str, timestamp: datetime) -> Optional[BottleEvent]:
        """Parse bottle event from text."""
        # Extract milk type
        milk_type = "Unknown"
        if "breast" in text.lower():
            milk_type = "Breast milk"
        elif "formula" in text.lower():
            milk_type = "Formula"

        # Extract ounces offered - handle multi-line format:
        # "Ounces Offered"
        # "3.5"
        offered_match = re.search(r"(?:ounces\s*offered|offered)[:\s\n]*(\d+\.?\d*)", text, re.IGNORECASE)
        ounces_offered = float(offered_match.group(1)) if offered_match else 0.0

        # Extract ounces consumed - handle multi-line format:
        # "Ounces Consumed"
        # "3.6"
        consumed_match = re.search(r"(?:ounces\s*consumed|consumed)[:\s\n]*(\d+\.?\d*)", text, re.IGNORECASE)
        ounces_consumed = float(consumed_match.group(1)) if consumed_match else 0.0

        # If no specific matches, try to find any number followed by "oz"
        if ounces_offered == 0 and ounces_consumed == 0:
            oz_match = re.search(r"(\d+\.?\d*)\s*(?:oz|ounces)", text, re.IGNORECASE)
            if oz_match:
                ounces_consumed = float(oz_match.group(1))
                ounces_offered = ounces_consumed

        return BottleEvent(
            time=timestamp,
            milk_type=milk_type,
            ounces_offered=ounces_offered,
            ounces_consumed=ounces_consumed,
        )

    def _parse_fluids(self, text: str, timestamp: datetime) -> Optional[FluidsEvent]:
        """Parse fluids event from text."""
        # Extract ounces - format like "3.5 oz." or "3.5oz"
        oz_match = re.search(r"(\d+\.?\d*)\s*oz", text, re.IGNORECASE)
        ounces = float(oz_match.group(1)) if oz_match else 0.0

        # Extract meal type
        meal_type = None
        for meal in ["breakfast", "lunch", "dinner", "snack", "am snack", "pm snack"]:
            if meal in text.lower():
                meal_type = meal.title()
                break

        return FluidsEvent(time=timestamp, ounces=ounces, meal_type=meal_type)

    def _parse_napping(self, text: str, date: datetime) -> Optional[NappingEvent]:
        """Parse napping event from text."""
        # Look for "From Jan 29, 2026 1:18 PM until 1:38 PM" pattern (with end time)
        from_until_match = re.search(
            r"From\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)\s+until\s+(\d{1,2}):(\d{2})\s*(AM|PM)",
            text,
            re.IGNORECASE
        )

        if from_until_match:
            month_str = from_until_match.group(1)
            day = int(from_until_match.group(2))
            year = int(from_until_match.group(3))
            start_hour = int(from_until_match.group(4))
            start_minute = int(from_until_match.group(5))
            start_ampm = from_until_match.group(6).upper()
            end_hour = int(from_until_match.group(7))
            end_minute = int(from_until_match.group(8))
            end_ampm = from_until_match.group(9).upper()

            months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                      "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
            month = months.get(month_str.lower(), 1)

            if start_ampm == "PM" and start_hour != 12:
                start_hour += 12
            elif start_ampm == "AM" and start_hour == 12:
                start_hour = 0

            if end_ampm == "PM" and end_hour != 12:
                end_hour += 12
            elif end_ampm == "AM" and end_hour == 12:
                end_hour = 0

            start_time = datetime(year, month, day, start_hour, start_minute, 0)
            end_time = datetime(year, month, day, end_hour, end_minute, 0)

            position = None
            for pos in ["back", "side", "stomach", "tummy"]:
                if pos in text.lower():
                    position = pos.title()
                    break

            return NappingEvent(start_time=start_time, end_time=end_time, position=position)

        # Also handle "Occurred at" format (nap without end time - just start time logged)
        # Example: "Occurred at Jan 29, 2026 1:10 PM · Back"
        occurred_match = re.search(
            r"Occurred at\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)",
            text,
            re.IGNORECASE
        )

        if occurred_match:
            month_str = occurred_match.group(1)
            day = int(occurred_match.group(2))
            year = int(occurred_match.group(3))
            start_hour = int(occurred_match.group(4))
            start_minute = int(occurred_match.group(5))
            start_ampm = occurred_match.group(6).upper()

            months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                      "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
            month = months.get(month_str.lower(), 1)

            if start_ampm == "PM" and start_hour != 12:
                start_hour += 12
            elif start_ampm == "AM" and start_hour == 12:
                start_hour = 0

            start_time = datetime(year, month, day, start_hour, start_minute, 0)

            position = None
            for pos in ["back", "side", "stomach", "tummy"]:
                if pos in text.lower():
                    position = pos.title()
                    break

            return NappingEvent(start_time=start_time, end_time=None, position=position)

        return None

    async def screenshot(self, path: str = "debug_screenshot.png") -> None:
        """Take a screenshot for debugging."""
        if self.page:
            full_path = SESSION_DIR / path
            await self.page.screenshot(path=str(full_path))
            logger.info(f"Screenshot saved to {full_path}")
