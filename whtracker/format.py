"""Anzeige- und Zeit-Helfer."""

from __future__ import annotations

from datetime import date, datetime

from .constants import COMMAND_ALIASES

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
