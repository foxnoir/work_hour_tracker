#!/usr/bin/env python3
"""Interaktiver CLI-Tracker für Arbeitszeiten."""

from __future__ import annotations

import calendar
import json
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
JSON_PATH = DATA_DIR / "hours.json"
PDF_PATH = DATA_DIR / "Arbeitszeiten.pdf"
BACKUP_KEEP = 30

REMINDER_HOUR = 17
REMINDER_TIMEOUT_SECONDS = 300
PING_COUNT = 3
PING_REPEAT_SECONDS = 30
PING_SOUND = Path("/System/Library/Sounds/Ping.aiff")
REMINDER_TITLE = "Arbeitszeit-Tracker"
REMINDER_TEXT = "Nicht vergessen, dich auszustempeln."
PAUSE_REMINDER_MINUTES = 70
PAUSE_REMINDER_REPEAT_MINUTES = 10
PAUSE_REMINDER_TEXT = "Bist du noch in Pause?"

WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONTHS_DE = [
    "",
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]

COMMAND_ALIASES = {
    "start": "start",
    "s": "start",
    "pause": "pause",
    "p": "pause",
    "pausestop": "pausestop",
    "pause stop": "pausestop",
    "ps": "pausestop",
    "stop": "stop",
    "stopp": "stop",
    "finished": "stop",
    "f": "stop",
    "fertig": "stop",
    "ende": "stop",
    "status": "status",
    "pdf": "pdf",
    "abbruch": "abbruch",
    "cancel": "abbruch",
    "help": "help",
    "h": "help",
    "?": "help",
    "quit": "quit",
    "q": "quit",
    "exit": "quit",
}

HELP_TEXT = """Befehle:
  start, s                 Arbeitstag starten (jetzt)
  start 7, s 7 Uhr         Nachträglich um 7:00 starten
                           auch: start 7:00, s um 7 Uhr
  pause, p                 Pause starten
  pausestop, ps            Pause beenden (volle Minuten)
                           auch: pause stop, pause-stop
  ps 13:15                 Pause nachträglich um 13:15 beenden
  stop, stopp, f, fertig   Arbeitstag beenden und PDF aktualisieren
                           auch: finished, ende
  status                   Aktuellen Tag anzeigen
  pdf                      PDF aus gespeicherten Tagen neu erzeugen
  abbruch, cancel          Offenen Tag verwerfen (nicht ins PDF)
  help, h, ?               Diese Hilfe
  quit, q, exit            Beenden (offener Tag bleibt gespeichert)

Ab 17:00 (dann jede volle Stunde): Pings + macOS-Hinweis.
Alarm wegklicken = Arbeit läuft weiter, nächste Stunde wieder nachfragen.
Nicht wegklicken (5 Min.) = ausstempeln zur Alarmzeit, nicht 5 Minuten später.
Pause länger als 1 Std. 10 Min.: Hinweis „Noch in Pause?“
  Ja = in 10 Min. nochmal. Nein = Dauer prüfen oder Endzeit eingeben.
Nur quit beendet die Alarme ganz.

Nachtrag ohne extra Befehl, z. B.:
  21.9. 8,5 Stunden        Stunden für einen Tag
  21.9. 8,5
  21. Sept 8,5
  21. September 8,5 Stunden
  21.9. 9 Uhr bis 18 Uhr   Zeitraum
  21.9. 9:00 bis 18:00
  21.9. 9-18
  21. September 7 Uhr bis 1 Uhr 30
  21.9. 22 Uhr bis 6 Uhr   über Mitternacht, zählt zum Startdatum

Bestehenden Tag korrigieren (Start und Pausen bleiben):
  21.09. edit 8            Stunden auf 8 setzen, Ende neu rechnen
  21.09. edit 8,5 Stunden
  21.09. edit 17:30        Endzeit setzen, Stunden neu rechnen
  21. September edit 17 Uhr 30
  21.09. edit pause 45     letzte Pause auf 45 Min. setzen
  21.09. edit pause 13:15  letzte Pause um 13:15 beenden"""


def normalize_command(raw: str) -> str:
    text = raw.strip().lower().replace("-", " ")
    text = " ".join(text.split())
    text = text.rstrip(".,;:!")
    return COMMAND_ALIASES.get(text, text)


