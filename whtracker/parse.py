"""Einlesen von Befehlen, Daten, Uhrzeiten und Nachträgen."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from .constants import COMMAND_ALIASES
from .models import AddPauseEntry, EditEntry, HoursQuery, ManualEntry, ParseError

_MONTH_ALIASES = {
    "januar": 1,
    "jan": 1,
    "februar": 2,
    "feb": 2,
    "märz": 3,
    "maerz": 3,
    "marz": 3,
    "mär": 3,
    "mrz": 3,
    "april": 4,
    "apr": 4,
    "mai": 5,
    "juni": 6,
    "jun": 6,
    "juli": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "oktober": 10,
    "okt": 10,
    "november": 11,
    "nov": 11,
    "dezember": 12,
    "dez": 12,
}
_MONTH_ALT = "|".join(
    re.escape(name) for name in sorted(_MONTH_ALIASES, key=len, reverse=True)
)
_DATE_NUMERIC_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\.?")
_DATE_NAMED_RE = re.compile(
    rf"^\s*(\d{{1,2}})\.?\s*({_MONTH_ALT})\b\.?(?:\s+(\d{{4}}))?",
    re.IGNORECASE,
)
_CLOCK_RE = re.compile(
    r"""
    ^\s*
    (\d{1,2})
    (?:
        [:.](\d{2})
        |
        \s*uhr(?:\s*(\d{1,2}))?
    )?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_HOURS_RE = re.compile(
    r"^\s*(\d+(?:[.,]\d+)?)\s*(?:stunden|std\.?|h)?\s*$",
    re.IGNORECASE,
)
_RANGE_SPLIT_RE = re.compile(r"\s*(?:bis|–|-)\s*", re.IGNORECASE)
KNOWN_COMMANDS = set(COMMAND_ALIASES.values())
START_PREFIX_RE = re.compile(r"^(?:start|s)\s+(?:um\s+)?(.+)$", re.IGNORECASE)
PAUSESTOP_PREFIX_RE = re.compile(
    r"^(?:ps|pausestop|pause\s+stop)\s+(?:um\s+)?(.+)$",
    re.IGNORECASE,
)
_KNOWN_COMMANDS = KNOWN_COMMANDS
_START_PREFIX_RE = START_PREFIX_RE
_PAUSESTOP_PREFIX_RE = PAUSESTOP_PREFIX_RE
_ADD_PAUSE_RE = re.compile(
    r"^\+\s*(?:pause|p)\s+(\d+)\s*(?:min(?:uten)?)?$",
    re.IGNORECASE,
)
_EDIT_RE = re.compile(
    r"^(?:edit|editiere|korrigiere)\s+(.+)$",
    re.IGNORECASE,
)
_CLOCK_HINT_RE = re.compile(r"uhr|\d{1,2}[:.]\d{2}", re.IGNORECASE)
_HOURS_QUERY_RE = re.compile(
    r"^(?:stunden|std\.?|hours)\s*(.*)$",
    re.IGNORECASE,
)
_MONTH_QUERY_RE = re.compile(
    r"^(?:monat|month)\s*(.*)$",
    re.IGNORECASE,
)
_MONTH_NUMBER_RE = re.compile(r"^(\d{1,2})(?:[./](\d{2,4}))?$")
_MONTH_NAME_ONLY_RE = re.compile(
    rf"^({_MONTH_ALT})(?:\s+(\d{{2,4}}))?$",
    re.IGNORECASE,
)
_TODAY_WORDS = {"heute", "today", "tag", "day"}
_MONTH_WORDS = {"monat", "month", "dieser monat", "aktuell"}


def parse_start_clock(raw: str) -> time | None:
    match = _START_PREFIX_RE.match(raw.strip())
    if match is None:
        return None
    return _parse_clock(match.group(1))


def parse_pausestop_clock(raw: str) -> time | None:
    match = _PAUSESTOP_PREFIX_RE.match(raw.strip())
    if match is None:
        return None
    return _parse_clock(match.group(1))


def _resolve_year(token: str | None, today: date) -> int:
    if not token:
        return today.year
    year = int(token)
    if year < 100:
        return 2000 + year
    return year


