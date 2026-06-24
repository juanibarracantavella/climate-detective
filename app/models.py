from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Period:
    name: str
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class Sample:
    timestamp: datetime
    value: float


@dataclass(frozen=True, slots=True)
class Event:
    kind: str
    start: datetime
    end: datetime
    change: float
    unit: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "change": round(self.change, 2),
            "unit": self.unit,
        }


@dataclass(slots=True)
class AnalysisResult:
    statistics: dict[str, float | int | None]
    events: list[Event]
    warnings: list[str] = field(default_factory=list)

    def facts(self) -> dict[str, Any]:
        return {
            "statistics": self.statistics,
            "events": [event.as_dict() for event in self.events],
            "warnings": self.warnings,
        }
