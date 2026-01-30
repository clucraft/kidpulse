"""Notification handlers for KidPulse."""

import logging
from abc import ABC, abstractmethod
from typing import Optional

import httpx
from telegram import Bot
from telegram.constants import ParseMode

from .config import NtfyConfig, TelegramConfig
from .models import DailySummary, ChildSummary

logger = logging.getLogger(__name__)


class Notifier(ABC):
    """Base class for notifiers."""

    @abstractmethod
    async def send(self, summary: DailySummary, magic_link: Optional[str] = None) -> bool:
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

    async def send(self, summary: DailySummary, magic_link: Optional[str] = None) -> bool:
        """Send daily summary via NTFY."""
        message = self._format_summary(summary, magic_link)
        title = f"KidPulse - {summary.date.strftime('%b %d')}"
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

    def _format_summary(self, summary: DailySummary, magic_link: Optional[str] = None) -> str:
        """Format summary for NTFY (plain text)."""
        lines = []
        date_str = summary.date.strftime("%A, %B %d")
        lines.append(f"Daily Summary for {date_str}")
        lines.append("")

        for child_name, child in summary.children.items():
            lines.append(f"=== {child_name} ===")
            lines.append("")
            lines.extend(self._format_child_summary(child))
            lines.append("")

        if magic_link:
            lines.append("---")
            lines.append(f"View Dashboard: {magic_link}")

        return "\n".join(lines)

    def _format_child_summary(self, child: ChildSummary) -> list[str]:
        """Format a single child's summary."""
        lines = []

        # Attendance
        if child.sign_in:
            lines.append(f"Arrived: {child.sign_in.strftime('%I:%M %p')}")
        if child.sign_out:
            lines.append(f"Left: {child.sign_out.strftime('%I:%M %p')}")
        if child.sign_in or child.sign_out:
            lines.append("")

        # Bottles
        if child.bottles:
            lines.append(f"Bottles ({len(child.bottles)}):")
            for b in sorted(child.bottles, key=lambda x: x.time):
                lines.append(f"  {b.time.strftime('%I:%M %p')} - {b.milk_type}: {b.ounces_consumed}oz consumed")
            lines.append(f"  Total: {child.total_bottle_consumed}oz")
            lines.append("")

        # Fluids
        if child.fluids:
            lines.append(f"Fluids ({len(child.fluids)}):")
            for f in sorted(child.fluids, key=lambda x: x.time):
                meal = f" ({f.meal_type})" if f.meal_type else ""
                lines.append(f"  {f.time.strftime('%I:%M %p')} - {f.ounces}oz{meal}")
            lines.append(f"  Total: {child.total_fluids}oz")
            lines.append("")

        # Diapers
        if child.diapers:
            lines.append(f"Diapers ({len(child.diapers)}):")
            for d in sorted(child.diapers, key=lambda x: x.time):
                notes = f" - {d.notes}" if d.notes else ""
                lines.append(f"  {d.time.strftime('%I:%M %p')} - {d.diaper_type}{notes}")
            lines.append(f"  Summary: {child.wet_diapers} wet, {child.bm_diapers} BM")
            lines.append("")

        # Naps
        if child.naps:
            lines.append(f"Naps ({len(child.naps)}):")
            for n in sorted(child.naps, key=lambda x: x.start_time):
                end_str = n.end_time.strftime('%I:%M %p') if n.end_time else "ongoing"
                duration = f" ({n.duration_minutes} min)" if n.duration_minutes else ""
                position = f" - {n.position}" if n.position else ""
                lines.append(f"  {n.start_time.strftime('%I:%M %p')} - {end_str}{duration}{position}")
            lines.append(f"  Total: {child.total_nap_minutes} minutes")

        return lines


