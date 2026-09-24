"""Berliner Feiertage, Arbeitstage und Sollstunden."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache

from .constants import ABSENCE_KINDS, DAILY_TARGET_HOURS, EMPLOYMENT_START


def easter_sunday(year: int) -> date:
    """Ostersonntag (gregorianisch, Anonymous-Gregorian-Algorithmus)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=None)
def berlin_holidays(year: int) -> dict[date, str]:
    """Gesetzliche Feiertage in Berlin plus Heiligabend und Silvester (arbeitsfrei)."""
    easter = easter_sunday(year)
    holidays = {
        date(year, 1, 1): "Neujahr",
        date(year, 3, 8): "Frauentag",
        easter - timedelta(days=2): "Karfreitag",
        easter + timedelta(days=1): "Ostermontag",
        date(year, 5, 1): "Tag der Arbeit",
        easter + timedelta(days=39): "Christi Himmelfahrt",
        easter + timedelta(days=50): "Pfingstmontag",
        date(year, 10, 3): "Tag der Deutschen Einheit",
        date(year, 12, 24): "Heiligabend",
        date(year, 12, 25): "1. Weihnachtstag",
        date(year, 12, 26): "2. Weihnachtstag",
        date(year, 12, 31): "Silvester",
    }
    if year < 2019:
        del holidays[date(year, 3, 8)]
    return holidays


def holiday_name(day: date) -> str | None:
    return berlin_holidays(day.year).get(day)


def is_workday(day: date) -> bool:
    """Mo–Fr, kein Feiertag, ab Arbeitsbeginn."""
    return day.weekday() < 5 and holiday_name(day) is None and day >= EMPLOYMENT_START


def non_workday_reason(day: date) -> str:
    if day < EMPLOYMENT_START:
        return "vor Arbeitsbeginn"
    holiday = holiday_name(day)
    if holiday is not None:
        return f"Feiertag ({holiday})"
    return "Wochenende"


def workdays_between(start: date, end: date) -> list[date]:
    found: list[date] = []
    current = start
    while current <= end:
        if is_workday(current):
            found.append(current)
        current += timedelta(days=1)
    return found


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


@dataclass
class Deduction:
    """Abzug vom Soll: Feiertage oder eine Abwesenheitsart (datiert + pauschal)."""

    name: str
    dates: list[date] = field(default_factory=list)
    dated_days: float = 0.0
    lump_days: float = 0.0

    @property
    def days(self) -> float:
        return self.dated_days + self.lump_days

    @property
    def hours(self) -> float:
        return self.days * DAILY_TARGET_HOURS


@dataclass
class TargetBreakdown:
    weekdays: int
    deductions: list[Deduction]

    @property
    def base_hours(self) -> float:
        return self.weekdays * DAILY_TARGET_HOURS

    @property
    def target_days(self) -> float:
        return max(0.0, self.weekdays - sum(item.days for item in self.deductions))

    @property
    def total(self) -> float:
        return self.target_days * DAILY_TARGET_HOURS


def target_breakdown(
    year: int,
    month: int,
    absences: dict[str, dict[str, float]] | None = None,
    absence_totals: dict[str, dict[str, float]] | None = None,
) -> TargetBreakdown:
    """Mo–Fr ab Arbeitsbeginn, minus Feiertage, Urlaub und Krank (immer alle aufgeführt)."""
    absences = absences or {}
    absence_totals = absence_totals or {}
    _, day_count = calendar.monthrange(year, month)
    weekdays = [
        date(year, month, num)
        for num in range(1, day_count + 1)
        if date(year, month, num).weekday() < 5 and date(year, month, num) >= EMPLOYMENT_START
    ]
    holidays = [day for day in weekdays if holiday_name(day) is not None]
    deductions = [Deduction(name="Feiertage", dates=holidays, dated_days=float(len(holidays)))]
    workdays = [day for day in weekdays if holiday_name(day) is None]
    for kind, name in ABSENCE_KINDS.items():
        dated = absences.get(kind) or {}
        booked = [day for day in workdays if dated.get(day.isoformat())]
        deductions.append(
            Deduction(
                name=name,
                dates=booked,
                dated_days=sum(min(1.0, dated[day.isoformat()]) for day in booked),
                lump_days=(absence_totals.get(kind) or {}).get(month_key(year, month), 0.0),
            )
        )
    return TargetBreakdown(weekdays=len(weekdays), deductions=deductions)


def target_hours(
    year: int,
    month: int,
    absences: dict[str, dict[str, float]] | None = None,
    absence_totals: dict[str, dict[str, float]] | None = None,
) -> float:
    return target_breakdown(year, month, absences, absence_totals).total
