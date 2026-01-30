"""Data models for KidPulse events."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


class EventType(Enum):
    """Types of events from Playground."""
    SIGN_IN = "sign_in"
    SIGN_OUT = "sign_out"
    BOTTLE = "bottle"
    FLUIDS = "fluids"
    DIAPER = "diaper"
    NAPPING = "napping"
    MEAL = "meal"
    ACTIVITY = "activity"
    PHOTO = "photo"
    NOTE = "note"
    INCIDENT = "incident"
    UNKNOWN = "unknown"


@dataclass
class DiaperEvent:
    """Diaper change event details."""
    time: datetime
    diaper_type: str  # "Wet", "BM", "Dry"
    notes: Optional[str] = None


@dataclass
class BottleEvent:
    """Bottle feeding event details."""
    time: datetime
    milk_type: str  # "Breast milk", "Formula", etc.
    ounces_offered: float
    ounces_consumed: float


@dataclass
class FluidsEvent:
    """Fluids event details."""
    time: datetime
    ounces: float
    meal_type: Optional[str] = None  # "Lunch", "Snack", etc.


@dataclass
class NappingEvent:
    """Napping event details."""
    start_time: datetime
    end_time: Optional[datetime] = None
    position: Optional[str] = None  # "Back", "Side", etc.

    @property
    def duration_minutes(self) -> Optional[int]:
        if self.end_time:
            delta = self.end_time - self.start_time
            return int(delta.total_seconds() / 60)
        return None


@dataclass
class EatingEvent:
    """Eating/meal event details."""
    time: datetime
    meal_items: str
    meal_type: Optional[str] = None  # "Breakfast", "Lunch", "Snack", etc.


@dataclass
class SignEvent:
    """Sign in/out event details."""
    time: datetime
    event_type: str  # "in" or "out"
    recorded_by: Optional[str] = None


@dataclass
class Event:
    """A single event from Playground."""
    event_type: EventType
    timestamp: datetime
    child_name: str
    description: str
    recorded_by: Optional[str] = None
    details: Optional[dict] = None  # Type-specific details

    def __str__(self) -> str:
        time_str = self.timestamp.strftime("%I:%M %p")
        return f"[{time_str}] {self.child_name}: {self.description}"


@dataclass
class ChildSummary:
    """Summary of events for a single child."""
    name: str
    sign_in: Optional[datetime] = None
    sign_out: Optional[datetime] = None
    # Lists to track ALL sign events (for multi-day feeds)
    sign_in_events: list[datetime] = field(default_factory=list)
    sign_out_events: list[datetime] = field(default_factory=list)
    diapers: list[DiaperEvent] = field(default_factory=list)
    bottles: list[BottleEvent] = field(default_factory=list)
    fluids: list[FluidsEvent] = field(default_factory=list)
    naps: list[NappingEvent] = field(default_factory=list)
    meals: list["EatingEvent"] = field(default_factory=list)
    other_events: list[Event] = field(default_factory=list)

    @property
    def total_bottle_consumed(self) -> float:
        return sum(b.ounces_consumed for b in self.bottles)

    @property
    def total_fluids(self) -> float:
        return sum(f.ounces for f in self.fluids)

    @property
    def total_nap_minutes(self) -> int:
        return sum(n.duration_minutes or 0 for n in self.naps)

    @property
    def wet_diapers(self) -> int:
        return sum(1 for d in self.diapers if d.diaper_type.lower() == "wet")

    @property
    def bm_diapers(self) -> int:
        return sum(1 for d in self.diapers if d.diaper_type.lower() == "bm")


@dataclass
class DailySummary:
    """Summary of all events for a day."""
    date: datetime
    children: dict[str, ChildSummary] = field(default_factory=dict)

    def get_or_create_child(self, name: str) -> ChildSummary:
        """Get or create a child summary."""
        if name not in self.children:
            self.children[name] = ChildSummary(name=name)
        return self.children[name]

    @property
    def child_names(self) -> list[str]:
        return list(self.children.keys())

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "date": self.date.isoformat(),
            "children": {
                name: {
                    "sign_in": child.sign_in.isoformat() if child.sign_in else None,
                    "sign_out": child.sign_out.isoformat() if child.sign_out else None,
                    "bottles": [
                        {
                            "time": b.time.isoformat(),
                            "milk_type": b.milk_type,
                            "offered": b.ounces_offered,
                            "consumed": b.ounces_consumed,
                        }
                        for b in child.bottles
                    ],
                    "fluids": [
                        {
                            "time": f.time.isoformat(),
                            "ounces": f.ounces,
                            "meal": f.meal_type,
                        }
                        for f in child.fluids
                    ],
                    "diapers": [
                        {
                            "time": d.time.isoformat(),
                            "type": d.diaper_type,
                            "notes": d.notes,
                        }
                        for d in child.diapers
                    ],
                    "naps": [
                        {
                            "start": n.start_time.isoformat(),
                            "end": n.end_time.isoformat() if n.end_time else None,
                            "duration_minutes": n.duration_minutes,
                            "position": n.position,
                        }
                        for n in child.naps
                    ],
                    "meals": [
                        {
                            "time": m.time.isoformat(),
                            "items": m.meal_items,
                            "type": m.meal_type,
                        }
                        for m in child.meals
                    ],
                    "totals": {
                        "bottle_oz": child.total_bottle_consumed,
                        "fluids_oz": child.total_fluids,
                        "nap_minutes": child.total_nap_minutes,
                        "wet_diapers": child.wet_diapers,
                        "bm_diapers": child.bm_diapers,
                        "meals_count": len(child.meals),
                    },
                }
                for name, child in self.children.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DailySummary":
        """Reconstruct DailySummary from dictionary."""
        date_val = datetime.fromisoformat(data["date"]) if isinstance(data["date"], str) else data["date"]
        summary = cls(date=date_val)

        for name, child_data in data.get("children", {}).items():
            child = ChildSummary(name=name)

            if child_data.get("sign_in"):
                child.sign_in = datetime.fromisoformat(child_data["sign_in"])
            if child_data.get("sign_out"):
                child.sign_out = datetime.fromisoformat(child_data["sign_out"])

            for b in child_data.get("bottles", []):
                child.bottles.append(BottleEvent(
                    time=datetime.fromisoformat(b["time"]),
                    milk_type=b.get("milk_type", "Unknown"),
                    ounces_offered=b.get("offered", 0),
                    ounces_consumed=b.get("consumed", 0),
                ))

            for f in child_data.get("fluids", []):
                child.fluids.append(FluidsEvent(
                    time=datetime.fromisoformat(f["time"]),
                    ounces=f.get("ounces", 0),
                    meal_type=f.get("meal"),
                ))

            for d in child_data.get("diapers", []):
                child.diapers.append(DiaperEvent(
                    time=datetime.fromisoformat(d["time"]),
                    diaper_type=d.get("type", "Unknown"),
                    notes=d.get("notes"),
                ))

            for n in child_data.get("naps", []):
                child.naps.append(NappingEvent(
                    start_time=datetime.fromisoformat(n["start"]),
                    end_time=datetime.fromisoformat(n["end"]) if n.get("end") else None,
                    position=n.get("position"),
                ))

            for m in child_data.get("meals", []):
                child.meals.append(EatingEvent(
                    time=datetime.fromisoformat(m["time"]),
                    meal_items=m.get("items", ""),
                    meal_type=m.get("type"),
                ))

            summary.children[name] = child

        return summary