class TelegramNotifier(Notifier):
    """Telegram notification handler."""

    def __init__(self, config: TelegramConfig):
        self.config = config
        self.bot = Bot(token=config.bot_token) if config.bot_token else None

    async def send(self, summary: DailySummary, magic_link: Optional[str] = None) -> bool:
        """Send daily summary via Telegram."""
        message = self._format_summary(summary, magic_link)
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

    def _format_summary(self, summary: DailySummary, magic_link: Optional[str] = None) -> str:
        """Format summary for Telegram (Markdown)."""
        lines = []
        date_str = summary.date.strftime("%A, %B %d")
        lines.append(f"*KidPulse Daily Summary*")
        lines.append(f"_{date_str}_")
        lines.append("")

        for child_name, child in summary.children.items():
            lines.append(f"*{child_name}*")
            lines.append("")
            lines.extend(self._format_child_summary(child))
            lines.append("")

        if magic_link:
            lines.append("")
            lines.append(f"[View Dashboard]({magic_link})")

        return "\n".join(lines)

    def _format_child_summary(self, child: ChildSummary) -> list[str]:
        """Format a single child's summary with emojis."""
        lines = []

        # Attendance
        if child.sign_in or child.sign_out:
            attendance = []
            if child.sign_in:
                attendance.append(f"In: {child.sign_in.strftime('%I:%M %p')}")
            if child.sign_out:
                attendance.append(f"Out: {child.sign_out.strftime('%I:%M %p')}")
            lines.append(f"\U0001F3EB " + " | ".join(attendance))
            lines.append("")

        # Bottles summary
        if child.bottles:
            lines.append(f"\U0001F37C *Bottles* ({len(child.bottles)})")
            for b in sorted(child.bottles, key=lambda x: x.time):
                lines.append(f"  `{b.time.strftime('%I:%M %p')}` {b.ounces_consumed}oz {b.milk_type}")
            lines.append(f"  *Total: {child.total_bottle_consumed}oz*")
            lines.append("")

        # Fluids summary
        if child.fluids:
            lines.append(f"\U0001F964 *Fluids* ({len(child.fluids)})")
            for f in sorted(child.fluids, key=lambda x: x.time):
                meal = f" _{f.meal_type}_" if f.meal_type else ""
                lines.append(f"  `{f.time.strftime('%I:%M %p')}` {f.ounces}oz{meal}")
            lines.append(f"  *Total: {child.total_fluids}oz*")
            lines.append("")

        # Diapers summary
        if child.diapers:
            lines.append(f"\U0001F476 *Diapers* ({len(child.diapers)})")
            for d in sorted(child.diapers, key=lambda x: x.time):
                emoji = "\U0001F4A7" if d.diaper_type == "Wet" else "\U0001F4A9" if d.diaper_type == "BM" else "\u2B55"
                notes = f" _{d.notes}_" if d.notes else ""
                lines.append(f"  `{d.time.strftime('%I:%M %p')}` {emoji} {d.diaper_type}{notes}")
            lines.append(f"  *Summary: {child.wet_diapers} wet, {child.bm_diapers} BM*")
            lines.append("")

        # Naps summary
        if child.naps:
            lines.append(f"\U0001F634 *Naps* ({len(child.naps)})")
            for n in sorted(child.naps, key=lambda x: x.start_time):
                end_str = n.end_time.strftime('%I:%M %p') if n.end_time else "ongoing"
                duration = f" ({n.duration_minutes}min)" if n.duration_minutes else ""
                position = f" _{n.position}_" if n.position else ""
                lines.append(f"  `{n.start_time.strftime('%I:%M %p')}-{end_str}`{duration}{position}")
            if child.total_nap_minutes:
                hours = child.total_nap_minutes // 60
                mins = child.total_nap_minutes % 60
                if hours:
                    lines.append(f"  *Total: {hours}h {mins}m*")
                else:
                    lines.append(f"  *Total: {mins} minutes*")

        return lines


class NotificationManager:
    """Manages multiple notification channels."""

    def __init__(self, ntfy: Optional[NtfyNotifier] = None, telegram: Optional[TelegramNotifier] = None):
        self.notifiers: list[Notifier] = []
        if ntfy:
            self.notifiers.append(ntfy)
        if telegram:
            self.notifiers.append(telegram)

    async def send_summary(self, summary: DailySummary, magic_link: Optional[str] = None) -> dict[str, bool]:
        """Send summary to all configured notifiers."""
        results = {}
        for notifier in self.notifiers:
            name = notifier.__class__.__name__
            results[name] = await notifier.send(summary, magic_link=magic_link)
        return results

    async def send_raw(self, message: str, title: Optional[str] = None) -> dict[str, bool]:
        """Send raw message to all configured notifiers."""
        results = {}
        for notifier in self.notifiers:
            name = notifier.__class__.__name__
            results[name] = await notifier.send_raw(message, title)
        return results
