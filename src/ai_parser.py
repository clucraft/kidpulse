"""AI-powered feed parsing using Ollama or OpenAI."""

import json
import logging
import re
from datetime import datetime
from typing import Optional

import httpx

from .config import AIConfig
from .models import (
    ChildSummary,
    DiaperEvent,
    BottleEvent,
    FluidsEvent,
    NappingEvent,
)

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Extract all childcare events from this feed text. Return ONLY valid JSON, no other text.

The JSON should have this structure:
{
  "sign_in": "HH:MM AM/PM" or null,
  "sign_out": "HH:MM AM/PM" or null,
  "bottles": [
    {"time": "HH:MM AM/PM", "milk_type": "Breast milk" or "Formula", "offered": 0.0, "consumed": 0.0}
  ],
  "diapers": [
    {"time": "HH:MM AM/PM", "type": "Wet" or "BM" or "Dry", "notes": "optional notes"}
  ],
  "fluids": [
    {"time": "HH:MM AM/PM", "ounces": 0.0, "meal": "Lunch" or null}
  ],
  "naps": [
    {"start": "HH:MM AM/PM", "end": "HH:MM AM/PM", "position": "Back" or null}
  ]
}

Only include events from today's date. Extract times in 12-hour format with AM/PM.

Feed text:
{feed_text}

/no_think"""


class AIParser:
    """Parse feed content using AI."""

    def __init__(self, config: AIConfig):
        self.config = config

    async def parse_feed(self, feed_text: str, child_name: str, date: datetime) -> Optional[ChildSummary]:
        """Parse feed text using AI and return structured data."""
        if not self.config.enabled:
            return None

        try:
            if self.config.provider == "ollama":
                return await self._parse_with_ollama(feed_text, child_name, date)
            elif self.config.provider == "openai":
                return await self._parse_with_openai(feed_text, child_name, date)
            else:
                logger.error(f"Unknown AI provider: {self.config.provider}")
                return None
        except Exception as e:
            logger.error(f"AI parsing failed: {e}")
            return None

    async def _parse_with_ollama(self, feed_text: str, child_name: str, date: datetime) -> Optional[ChildSummary]:
        """Parse using local Ollama."""
        prompt = EXTRACTION_PROMPT.format(feed_text=feed_text)

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.config.ollama_url}/api/generate",
                json={
                    "model": self.config.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # Low temperature for consistent output
                    },
                },
            )
            response.raise_for_status()
            result = response.json()
            ai_response = result.get("response", "")

        return self._parse_ai_response(ai_response, child_name, date)

    async def _parse_with_openai(self, feed_text: str, child_name: str, date: datetime) -> Optional[ChildSummary]:
        """Parse using OpenAI API."""
        if not self.config.openai_api_key:
            logger.error("OpenAI API key not configured")
            return None

        prompt = EXTRACTION_PROMPT.format(feed_text=feed_text).replace("/no_think", "")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.config.openai_model,
                    "messages": [
                        {"role": "system", "content": "You extract structured data from text. Always respond with valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            result = response.json()
            ai_response = result["choices"][0]["message"]["content"]

        return self._parse_ai_response(ai_response, child_name, date)

    def _parse_ai_response(self, ai_response: str, child_name: str, date: datetime) -> Optional[ChildSummary]:
        """Parse the AI response JSON into a ChildSummary."""
        # Extract JSON from response (in case there's extra text)
        json_match = re.search(r'\{[\s\S]*\}', ai_response)
        if not json_match:
            logger.error(f"No JSON found in AI response: {ai_response[:200]}")
            return None

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI JSON: {e}\nResponse: {ai_response[:500]}")
            return None

        child = ChildSummary(name=child_name)

        # Parse sign in/out
        if data.get("sign_in"):
            child.sign_in = self._parse_time(data["sign_in"], date)
            logger.info(f"AI parsed sign in: {child.sign_in}")

        if data.get("sign_out"):
            child.sign_out = self._parse_time(data["sign_out"], date)
            logger.info(f"AI parsed sign out: {child.sign_out}")

        # Parse bottles
        for bottle in data.get("bottles", []):
            try:
                event = BottleEvent(
                    time=self._parse_time(bottle.get("time", ""), date),
                    milk_type=bottle.get("milk_type", "Unknown"),
                    ounces_offered=float(bottle.get("offered", 0)),
                    ounces_consumed=float(bottle.get("consumed", 0)),
                )
                child.bottles.append(event)
                logger.info(f"AI parsed bottle: {event.ounces_consumed}oz {event.milk_type}")
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse bottle: {e}")

        # Parse diapers
        for diaper in data.get("diapers", []):
            try:
                event = DiaperEvent(
                    time=self._parse_time(diaper.get("time", ""), date),
                    diaper_type=diaper.get("type", "Unknown"),
                    notes=diaper.get("notes"),
                )
                child.diapers.append(event)
                logger.info(f"AI parsed diaper: {event.diaper_type}")
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse diaper: {e}")

        # Parse fluids
        for fluid in data.get("fluids", []):
            try:
                event = FluidsEvent(
                    time=self._parse_time(fluid.get("time", ""), date),
                    ounces=float(fluid.get("ounces", 0)),
                    meal_type=fluid.get("meal"),
                )
                child.fluids.append(event)
                logger.info(f"AI parsed fluids: {event.ounces}oz")
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse fluids: {e}")

        # Parse naps
        for nap in data.get("naps", []):
            try:
                event = NappingEvent(
                    start_time=self._parse_time(nap.get("start", ""), date),
                    end_time=self._parse_time(nap.get("end", ""), date) if nap.get("end") else None,
                    position=nap.get("position"),
                )
                child.naps.append(event)
                logger.info(f"AI parsed nap: {event.start_time} - {event.end_time}")
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse nap: {e}")

        return child

    def _parse_time(self, time_str: str, date: datetime) -> datetime:
        """Parse a time string like '3:06 PM' into a datetime."""
        if not time_str:
            return date

        # Try common formats
        for fmt in ["%I:%M %p", "%I:%M%p", "%H:%M"]:
            try:
                parsed = datetime.strptime(time_str.strip(), fmt)
                return date.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
            except ValueError:
                continue

        # Try extracting with regex
        match = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", time_str, re.IGNORECASE)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            ampm = match.group(3)
            if ampm:
                if ampm.upper() == "PM" and hour != 12:
                    hour += 12
                elif ampm.upper() == "AM" and hour == 12:
                    hour = 0
            return date.replace(hour=hour, minute=minute, second=0, microsecond=0)

        return date