def pause_full_minutes(start: datetime, end: datetime) -> int:
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return 0
    return int(seconds // 60)


def round_to_quarter_hours(minutes: float) -> float:
    return round(minutes / 15) / 4


def format_hours(hours: float) -> str:
    quantized = round(float(hours) * 4) / 4
    if quantized == int(quantized):
        return str(int(quantized))
    return f"{quantized:.2f}".rstrip("0").replace(".", ",")


def format_time(value: datetime | str) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime("%H:%M")


def format_end_time(start: datetime | str, end: datetime | str) -> str:
    start_dt = datetime.fromisoformat(start) if isinstance(start, str) else start
    end_dt = datetime.fromisoformat(end) if isinstance(end, str) else end
    label = format_time(end_dt)
    extra_days = (end_dt.date() - start_dt.date()).days
    if extra_days > 0:
        return f"{label} (+{extra_days})"
    return label


def format_date_de(iso_date: str) -> str:
    return date.fromisoformat(iso_date).strftime("%d.%m.%Y")


def now_iso(now: datetime) -> str:
    return now.replace(microsecond=0).isoformat(timespec="seconds")


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
_KNOWN_COMMANDS = set(COMMAND_ALIASES.values())
_START_PREFIX_RE = re.compile(r"^(?:start|s)\s+(?:um\s+)?(.+)$", re.IGNORECASE)
_PAUSESTOP_PREFIX_RE = re.compile(
    r"^(?:ps|pausestop|pause\s+stop)\s+(?:um\s+)?(.+)$",
    re.IGNORECASE,
)
_EDIT_RE = re.compile(
    r"^(?:edit|editiere|korrigiere)\s+(.+)$",
    re.IGNORECASE,
)
_CLOCK_HINT_RE = re.compile(r"uhr|\d{1,2}[:.]\d{2}", re.IGNORECASE)


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


def _parse_clock(text: str) -> time:
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


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def backup_dir_for(path: Path) -> Path:
    return path.parent / "backups"


def backup_existing(path: Path, keep: int = BACKUP_KEEP) -> Path | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    folder = backup_dir_for(path)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = folder / f"{path.stem}-{stamp}{path.suffix}"
    index = 1
    while dest.exists():
        dest = folder / f"{path.stem}-{stamp}-{index}{path.suffix}"
        index += 1
    shutil.copy2(path, dest)
    pattern = f"{path.stem}-*{path.suffix}"
    old = sorted(folder.glob(pattern), key=lambda item: item.stat().st_mtime)
    for leftover in old[:-keep]:
        leftover.unlink(missing_ok=True)
    return dest


def latest_backup(path: Path) -> Path | None:
    folder = backup_dir_for(path)
    if not folder.exists():
        return None
    matches = sorted(
        folder.glob(f"{path.stem}-*{path.suffix}"),
        key=lambda item: item.stat().st_mtime,
    )
    return matches[-1] if matches else None


def read_json_object(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def load_hours_payload(json_path: Path) -> tuple[dict, str]:
    main = read_json_object(json_path) if json_path.exists() else None
    backup_path = latest_backup(json_path)
    backup = read_json_object(backup_path) if backup_path else None
    main_days = (main or {}).get("days") or {}
    backup_days = (backup or {}).get("days") or {}
    if main and main_days:
        return main, "file"
    if backup and backup_days:
        merged = dict(backup)
        if main and main.get("current") and not merged.get("current"):
            merged["current"] = main["current"]
        return merged, "backup"
    if main:
        return main, "file"
    return {"current": None, "days": {}}, "empty"


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

    def to_dict(self) -> dict:
        data = {
            "date": self.date,
            "work_start": self.work_start,
            "work_end": self.work_end,
            "pauses": [pause.to_dict() for pause in self.pauses],
        }
        if self.manual_hours is not None:
            data["manual_hours"] = self.manual_hours
        return data

    @classmethod
    def from_dict(cls, data: dict) -> WorkDay:
        return cls(
            date=data["date"],
            work_start=data.get("work_start"),
            work_end=data.get("work_end"),
            pauses=[Pause.from_dict(item) for item in data.get("pauses", [])],
            manual_hours=data.get("manual_hours"),
        )

    def open_pause(self) -> Pause | None:
        for pause in self.pauses:
            if pause.end is None:
                return pause
        return None

    def total_pause_minutes(self) -> int:
        return sum(pause.minutes() for pause in self.pauses)

    def work_minutes(self) -> float:
        if self.work_start is None or self.work_end is None:
            if self.manual_hours is not None:
                return float(self.manual_hours) * 60.0
            return 0.0
        start = datetime.fromisoformat(self.work_start)
        end = datetime.fromisoformat(self.work_end)
        raw_minutes = (end - start).total_seconds() / 60.0
        return max(0.0, raw_minutes - self.total_pause_minutes())

    def rounded_hours(self) -> float:
        if self.manual_hours is not None:
            return round_to_quarter_hours(float(self.manual_hours) * 60.0)
        return round_to_quarter_hours(self.work_minutes())


@dataclass
class State:
    current: WorkDay | None = None
    days: dict[str, WorkDay] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "current": None if self.current is None else self.current.to_dict(),
            "days": {key: day.to_dict() for key, day in self.days.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> State:
        current_data = data.get("current")
        days_data = data.get("days") or {}
        return cls(
            current=None if current_data is None else WorkDay.from_dict(current_data),
            days={key: WorkDay.from_dict(value) for key, value in days_data.items()},
        )


def reminder_window_open(now: datetime, work_start: datetime) -> bool:
    first = datetime.combine(work_start.date(), time(REMINDER_HOUR, 0))
    return now >= first


def reminder_slot(now: datetime) -> tuple[date, int]:
    return now.date(), now.hour


def next_reminder_clock(now: datetime) -> str:
    nxt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return nxt.strftime("%H:%M")


def format_duration_de(minutes: int) -> str:
    hours, mins = divmod(max(0, minutes), 60)
    if hours == 0:
        return f"{mins} Minuten"
    hour_word = "Stunde" if hours == 1 else "Stunden"
    if mins == 0:
        return f"{hours} {hour_word}"
    return f"{hours} {hour_word} und {mins} Minuten"


class ReminderUI:
    def alert(self, timeout: int) -> str:
        raise NotImplementedError

    def pause_still_away(self, timeout: int) -> str:
        raise NotImplementedError

    def pause_duration_ok(self, duration_label: str, timeout: int) -> str:
        raise NotImplementedError

    def pause_end_time(self, timeout: int) -> str | None:
        raise NotImplementedError


class MacReminderUI(ReminderUI):
    def alert(self, timeout: int) -> str:
        return self._with_pings(
            lambda: self._notify(REMINDER_TEXT) or self._ok_dialog(REMINDER_TEXT, timeout)
        )

    def pause_still_away(self, timeout: int) -> str:
        return self._with_pings(
            lambda: self._notify(PAUSE_REMINDER_TEXT)
            or self._yes_no(PAUSE_REMINDER_TEXT, timeout)
        )

    def pause_duration_ok(self, duration_label: str, timeout: int) -> str:
        question = f"{duration_label} Pause — ist das korrekt?"
        return self._with_pings(
            lambda: self._notify(question) or self._yes_no(question, timeout)
        )

    def pause_end_time(self, timeout: int) -> str | None:
        prompt = "Bis wann ging die Pause? (z. B. 13:15)"
        return self._with_pings(
            lambda: self._notify(prompt) or self._ask_text(prompt, timeout)
        )

    def _with_pings(self, action):
        stop = threading.Event()
        pinger = threading.Thread(
            target=self._ping_until,
            args=(stop,),
            name="reminder-pings",
            daemon=True,
        )
        pinger.start()
        try:
            return action()
        finally:
            stop.set()
            pinger.join(timeout=2)

    def _ping_until(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self._ping()
            if stop.wait(PING_REPEAT_SECONDS):
                return

    def _ping(self) -> None:
        sound = str(PING_SOUND) if PING_SOUND.exists() else ""
        for _ in range(PING_COUNT):
            if sound:
                subprocess.run(
                    ["afplay", sound],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                print("\a", end="", flush=True)
            threading.Event().wait(0.12)

    def _notify(self, text: str) -> None:
        script = f'display notification "{text}" with title "{REMINDER_TITLE}"'
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _run_dialog(self, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )

    def _gave_up(self, result: subprocess.CompletedProcess[str]) -> bool:
        output = f"{result.stdout} {result.stderr}".lower()
        return "gave up:true" in output or "gab auf:true" in output

    def _ok_dialog(self, text: str, timeout: int) -> str:
        script = (
            f'display dialog "{text}" with title "{REMINDER_TITLE}" '
            f'buttons {{"OK"}} default button "OK" giving up after {timeout}'
        )
        result = self._run_dialog(script)
        if self._gave_up(result):
            return "timeout"
        return "dismiss"

    def _yes_no(self, text: str, timeout: int) -> str:
        script = (
            f'display dialog "{text}" with title "{REMINDER_TITLE}" '
            f'buttons {{"Ja", "Nein"}} default button "Ja" giving up after {timeout}'
        )
        result = self._run_dialog(script)
        output = f"{result.stdout} {result.stderr}".lower()
        if self._gave_up(result):
            return "timeout"
        if "nein" in output:
            return "nein"
        return "ja"

    def _ask_text(self, text: str, timeout: int) -> str | None:
        script = (
            f'display dialog "{text}" with title "{REMINDER_TITLE}" '
            f'default answer "" buttons {{"OK"}} default button "OK" '
            f"giving up after {timeout}"
        )
        result = self._run_dialog(script)
        if self._gave_up(result) or result.returncode != 0:
            return None
        match = re.search(r"text returned:(.*?)(?:,|$)", result.stdout, re.IGNORECASE)
        if match is None:
            return None
        value = match.group(1).strip()
        return value or None


class Tracker:
    def __init__(
        self,
        json_path: Path | None = None,
        pdf_path: Path | None = None,
        reminder_ui: ReminderUI | None = None,
        reminder_timeout: int = REMINDER_TIMEOUT_SECONDS,
    ) -> None:
        self.json_path = json_path or JSON_PATH
        self.pdf_path = pdf_path or PDF_PATH
        self.reminder_ui = reminder_ui or MacReminderUI()
        self.reminder_timeout = reminder_timeout
        self._last_reminder_slot: tuple[date, int] | None = None
        self._pause_next_at: datetime | None = None
        self._reminder_stop = threading.Event()
        self._reminder_thread: threading.Thread | None = None
        self._hours_source = "empty"
        self.state = State()
        self.load()

    def start_reminders(self) -> None:
        if self._reminder_thread is not None and self._reminder_thread.is_alive():
            return
        self._reminder_stop.clear()
        self._reminder_thread = threading.Thread(
            target=self._reminder_loop,
            name="checkout-reminder",
            daemon=True,
        )
        self._reminder_thread.start()

    def stop_reminders(self) -> None:
        self._reminder_stop.set()
        thread = self._reminder_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._reminder_thread = None

    def _reminder_loop(self) -> None:
        while not self._reminder_stop.wait(1.0):
            try:
                message = self.process_pause_reminder()
                if message is None:
                    message = self.process_reminder()
            except Exception:
                continue
            if message:
                print(f"\n{message}", flush=True)
                print("> ", end="", flush=True)

    def process_reminder(self, now: datetime | None = None) -> str | None:
        alarm_at = now or datetime.now()
        current = self.state.current
        if current is None or current.work_start is None:
            return None
        if current.open_pause() is not None:
            return None
        start_dt = datetime.fromisoformat(current.work_start)
        if not reminder_window_open(alarm_at, start_dt):
            return None
        slot = reminder_slot(alarm_at)
        if self._last_reminder_slot == slot:
            return None
        self._last_reminder_slot = slot

        result = self.reminder_ui.alert(self.reminder_timeout)
        if result == "dismiss":
            nxt = next_reminder_clock(alarm_at)
            return f"Arbeit läuft weiter. Nächster Ausstempel-Alarm um {nxt}."
        if self.state.current is None:
            return None
        # Timeout: end at the alarm, not after the 5-minute wait.
        stopped = self.stop(now=alarm_at)
        return f"Alarm nicht bestätigt — ausgestempelt um {format_time(alarm_at)}. {stopped}"

    def process_pause_reminder(self, now: datetime | None = None) -> str | None:
        alarm_at = now or datetime.now()
        current = self.state.current
        if current is None:
            self._pause_next_at = None
            return None
        pause = current.open_pause()
        if pause is None:
            self._pause_next_at = None
            return None
        elapsed = pause.elapsed_minutes(alarm_at)
        if elapsed < PAUSE_REMINDER_MINUTES:
            return None
        if self._pause_next_at is not None and alarm_at < self._pause_next_at:
            return None

        still = self.reminder_ui.pause_still_away(self.reminder_timeout)
        if still in {"ja", "timeout"}:
            self._pause_next_at = alarm_at + timedelta(
                minutes=PAUSE_REMINDER_REPEAT_MINUTES
            )
            return (
                "Noch in Pause. Nächster Hinweis in "
                f"{PAUSE_REMINDER_REPEAT_MINUTES} Minuten."
            )

        label = format_duration_de(elapsed)
        confirmed = self.reminder_ui.pause_duration_ok(label, self.reminder_timeout)
        if confirmed in {"ja", "timeout"}:
            end = pause.start_dt + timedelta(minutes=elapsed)
            self._stop_open_pause(current, end)
            self._pause_next_at = None
            self.save()
            return (
                f"Pause beendet nach {label} "
                f"(um {format_time(end)}). Arbeit läuft weiter."
            )

        raw_end = self.reminder_ui.pause_end_time(self.reminder_timeout)
        if not raw_end:
            self._pause_next_at = alarm_at + timedelta(
                minutes=PAUSE_REMINDER_REPEAT_MINUTES
            )
            return (
                "Pause-Ende nicht angegeben. "
                f"Nächster Hinweis in {PAUSE_REMINDER_REPEAT_MINUTES} Minuten."
            )
        try:
            clock = _parse_clock(raw_end)
        except ParseError as exc:
            self._pause_next_at = alarm_at + timedelta(
                minutes=PAUSE_REMINDER_REPEAT_MINUTES
            )
            return f"{exc} Nächster Hinweis in {PAUSE_REMINDER_REPEAT_MINUTES} Minuten."
        end = datetime.combine(pause.start_dt.date(), clock)
        if end <= pause.start_dt:
            end += timedelta(days=1)
        self._stop_open_pause(current, end)
        self._pause_next_at = None
        self.save()
        minutes = pause.minutes()
        return (
            f"Pause beendet um {format_time(end)} ({minutes} Min.). "
            "Arbeit läuft weiter."
        )

    def load(self) -> None:
        payload, source = load_hours_payload(self.json_path)
        self.state = State.from_dict(payload)
        self._hours_source = source

    def save(self) -> None:
        existing = read_json_object(self.json_path) if self.json_path.exists() else None
        old_days = set((existing or {}).get("days") or {})
        new_days = set(self.state.days)
        if existing and (not new_days and old_days or old_days - new_days):
            backup_existing(self.json_path)
        atomic_write_text(
            self.json_path,
            json.dumps(self.state.to_dict(), ensure_ascii=False, indent=2),
        )

    def _write_pdf(self) -> Path:
        backup_existing(self.json_path)
        if self.pdf_path.exists():
            backup_existing(self.pdf_path)
            if not self.state.days:
                return self.pdf_path
        return generate_pdf(self.state.days, self.pdf_path)

    def start(self, now: datetime | None = None, at: time | None = None) -> str:
        now = now or datetime.now()
        started = datetime.combine(now.date(), at) if at is not None else now
        if started > now:
            return (
                f"{format_time(started)} liegt in der Zukunft "
                f"(jetzt {format_time(now)})."
            )
        today = started.date().isoformat()
        if self.state.current is not None:
            if self.state.current.date != today:
                return (
                    f"Es gibt noch einen offenen Tag vom "
                    f"{format_date_de(self.state.current.date)}. "
                    f"Bitte zuerst mit 'f' beenden oder mit 'abbruch' verwerfen."
                )
            return "Die Arbeit wurde heute bereits gestartet."
        self.state.current = WorkDay(date=today, work_start=now_iso(started))
        self.save()
        return (
            f"Arbeit gestartet am {format_date_de(today)} um {format_time(started)}."
        )

    def pause(self, now: datetime | None = None) -> str:
        now = now or datetime.now()
        current = self.state.current
        if current is None:
            return "Kein laufender Arbeitstag. Starte zuerst mit 'start'."
        if current.open_pause() is not None:
            return "Es läuft bereits eine Pause."
        current.pauses.append(Pause(start=now_iso(now)))
        self._pause_next_at = None
        self.save()
        return f"Pause gestartet um {format_time(now)} (bisher 0 Min., Pausen heute: {current.total_pause_minutes()} Min.)."

    def pausestop(self, now: datetime | None = None, at: time | None = None) -> str:
        now = now or datetime.now()
        current = self.state.current
        if current is None:
            return "Kein laufender Arbeitstag. Starte zuerst mit 'start'."
        pause = current.open_pause()
        if pause is None:
            return "Es läuft keine Pause."
        ended = now
        if at is not None:
            ended = datetime.combine(pause.start_dt.date(), at)
            if ended <= pause.start_dt:
                ended += timedelta(days=1)
            if ended > now:
                return (
                    f"{format_time(ended)} liegt in der Zukunft "
                    f"(jetzt {format_time(now)})."
                )
        minutes = self._stop_open_pause(current, ended)
        self._pause_next_at = None
        self.save()
        total = current.total_pause_minutes()
        return (
            f"Pause beendet um {format_time(ended)} ({minutes} Min.). "
            f"Pausen heute: {total} Min."
        )

    def stop(self, now: datetime | None = None) -> str:
        now = now or datetime.now()
        current = self.state.current
        if current is None:
            return "Kein offener Arbeitstag."
        self._stop_open_pause(current, now)
        current.work_end = now_iso(now)
        hours = current.rounded_hours()
        self.state.days[current.date] = current
        self.state.current = None
        self.save()
        self._write_pdf()
        return (
            f"Arbeitstag beendet um {format_time(now)}. "
            f"Stunden: {format_hours(hours)}. PDF aktualisiert."
        )

    def status(self) -> str:
        current = self.state.current
        if current is None:
            finished = len(self.state.days)
            extra = f" Gespeicherte Tage: {finished}." if finished else ""
            return f"Kein offener Arbeitstag.{extra}"
        lines = [
            f"Aktueller Tag: {format_date_de(current.date)}",
            f"Arbeit gestartet: {format_time(current.work_start)}",
        ]
        if current.pauses:
            lines.append("Pausen:")
            for pause in current.pauses:
                if pause.end is None:
                    lines.append(f"  {format_time(pause.start)}– (läuft)")
                else:
                    lines.append(f"  {pause.range_label()} ({pause.minutes()} Min.)")
        else:
            lines.append("Pausen: keine")
        lines.append(f"Pause gesamt: {current.total_pause_minutes()} Min.")
        if current.open_pause() is not None:
            lines.append("Status: Pause läuft")
        else:
            lines.append("Status: Arbeit läuft")
        return "\n".join(lines)

    def pdf(self) -> str:
        path = self._write_pdf()
        if not self.state.days and path.exists():
            return f"Keine neuen Tage — bestehende PDF behalten: {path}."
        return f"PDF gespeichert unter {path}."

    def abbruch(self) -> str:
        if self.state.current is None:
            return "Kein offener Arbeitstag zum Verwerfen."
        self.state.current = None
        self.save()
        return "Offener Tag verworfen. Es wurde nichts ins PDF übernommen."

    def dispatch(self, command: str, now: datetime | None = None) -> str:
        timed = {
            "start": self.start,
            "pause": self.pause,
            "pausestop": self.pausestop,
            "stop": self.stop,
        }
        if command in timed:
            return timed[command](now=now)
        handlers = {
            "status": self.status,
            "pdf": self.pdf,
            "abbruch": self.abbruch,
            "help": lambda: HELP_TEXT,
            "quit": lambda: "Beendet. Offener Tag bleibt gespeichert.",
        }
        handler = handlers.get(command)
        if handler is None:
            return f"Unbekannter Befehl: {command}. Tippe 'help' für Hilfe."
        return handler()

    def handle(self, raw: str, now: datetime | None = None) -> str:
        now = now or datetime.now()
        command = normalize_command(raw)
        if command in _KNOWN_COMMANDS:
            return self.dispatch(command, now=now)
        if _START_PREFIX_RE.match(raw.strip()):
            try:
                clock = parse_start_clock(raw)
            except ParseError as exc:
                return str(exc)
            if clock is None:
                return f"Unbekannter Befehl: {command}. Tippe 'help' für Hilfe."
            return self.start(now=now, at=clock)
        if _PAUSESTOP_PREFIX_RE.match(raw.strip()):
            try:
                clock = parse_pausestop_clock(raw)
            except ParseError as exc:
                return str(exc)
            if clock is None:
                return f"Unbekannter Befehl: {command}. Tippe 'help' für Hilfe."
            return self.pausestop(now=now, at=clock)
        edited = self.try_edit(raw, now=now)
        if edited is not None:
            return edited
        message = self.try_manual(raw, now=now)
        if message is not None:
            return message
        return f"Unbekannter Befehl: {command}. Tippe 'help' für Hilfe."

    def try_edit(self, raw: str, now: datetime | None = None) -> str | None:
        now = now or datetime.now()
        try:
            entry = parse_edit_entry(raw, now.date())
        except ParseError as exc:
            return str(exc)
        if entry is None:
            return None
        return self.apply_edit(entry)

    def apply_edit(self, entry: EditEntry) -> str:
        day_key = entry.day.isoformat()
        from_current = (
            self.state.current is not None and self.state.current.date == day_key
        )
        work_day = self.state.current if from_current else self.state.days.get(day_key)
        if work_day is None:
            return f"Kein Eintrag für {format_date_de(day_key)}."

        if entry.pause_minutes is not None or entry.pause_end is not None:
            return self._apply_pause_edit(work_day, entry, from_current)

        if entry.hours is not None:
            hours = round_to_quarter_hours(entry.hours * 60)
            if work_day.work_start is None:
                work_day.manual_hours = hours
                work_day.work_end = None
                work_day.pauses = []
            else:
                start = datetime.fromisoformat(work_day.work_start)
                end = start + timedelta(
                    minutes=hours * 60 + work_day.total_pause_minutes()
                )
                self._stop_open_pause(work_day, end)
                end = start + timedelta(
                    minutes=hours * 60 + work_day.total_pause_minutes()
                )
                work_day.work_end = now_iso(end)
                work_day.manual_hours = None
            detail = (
                f"{format_date_de(day_key)} auf {format_hours(hours)} Stunden "
                f"korrigiert."
            )
        else:
            if work_day.work_start is None:
                return (
                    f"{format_date_de(day_key)} hat keine Startzeit. "
                    f"Bitte Stunden setzen, z. B. {entry.day.day}.{entry.day.month}. edit 8."
                )
            assert entry.end is not None
            start = datetime.fromisoformat(work_day.work_start)
            end = datetime.combine(start.date(), entry.end)
            if end <= start:
                end += timedelta(days=1)
            self._stop_open_pause(work_day, end)
            work_day.work_end = now_iso(end)
            work_day.manual_hours = None
            hours = work_day.rounded_hours()
            detail = (
                f"{format_date_de(day_key)}: Ende auf "
                f"{format_end_time(start, end)} gesetzt "
                f"({format_hours(hours)} Stunden)."
            )

        if from_current:
            self.state.days[day_key] = work_day
            self.state.current = None
        else:
            self.state.days[day_key] = work_day
        self.save()
        self._write_pdf()
        return f"{detail} PDF aktualisiert."

    def _apply_pause_edit(
        self,
        work_day: WorkDay,
        entry: EditEntry,
        from_current: bool,
    ) -> str:
        if not work_day.pauses:
            return f"{format_date_de(work_day.date)} hat keine Pause zum Korrigieren."
        pause = work_day.pauses[-1]
        if entry.pause_minutes is not None:
            end = pause.start_dt + timedelta(minutes=entry.pause_minutes)
        else:
            assert entry.pause_end is not None
            end = datetime.combine(pause.start_dt.date(), entry.pause_end)
            if end <= pause.start_dt:
                end += timedelta(days=1)
        pause.end = now_iso(end)
        self._pause_next_at = None
        if from_current and work_day.work_end is None:
            self.state.current = work_day
        else:
            self.state.days[work_day.date] = work_day
            self._write_pdf()
        self.save()
        minutes = pause.minutes()
        extra = " PDF aktualisiert." if not from_current or work_day.work_end else ""
        return (
            f"{format_date_de(work_day.date)}: letzte Pause "
            f"{format_time(pause.start)}–{format_time(end)} "
            f"({minutes} Min.).{extra}"
        )

    def try_manual(self, raw: str, now: datetime | None = None) -> str | None:
        now = now or datetime.now()
        try:
            entry = parse_manual_entry(raw, now.date())
        except ParseError as exc:
            return str(exc)
        if entry is None:
            return None
        return self.apply_manual(entry)

    def apply_manual(self, entry: ManualEntry) -> str:
        day_key = entry.day.isoformat()
        current = self.state.current
        if current is not None and current.date == day_key:
            return (
                f"Der {format_date_de(day_key)} wird gerade erfasst. "
                f"Bitte zuerst mit 'f' beenden oder mit 'abbruch' verwerfen."
            )
        replaced = day_key in self.state.days
        if entry.hours is not None:
            hours = round_to_quarter_hours(entry.hours * 60)
            work_day = WorkDay(
                date=day_key,
                work_start=None,
                work_end=None,
                pauses=[],
                manual_hours=hours,
            )
            detail = (
                f"{format_date_de(day_key)}: {format_hours(hours)} Stunden "
                f"eingetragen. PDF aktualisiert."
            )
        else:
            if entry.start is None or entry.end is None:
                raise ParseError("Zeitraum konnte nicht gelesen werden.")
            work_day = WorkDay(
                date=day_key,
                work_start=now_iso(entry.start),
                work_end=now_iso(entry.end),
                pauses=[],
            )
            hours = work_day.rounded_hours()
            detail = (
                f"{format_date_de(day_key)}: "
                f"{format_time(entry.start)}–{format_end_time(entry.start, entry.end)} "
                f"({format_hours(hours)} Stunden). PDF aktualisiert."
            )
        self.state.days[day_key] = work_day
        self.save()
        self._write_pdf()
        if replaced:
            return f"Eintrag für {format_date_de(day_key)} ersetzt. {detail}"
        return detail

    def _stop_open_pause(self, day: WorkDay, now: datetime) -> int | None:
        pause = day.open_pause()
        if pause is None:
            return None
        pause.end = now_iso(now)
        return pause.minutes()


def _cell_style(name: str, font_name: str, font_size: int, text_color: colors.Color) -> ParagraphStyle:
    return ParagraphStyle(
        name=name,
        fontName=font_name,
        fontSize=font_size,
        leading=font_size + 2,
        textColor=text_color,
        alignment=TA_CENTER,
        encoding="latin-1",
    )


def generate_pdf(
    days: dict[str, WorkDay],
    pdf_path: Path,
    today: date | None = None,
) -> Path:
    today = today or date.today()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if pdf_path.exists() and not days:
        return pdf_path

    months: set[tuple[int, int]] = set()
    for key in days:
        day = date.fromisoformat(key)
        months.add((day.year, day.month))
    if not months:
        months.add((today.year, today.month))

    header_style = _cell_style("pdf_header", "Helvetica-Bold", 8, colors.white)
    cell_style = _cell_style("pdf_cell", "Helvetica", 8, colors.black)
    title_style = ParagraphStyle(
        "pdf_title",
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.black,
        alignment=TA_LEFT,
        encoding="latin-1",
        spaceAfter=6,
    )
    footer_style = ParagraphStyle(
        "pdf_footer",
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        textColor=colors.black,
        alignment=TA_LEFT,
        encoding="latin-1",
    )

    story: list = []
    page_width, _page_height = A4
    usable_width = page_width - 30 * mm
    col_widths = [
        usable_width * 0.10,
        usable_width * 0.18,
        usable_width * 0.24,
        usable_width * 0.18,
        usable_width * 0.16,
        usable_width * 0.14,
    ]
    headers = [
        "Tag",
        "Arbeit gestartet",
        "Pause gestartet",
        "Arbeit beendet",
        "Pause gesamt",
        "Stunden",
    ]

    for index, (year, month) in enumerate(sorted(months)):
        if index > 0:
            story.append(PageBreak())
        title = f"Arbeitszeitenüberblick {MONTHS_DE[month]} {year}"
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 4 * mm))

        table_data = [[Paragraph(text, header_style) for text in headers]]
        weekend_rows: list[int] = []
        month_total = 0.0
        _, day_count = calendar.monthrange(year, month)

        for day_num in range(1, day_count + 1):
            current = date(year, month, day_num)
            weekday = current.weekday()
            row_index = day_num
            if weekday >= 5:
                weekend_rows.append(row_index)

            key = current.isoformat()
            work_day = days.get(key)
            tag = f"{day_num} {WEEKDAYS_DE[weekday]}"
            started = ""
            pauses_html = ""
            ended = ""
            pause_total = ""
            hours_text = ""

            if work_day is not None:
                if work_day.work_start is not None:
                    started = format_time(work_day.work_start)
                if work_day.work_end is not None:
                    if work_day.work_start is not None:
                        ended = format_end_time(work_day.work_start, work_day.work_end)
                    else:
                        ended = format_time(work_day.work_end)
                if work_day.pauses:
                    pause_bits = [pause.range_label() for pause in work_day.pauses]
                    pauses_html = "<br/>".join(pause_bits)
                    pause_total = f"{work_day.total_pause_minutes()} Min."
                hours = work_day.rounded_hours()
                hours_text = format_hours(hours)
                month_total += hours

            table_data.append(
                [
                    Paragraph(tag, cell_style),
                    Paragraph(started, cell_style),
                    Paragraph(pauses_html, cell_style),
                    Paragraph(ended, cell_style),
                    Paragraph(pause_total, cell_style),
                    Paragraph(hours_text, cell_style),
                ]
            )

        style_commands: list[tuple] = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C2C2C")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#666666")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for row in weekend_rows:
            style_commands.append(
                ("BACKGROUND", (0, row), (-1, row), colors.HexColor("#E8E8E8"))
            )

        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle(style_commands))
        story.append(table)
        story.append(Spacer(1, 6 * mm))
        footer = f"Monat Gesamtstunden: {format_hours(month_total)}"
        story.append(Paragraph(footer, footer_style))

    document = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Arbeitszeitenüberblick",
    )
    document.build(story)
    return pdf_path


def run_cli() -> None:
    tracker = Tracker()
    tracker.start_reminders()
    print("Arbeitszeit-Tracker – tippe 'help' für die Befehlsliste.")
    if tracker._hours_source == "backup":
        print(
            f"Stunden aus Sicherung geladen ({len(tracker.state.days)} Tage)."
        )
    elif tracker.state.days:
        print(f"{len(tracker.state.days)} gespeicherte Tage gefunden.")
    if tracker.state.current is not None:
        print(tracker.status())
    try:
        while True:
            try:
                raw = input("> ")
            except (KeyboardInterrupt, EOFError):
                print("\nBeendet. Offener Tag bleibt gespeichert.")
                return
            if not raw.strip():
                continue
            command = normalize_command(raw)
            print(tracker.handle(raw))
            if command == "quit":
                return
    finally:
        tracker.stop_reminders()


def main() -> None:
    try:
        run_cli()
    except (KeyboardInterrupt, EOFError):
        print("\nBeendet. Offener Tag bleibt gespeichert.")
        sys.exit(0)


if __name__ == "__main__":
    main()
