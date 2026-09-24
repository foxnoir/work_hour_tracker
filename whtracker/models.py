"""Gespeicherte Tage, Pausen und Parse-Ergebnisse."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time

from .format import format_time, pause_full_minutes, round_to_quarter_hours

class ParseError(ValueError):
    """Ungültige manuelle Datums- oder Zeitangabe."""


@dataclass
class ManualEntry:
    day: date
    hours: float | None = None
    start: datetime | None = None
    end: datetime | None = None


@dataclass
class EditEntry:
    day: date
    hours: float | None = None
    end: time | None = None
    pause_minutes: int | None = None
    pause_end: time | None = None


@dataclass
class AddPauseEntry:
    minutes: int
    day: date | None = None


@dataclass
class AbsenceEntry:
    kind: str
    days: float | None = None
    start: date | None = None
    end: date | None = None
    year: int | None = None
    month: int | None = None
    remove: bool = False


@dataclass
class HoursQuery:
    kind: str
    year: int | None = None
    month: int | None = None


@dataclass
class Pause:
    start: str
    end: str | None = None

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, data: dict) -> Pause:
        return cls(start=data["start"], end=data.get("end"))

    @property
    def start_dt(self) -> datetime:
        return datetime.fromisoformat(self.start)

    def minutes(self) -> int:
        if self.end is None:
            return 0
        return pause_full_minutes(
            self.start_dt,
            datetime.fromisoformat(self.end),
        )

    def elapsed_minutes(self, at: datetime) -> int:
        end = datetime.fromisoformat(self.end) if self.end else at
        return pause_full_minutes(self.start_dt, end)

    def range_label(self) -> str:
        start = format_time(self.start)
        if self.end is None:
            return start
        return f"{start}–{format_time(self.end)}"


@dataclass
class WorkDay:
    date: str
    work_start: str | None = None
    work_end: str | None = None
    pauses: list[Pause] = field(default_factory=list)
    manual_hours: float | None = None
    extra_pause_minutes: int = 0

    def to_dict(self) -> dict:
        data = {
            "date": self.date,
            "work_start": self.work_start,
            "work_end": self.work_end,
            "pauses": [pause.to_dict() for pause in self.pauses],
        }
        if self.manual_hours is not None:
            data["manual_hours"] = self.manual_hours
        if self.extra_pause_minutes:
            data["extra_pause_minutes"] = self.extra_pause_minutes
        return data

    @classmethod
    def from_dict(cls, data: dict) -> WorkDay:
        return cls(
            date=data["date"],
            work_start=data.get("work_start"),
            work_end=data.get("work_end"),
            pauses=[Pause.from_dict(item) for item in data.get("pauses", [])],
            manual_hours=data.get("manual_hours"),
            extra_pause_minutes=int(data.get("extra_pause_minutes") or 0),
        )

    def open_pause(self) -> Pause | None:
        for pause in self.pauses:
            if pause.end is None:
                return pause
        return None

    def total_pause_minutes(self) -> int:
        return sum(pause.minutes() for pause in self.pauses) + self.extra_pause_minutes

    def work_minutes(self) -> float:
        if self.work_start is None or self.work_end is None:
            if self.manual_hours is not None:
                return max(0.0, float(self.manual_hours) * 60.0 - self.extra_pause_minutes)
            return 0.0
        start = datetime.fromisoformat(self.work_start)
        end = datetime.fromisoformat(self.work_end)
        raw_minutes = (end - start).total_seconds() / 60.0
        return max(0.0, raw_minutes - self.total_pause_minutes())

    def rounded_hours(self) -> float:
        extra = float(self.manual_hours) if self.manual_hours is not None else 0.0
        if self.work_start is None or self.work_end is None:
            return round_to_quarter_hours(
                max(0.0, extra * 60.0 - self.extra_pause_minutes)
            )
        session = self.work_minutes()
        return round_to_quarter_hours(session + extra * 60.0)

    def hours_at(self, at: datetime | None = None) -> float:
        if self.work_end is not None or self.work_start is None:
            return self.rounded_hours()
        if at is None:
            return 0.0
        start = datetime.fromisoformat(self.work_start)
        end = at if at >= start else start
        extra = float(self.manual_hours) if self.manual_hours is not None else 0.0
        raw_minutes = (end - start).total_seconds() / 60.0
        pause_minutes = self.extra_pause_minutes
        for pause in self.pauses:
            if pause.end is None:
                pause_minutes += pause.elapsed_minutes(end)
            else:
                pause_minutes += pause.minutes()
        return round_to_quarter_hours(
            max(0.0, raw_minutes - pause_minutes) + extra * 60.0
        )


@dataclass
class State:
    current: WorkDay | None = None
    days: dict[str, WorkDay] = field(default_factory=dict)
    absences: dict[str, dict[str, float]] = field(default_factory=dict)
    absence_totals: dict[str, dict[str, float]] = field(default_factory=dict)

    def has_absences(self) -> bool:
        return any(self.absences.values()) or any(self.absence_totals.values())

    def to_dict(self) -> dict:
        data = {
            "current": None if self.current is None else self.current.to_dict(),
            "days": {key: day.to_dict() for key, day in self.days.items()},
        }
        absences = {kind: dict(sorted(v.items())) for kind, v in self.absences.items() if v}
        totals = {kind: dict(sorted(v.items())) for kind, v in self.absence_totals.items() if v}
        if absences:
            data["absences"] = absences
        if totals:
            data["absence_totals"] = totals
        return data

    @classmethod
    def from_dict(cls, data: dict) -> State:
        current_data = data.get("current")
        days_data = data.get("days") or {}
        return cls(
            current=None if current_data is None else WorkDay.from_dict(current_data),
            days={key: WorkDay.from_dict(value) for key, value in days_data.items()},
            absences=_float_maps(data.get("absences")),
            absence_totals=_float_maps(data.get("absence_totals")),
        )


def _float_maps(raw: dict | None) -> dict[str, dict[str, float]]:
    return {
        kind: {key: float(value) for key, value in (values or {}).items()}
        for kind, values in (raw or {}).items()
    }