def _build_date(day: int, month: int, year: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        raise ParseError(f"Ungültiges Datum: {day}.{month}.{year}.") from None


def _parse_date_prefix(text: str, today: date) -> tuple[date, str] | None:
    named = _DATE_NAMED_RE.match(text)
    numeric = _DATE_NUMERIC_RE.match(text)
    if named and numeric:
        if named.end() >= numeric.end():
            match, kind = named, "named"
        else:
            match, kind = numeric, "numeric"
    elif named:
        match, kind = named, "named"
    elif numeric:
        match, kind = numeric, "numeric"
    else:
        return None

    day_n = int(match.group(1))
    if kind == "named":
        month_n = _MONTH_ALIASES[match.group(2).lower()]
    else:
        month_n = int(match.group(2))
        if month_n < 1 or month_n > 12:
            raise ParseError(f"Ungültiges Datum: {day_n}.{month_n}.")
    year_n = _resolve_year(match.group(3), today)
    parsed = _build_date(day_n, month_n, year_n)
    return parsed, text[match.end() :]


def parse_clock(text: str) -> time:
    stripped = text.strip()
    match = _CLOCK_RE.match(stripped)
    if match is None:
        raise ParseError(f"Ungültige Uhrzeit: {stripped}.")
    hour = int(match.group(1))
    minute = int(match.group(2) or match.group(3) or 0)
    try:
        return time(hour, minute)
    except ValueError:
        raise ParseError(f"Ungültige Uhrzeit: {stripped}.") from None


_parse_clock = parse_clock


def _parse_hours(text: str) -> float:
    match = _HOURS_RE.match(text)
    if match is None:
        raise ParseError("Stundenangabe konnte nicht gelesen werden.")
    return float(match.group(1).replace(",", "."))


def _is_range_rest(text: str) -> bool:
    lowered = text.lower()
    return "bis" in lowered or "-" in text or "–" in text


def _parse_time_range(start_day: date, rest: str, today: date) -> tuple[datetime, datetime]:
    parts = _RANGE_SPLIT_RE.split(rest.strip(), maxsplit=1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ParseError("Zeitraum konnte nicht gelesen werden.")

    start_dt = datetime.combine(start_day, _parse_clock(parts[0]))
    end_raw = parts[1].strip()
    parsed_end = _parse_date_prefix(end_raw, today)
    if parsed_end is None:
        end_day = start_day
        end_clock = _parse_clock(end_raw)
        explicit_end_date = False
    else:
        end_day, end_rest = parsed_end
        end_clock = _parse_clock(end_rest)
        explicit_end_date = True
        if end_day < start_day:
            end_day = date(end_day.year + 1, end_day.month, end_day.day)

    end_dt = datetime.combine(end_day, end_clock)
    later_end_date = explicit_end_date and end_day > start_day
    if not later_end_date and end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def _looks_like_clock(text: str) -> bool:
    return _CLOCK_HINT_RE.search(text) is not None


def parse_edit_entry(raw: str, today: date) -> EditEntry | None:
    parsed = _parse_date_prefix(raw, today)
    if parsed is None:
        return None
    day, rest = parsed
    rest = rest.strip()
    if not re.match(r"^(?:edit|editiere|korrigiere)\b", rest, re.IGNORECASE):
        return None
    match = _EDIT_RE.match(rest)
    if match is None:
        raise ParseError(
            "Bitte Stunden oder Endzeit angeben, z. B. "
            "21.09. edit 8 oder 21.09. edit 17:30."
        )
    payload = match.group(1).strip()
    pause_match = re.match(r"^pause\s+(.+)$", payload, re.IGNORECASE)
    if pause_match:
        inner = pause_match.group(1).strip()
        if _looks_like_clock(inner):
            return EditEntry(day=day, pause_end=_parse_clock(inner))
        minute_match = re.match(r"^(\d+)\s*(?:min(?:uten)?)?$", inner, re.IGNORECASE)
        if minute_match is None:
            raise ParseError("Pausenangabe konnte nicht gelesen werden.")
        minutes = int(minute_match.group(1))
        if minutes <= 0:
            raise ParseError("Pause muss länger als 0 Minuten sein.")
        return EditEntry(day=day, pause_minutes=minutes)
    if _looks_like_clock(payload):
        return EditEntry(day=day, end=_parse_clock(payload))
    hours = _parse_hours(payload)
    if hours <= 0 or hours > 36:
        raise ParseError("Stunden müssen größer als 0 und höchstens 36 sein.")
    return EditEntry(day=day, hours=hours)


def parse_add_pause_entry(raw: str, today: date) -> AddPauseEntry | None:
    text = raw.strip()
    parsed = _parse_date_prefix(text, today)
    rest = text
    day: date | None = None
    if parsed is not None:
        day, rest = parsed
        rest = rest.strip()
        if not rest.startswith("+"):
            return None
    elif not text.startswith("+"):
        return None
    match = _ADD_PAUSE_RE.match(rest)
    if match is None:
        if re.match(r"^\+\s*(?:pause|p)\b", rest, re.IGNORECASE):
            raise ParseError("Bitte Minuten angeben, z. B. + pause 10.")
        return None
    minutes = int(match.group(1))
    if minutes <= 0:
        raise ParseError("Pause muss länger als 0 Minuten sein.")
    return AddPauseEntry(minutes=minutes, day=day)


def _parse_month_token(text: str, today: date) -> tuple[int, int] | None:
    stripped = text.strip().rstrip(".")
    named = _MONTH_NAME_ONLY_RE.match(stripped)
    if named:
        month = _MONTH_ALIASES[named.group(1).lower()]
        year = _resolve_year(named.group(2), today)
        return year, month
    numbered = _MONTH_NUMBER_RE.match(stripped)
    if numbered is None:
        return None
    month = int(numbered.group(1))
    if month < 1 or month > 12:
        raise ParseError(f"Ungültiger Monat: {month}.")
    year = _resolve_year(numbered.group(2), today)
    return year, month


def parse_hours_query(raw: str, today: date) -> HoursQuery | None:
    text = raw.strip().rstrip(".,;:!")
    hours_match = _HOURS_QUERY_RE.match(text)
    month_match = _MONTH_QUERY_RE.match(text)
    if hours_match:
        rest = " ".join(hours_match.group(1).split())
        if not rest or rest.lower() in _TODAY_WORDS:
            return HoursQuery(kind="day")
        if rest.lower() in _MONTH_WORDS:
            return HoursQuery(kind="month", year=today.year, month=today.month)
        parsed = _parse_month_token(rest, today)
        if parsed is None:
            raise ParseError(
                "Monat konnte nicht gelesen werden, z. B. stunden september."
            )
        return HoursQuery(kind="month", year=parsed[0], month=parsed[1])
    if month_match:
        rest = " ".join(month_match.group(1).split())
        if not rest:
            return HoursQuery(kind="month", year=today.year, month=today.month)
        parsed = _parse_month_token(rest, today)
        if parsed is None:
            raise ParseError(
                "Monat konnte nicht gelesen werden, z. B. monat september."
            )
        return HoursQuery(kind="month", year=parsed[0], month=parsed[1])
    return None


def parse_manual_entry(raw: str, today: date) -> ManualEntry | None:
    parsed = _parse_date_prefix(raw, today)
    if parsed is None:
        return None
    day, rest = parsed
    rest = rest.strip()
    if not rest:
        raise ParseError("Bitte Stunden oder einen Zeitraum angeben.")
    if _is_range_rest(rest):
        start_dt, end_dt = _parse_time_range(day, rest, today)
        hours = (end_dt - start_dt).total_seconds() / 3600.0
        if hours <= 0 or hours > 36:
            raise ParseError("Stunden müssen größer als 0 und höchstens 36 sein.")
        return ManualEntry(day=day, start=start_dt, end=end_dt)
    hours = _parse_hours(rest)
    if hours <= 0 or hours > 36:
        raise ParseError("Stunden müssen größer als 0 und höchstens 36 sein.")
    return ManualEntry(day=day, hours=hours)
