"""Data models for KidPulse events."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class EventType(Enum):
    """Types of events from Playground."""
    CHECKIN = "check_in"
    CHECKOUT = "check_out"
    MEAL = "meal"
    NAP_START = "nap_start"
    NAP_END = "nap_end"
    DIAPER = "diaper"
    POTTY = "potty"
    ACTIVITY = "activity"
    PHOTO = "photo"
    VIDEO = "video"
    NOTE = "note"
    INCIDENT = "incident"
    MEDICATION = "medication"
    ANNOUNCEMENT = "announcement"
    UNKNOWN = "unknown"


@dataclass
class Event:
    """A single event from Playground."""
    event_type: EventType
    timestamp: datetime
    description: str
    child_name: Optional[str] = None
    details: Optional[str] = None
    media_url: Optional[str] = None
    raw_data: Optional[dict] = None

    def __str__(self) -> str:
        time_str = self.timestamp.strftime("%I:%M %p")
        if self.child_name:
            return f"[{time_str}] {self.child_name}: {self.description}"
        return f"[{time_str}] {self.description}"


@dataclass
class DailySummary:
    """Summary of all events for a day."""
    date: datetime
    events: list[Event] = field(default_factory=list)
    child_names: set[str] = field(default_factory=set)

    def add_event(self, event: Event) -> None:
        """Add an event to the summary."""
        self.events.append(event)
        if event.child_name:
            self.child_names.add(event.child_name)

    @property
    def event_count(self) -> int:
        return len(self.events)

    def events_by_type(self, event_type: EventType) -> list[Event]:
        """Get all events of a specific type."""
        return [e for e in self.events if e.event_type == event_type]

    def events_by_child(self, child_name: str) -> list[Event]:
        """Get all events for a specific child."""
        return [e for e in self.events if e.child_name == child_name]

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "date": self.date.isoformat(),
            "event_count": self.event_count,
            "children": list(self.child_names),
            "events": [
                {
                    "type": e.event_type.value,
                    "time": e.timestamp.isoformat(),
                    "description": e.description,
                    "child": e.child_name,
                    "details": e.details,
                }
                for e in self.events
            ],
        }
