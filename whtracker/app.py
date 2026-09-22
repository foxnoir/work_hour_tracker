"""CLI-Tracker: Befehle, Persistenz und Erinnerungen."""

from __future__ import annotations

import json
import sys
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .constants import (
    HELP_TEXT,
    JSON_PATH,
    MONTHS_DE,
    PAUSE_REMINDER_MINUTES,
    PAUSE_REMINDER_REPEAT_MINUTES,
    PDF_PATH,
    REMINDER_TIMEOUT_SECONDS,
)
from .format import (
    format_date_de,
    format_end_time,
    format_hours,
    format_time,
    normalize_command,
    now_iso,
    pause_full_minutes,
    round_to_quarter_hours,
)
from .models import (
    AddPauseEntry,
    EditEntry,
    HoursQuery,
    ManualEntry,
    Pause,
    ParseError,
    State,
    WorkDay,
)
from .parse import (
    KNOWN_COMMANDS,
    PAUSESTOP_PREFIX_RE,
    START_PREFIX_RE,
    parse_add_pause_entry,
    parse_clock,
    parse_edit_entry,
    parse_hours_query,
    parse_manual_entry,
    parse_pausestop_clock,
    parse_start_clock,
)
from .pdf import generate_pdf
from .reminders import (
    MacReminderUI,
    ReminderUI,
    format_duration_de,
    next_reminder_clock,
    reminder_slot,
    reminder_window_open,
)
from .storage import (
    atomic_write_text,
    backup_existing,
    load_hours_payload,
    read_json_object,
)

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
            clock = parse_clock(raw_end)
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
        previous = self.state.days.get(today)
        if previous is not None:
            return self._resume_day(previous, started)
        self.state.current = WorkDay(date=today, work_start=now_iso(started))
        self.save()
        return (
            f"Arbeit gestartet am {format_date_de(today)} um {format_time(started)}."
        )

    def _resume_day(self, previous: WorkDay, started: datetime) -> str:
        current = WorkDay.from_dict(previous.to_dict())
        gap_end = current.work_end
        if current.work_start is None:
            current.work_start = now_iso(started)
        elif gap_end is not None:
            gap_start = datetime.fromisoformat(gap_end)
            if pause_full_minutes(gap_start, started) > 0:
                current.pauses.append(
                    Pause(start=gap_end, end=now_iso(started))
                )
        current.work_end = None
        self.state.current = current
        self.save()
        already = previous.rounded_hours()
        return (
            f"Arbeit fortgesetzt um {format_time(started)}. "
            f"Bisher {format_hours(already)} Stunden bleiben erhalten."
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

    def status(self, now: datetime | None = None) -> str:
        now = now or datetime.now()
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
        if current.extra_pause_minutes:
            lines.append(f"Extra-Pause: {current.extra_pause_minutes} Min.")
        lines.append(f"Pause gesamt: {current.total_pause_minutes()} Min.")
        if current.open_pause() is not None:
            lines.append("Status: Pause läuft")
        else:
            lines.append("Status: Arbeit läuft")
        lines.append(f"Stunden bisher: {format_hours(current.hours_at(now))}")
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
            "status": self.status,
        }
        if command in timed:
            return timed[command](now=now)
        handlers = {
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
        if command in KNOWN_COMMANDS:
            return self.dispatch(command, now=now)
        if START_PREFIX_RE.match(raw.strip()):
            try:
                clock = parse_start_clock(raw)
            except ParseError as exc:
                return str(exc)
            if clock is None:
                return f"Unbekannter Befehl: {command}. Tippe 'help' für Hilfe."
            return self.start(now=now, at=clock)
        if PAUSESTOP_PREFIX_RE.match(raw.strip()):
            try:
                clock = parse_pausestop_clock(raw)
            except ParseError as exc:
                return str(exc)
            if clock is None:
                return f"Unbekannter Befehl: {command}. Tippe 'help' für Hilfe."
            return self.pausestop(now=now, at=clock)
        added = self.try_add_pause(raw, now=now)
        if added is not None:
            return added
        queried = self.try_hours_query(raw, now=now)
        if queried is not None:
            return queried
        edited = self.try_edit(raw, now=now)
        if edited is not None:
            return edited
        message = self.try_manual(raw, now=now)
        if message is not None:
            return message
        return f"Unbekannter Befehl: {command}. Tippe 'help' für Hilfe."

    def day_for(self, day_key: str) -> WorkDay | None:
        current = self.state.current
        if current is not None and current.date == day_key:
            return current
        return self.state.days.get(day_key)

    def days_in_month(self, year: int, month: int) -> list[WorkDay]:
        found: list[WorkDay] = []
        seen: set[str] = set()
        current = self.state.current
        if current is not None:
            current_day = date.fromisoformat(current.date)
            if current_day.year == year and current_day.month == month:
                found.append(current)
                seen.add(current.date)
        for key, work_day in self.state.days.items():
            if key in seen:
                continue
            day = date.fromisoformat(key)
            if day.year == year and day.month == month:
                found.append(work_day)
        return found

    def try_hours_query(self, raw: str, now: datetime | None = None) -> str | None:
        now = now or datetime.now()
        try:
            query = parse_hours_query(raw, now.date())
        except ParseError as exc:
            return str(exc)
        if query is None:
            return None
        return self.show_hours(query, now=now)

    def show_hours(self, query: HoursQuery, now: datetime) -> str:
        if query.kind == "day":
            return self._format_today_hours(now)
        year = query.year if query.year is not None else now.year
        month = query.month if query.month is not None else now.month
        return self._format_month_hours(year, month, now)

    def _format_today_hours(self, now: datetime) -> str:
        day_key = now.date().isoformat()
        work_day = self.day_for(day_key)
        label = f"Heute bisher ({format_date_de(day_key)})"
        if work_day is None:
            return f"{label}: noch keine Stunden."
        hours = work_day.hours_at(now)
        return f"{label}: {format_hours(hours)} Stunden."

    def _format_month_hours(self, year: int, month: int, now: datetime) -> str:
        month_name = MONTHS_DE[month]
        current_month = now.year == year and now.month == month
        suffix = " bisher" if current_month else ""
        label = f"{month_name} {year}{suffix}"
        work_days = self.days_in_month(year, month)
        totals = [day.hours_at(now) for day in work_days]
        hours = sum(totals)
        counted = sum(1 for value in totals if value > 0)
        if counted == 0:
            return f"{label}: noch keine Stunden."
        days_label = "Tag" if counted == 1 else "Tage"
        return (
            f"{label}: {format_hours(hours)} Stunden "
            f"({counted} {days_label})."
        )

    def try_add_pause(self, raw: str, now: datetime | None = None) -> str | None:
        now = now or datetime.now()
        try:
            entry = parse_add_pause_entry(raw, now.date())
        except ParseError as exc:
            return str(exc)
        if entry is None:
            return None
        return self.apply_add_pause(entry, now=now)

    def apply_add_pause(self, entry: AddPauseEntry, now: datetime) -> str:
        if entry.day is not None:
            day_key = entry.day.isoformat()
            from_current = (
                self.state.current is not None and self.state.current.date == day_key
            )
            work_day = self.state.current if from_current else self.state.days.get(day_key)
            if work_day is None:
                return f"Kein Eintrag für {format_date_de(day_key)}."
        elif self.state.current is not None:
            work_day = self.state.current
            from_current = True
            day_key = work_day.date
        else:
            day_key = now.date().isoformat()
            work_day = self.state.days.get(day_key)
            from_current = False
            if work_day is None:
                return (
                    "Kein Eintrag für heute. "
                    "Bitte Datum angeben, z. B. 21.09. + pause 10."
                )

        work_day.extra_pause_minutes += entry.minutes
        if from_current:
            self.state.current = work_day
            self.save()
        else:
            self.state.days[day_key] = work_day
            self.save()
            self._write_pdf()

        hours_bit = ""
        if work_day.work_end is not None or work_day.manual_hours is not None:
            hours_bit = f" Stunden: {format_hours(work_day.rounded_hours())}."
        pdf_bit = "" if from_current else " PDF aktualisiert."
        return (
            f"{entry.minutes} Min. Extra-Pause addiert "
            f"({format_date_de(day_key)}). "
            f"Pause gesamt {work_day.total_pause_minutes()} Min.{hours_bit}{pdf_bit}"
        )

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
