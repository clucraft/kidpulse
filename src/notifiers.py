"""Notification handlers for KidPulse."""

import logging
from abc import ABC, abstractmethod
from typing import Optional

import httpx
from telegram import Bot
from telegram.constants import ParseMode

from .config import NtfyConfig, TelegramConfig
from .models import DailySummary, EventType

logger = logging.getLogger(__name__)


class Notifier(ABC):
    """Base class for notifiers."""

    @abstractmethod
    async def send(self, summary: DailySummary) -> bool:
        """Send a notification. Returns True if successful."""
        pass

    @abstractmethod
    async def send_raw(self, message: str, title: Optional[str] = None) -> bool:
        """Send a raw message. Returns True if successful."""
        pass


class NtfyNotifier(Notifier):
    """NTFY notification handler."""

    def __init__(self, config: NtfyConfig):
        self.config = config

    async def send(self, summary: DailySummary) -> bool:
        """Send daily summary via NTFY."""
        message = self._format_summary(summary)
        title = f"KidPulse Daily Summary - {summary.date.strftime('%b %d')}"
        return await self.send_raw(message, title)

    async def send_raw(self, message: str, title: Optional[str] = None) -> bool:
        """Send a raw message via NTFY."""
        try:
            headers = {}
            if title:
                headers["Title"] = title
            headers["Tags"] = "baby,school"

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.config.url,
                    content=message,
                    headers=headers,
                )
                response.raise_for_status()
                logger.info("NTFY notification sent successfully")
                return True

        except Exception as e:
            logger.error(f"Failed to send NTFY notification: {e}")
            return False

    def _format_summary(self, summary: DailySummary) -> str:
        """Format summary for NTFY (plain text)."""
        lines = []
        date_str = summary.date.strftime("%A, %B %d")
        lines.append(f"Daily Summary for {date_str}")
        lines.append(f"Total Events: {summary.event_count}")
        lines.append("")

        if summary.child_names:
            lines.append(f"Children: {', '.join(sorted(summary.child_names))}")
            lines.append("")

        # Group by event type
        type_counts = {}
        for event in summary.events:
            type_name = event.event_type.value.replace("_", " ").title()
            type_counts[type_name] = type_counts.get(type_name, 0) + 1

        if type_counts:
            lines.append("Activity Breakdown:")
            for event_type, count in sorted(type_counts.items()):
                lines.append(f"  - {event_type}: {count}")
            lines.append("")

        # List events chronologically
        lines.append("Timeline:")
        for event in sorted(summary.events, key=lambda e: e.timestamp):
            lines.append(f"  {event}")

        return "\n".join(lines)


class TelegramNotifier(Notifier):
    """Telegram notification handler."""

    def __init__(self, config: TelegramConfig):
        self.config = config
        self.bot = Bot(token=config.bot_token) if config.bot_token else None

    async def send(self, summary: DailySummary) -> bool:
        """Send daily summary via Telegram."""
        message = self._format_summary(summary)
        return await self.send_raw(message)

    async def send_raw(self, message: str, title: Optional[str] = None) -> bool:
        """Send a raw message via Telegram."""
        if not self.bot:
            logger.error("Telegram bot not configured")
            return False

        try:
            if title:
                message = f"*{title}*\n\n{message}"

            await self.bot.send_message(
                chat_id=self.config.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info("Telegram notification sent successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False

    def _format_summary(self, summary: DailySummary) -> str:
        """Format summary for Telegram (Markdown)."""
        lines = []
        date_str = summary.date.strftime("%A, %B %d")
        lines.append(f"*KidPulse Daily Summary*")
        lines.append(f"_{date_str}_")
        lines.append("")

        if summary.child_names:
            children = ", ".join(sorted(summary.child_names))
            lines.append(f"*Children:* {children}")
            lines.append("")

        # Activity breakdown with emojis
        emoji_map = {
            EventType.CHECKIN: ("Check In", "\u2705"),
            EventType.CHECKOUT: ("Check Out", "\U0001F44B"),
            EventType.MEAL: ("Meals", "\U0001F37D\uFE0F"),
            EventType.NAP_START: ("Nap Start", "\U0001F634"),
            EventType.NAP_END: ("Nap End", "\u2600\uFE0F"),
            EventType.DIAPER: ("Diaper", "\U0001F476"),
            EventType.POTTY: ("Potty", "\U0001F6BD"),
            EventType.PHOTO: ("Photos", "\U0001F4F8"),
            EventType.VIDEO: ("Videos", "\U0001F3AC"),
            EventType.ACTIVITY: ("Activities", "\U0001F3A8"),
            EventType.INCIDENT: ("Incidents", "\u26A0\uFE0F"),
            EventType.NOTE: ("Notes", "\U0001F4DD"),
        }

        type_counts = {}
        for event in summary.events:
            type_counts[event.event_type] = type_counts.get(event.event_type, 0) + 1

        if type_counts:
            lines.append("*Activity Summary:*")
            for event_type, count in sorted(type_counts.items(), key=lambda x: x[0].value):
                if event_type in emoji_map:
                    name, emoji = emoji_map[event_type]
                    lines.append(f"  {emoji} {name}: {count}")
                else:
                    lines.append(f"  - {event_type.value}: {count}")
            lines.append("")

        # Timeline
        lines.append("*Timeline:*")
        for event in sorted(summary.events, key=lambda e: e.timestamp)[:20]:  # Limit to 20 events
            time_str = event.timestamp.strftime("%I:%M %p")
            desc = event.description[:50] + "..." if len(event.description) > 50 else event.description
            if event.child_name:
                lines.append(f"`{time_str}` *{event.child_name}*: {desc}")
            else:
                lines.append(f"`{time_str}` {desc}")

        if summary.event_count > 20:
            lines.append(f"\n_...and {summary.event_count - 20} more events_")

        return "\n".join(lines)


class NotificationManager:
    """Manages multiple notification channels."""

    def __init__(self, ntfy: Optional[NtfyNotifier] = None, telegram: Optional[TelegramNotifier] = None):
        self.notifiers: list[Notifier] = []
        if ntfy:
            self.notifiers.append(ntfy)
        if telegram:
            self.notifiers.append(telegram)

    async def send_summary(self, summary: DailySummary) -> dict[str, bool]:
        """Send summary to all configured notifiers."""
        results = {}
        for notifier in self.notifiers:
            name = notifier.__class__.__name__
            results[name] = await notifier.send(summary)
        return results

    async def send_raw(self, message: str, title: Optional[str] = None) -> dict[str, bool]:
        """Send raw message to all configured notifiers."""
        results = {}
        for notifier in self.notifiers:
            name = notifier.__class__.__name__
            results[name] = await notifier.send_raw(message, title)
        return results
