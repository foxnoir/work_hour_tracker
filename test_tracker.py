from __future__ import annotations

from datetime import date, datetime, timedelta, time
from pathlib import Path

import pytest

from tracker import (
    ParseError,
    Pause,
    ReminderUI,
    Tracker,
    WorkDay,
    PAUSE_REMINDER_MINUTES,
    format_duration_de,
    format_end_time,
    REMINDER_TIMEOUT_SECONDS,
    format_hours,
    normalize_command,
    parse_edit_entry,
    parse_manual_entry,
    parse_start_clock,
    pause_full_minutes,
    reminder_window_open,
    round_to_quarter_hours,
)

TODAY = date(2026, 9, 22)
NOW = datetime(2026, 9, 22, 12, 0, 0)


def test_pause_full_minutes_floors_seconds() -> None:
    start = datetime(2026, 9, 22, 10, 0, 0)
    almost_six = datetime(2026, 9, 22, 10, 5, 59)
    exact_six = datetime(2026, 9, 22, 10, 6, 0)
    assert pause_full_minutes(start, almost_six) == 5
    assert pause_full_minutes(start, exact_six) == 6


def test_quarter_hours() -> None:
    assert round_to_quarter_hours(15) == 0.25
    assert round_to_quarter_hours(30) == 0.5
    assert round_to_quarter_hours(45) == 0.75
    assert round_to_quarter_hours(8 * 60 + 15) == 8.25


def test_format_hours_german_comma() -> None:
    assert format_hours(8.5) == "8,5"
    assert format_hours(8.25) == "8,25"
    assert format_hours(8.0) == "8"
    assert format_hours(8.75) == "8,75"


def test_multiple_pauses_hours() -> None:
    day = WorkDay(
        date="2026-09-22",
        work_start="2026-09-22T09:00:00",
        work_end="2026-09-22T17:30:00",
        pauses=[
            Pause("2026-09-22T10:00:00", "2026-09-22T10:30:00"),
            Pause("2026-09-22T12:00:00", "2026-09-22T12:23:00"),
        ],
    )
    assert day.total_pause_minutes() == 53
    assert day.rounded_hours() == 7.5
    assert format_hours(day.rounded_hours()) == "7,5"


def test_normalize_command_pausestop() -> None:
    assert normalize_command("PS") == "pausestop"
    assert normalize_command("Pause Stop") == "pausestop"
    assert normalize_command("pausestop") == "pausestop"
    assert normalize_command("pause-stop") == "pausestop"
    assert normalize_command(" pause  stop ") == "pausestop"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("start", "start"),
        ("START", "start"),
        ("Start", "start"),
        ("s", "start"),
        ("S", "start"),
        ("pause", "pause"),
        ("PAUSE", "pause"),
        ("Pause", "pause"),
        ("p", "pause"),
        ("P", "pause"),
        ("stop", "stop"),
        ("STOP", "stop"),
        ("Stop", "stop"),
        ("stopp", "stop"),
        ("STOPP", "stop"),
        ("stop.", "stop"),
    ],
)
def test_normalize_full_command_words(raw: str, expected: str) -> None:
    assert normalize_command(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "21.9. 8,5",
        "21. Sept 8,5",
        "21. September 8,5 Stunden",
    ],
)
def test_parse_manual_date_defaults_to_current_year(raw: str) -> None:
    entry = parse_manual_entry(raw, TODAY)
    assert entry is not None
    assert entry.day == date(2026, 9, 21)


def test_parse_hours_only() -> None:
    entry = parse_manual_entry("21.9. 8,5 Stunden", TODAY)
    assert entry is not None
    assert entry.day == date(2026, 9, 21)
    assert entry.hours == 8.5
    assert entry.start is None
    assert entry.end is None


def test_parse_same_day_range() -> None:
    entry = parse_manual_entry("21.9. 9 Uhr bis 18 Uhr", TODAY)
    assert entry is not None
    assert entry.hours is None
    assert entry.start == datetime(2026, 9, 21, 9, 0)
    assert entry.end == datetime(2026, 9, 21, 18, 0)


def test_parse_overnight_implicit_next_day() -> None:
    entry = parse_manual_entry("21. September 7 Uhr bis 1 Uhr 30", TODAY)
    assert entry is not None
    assert entry.start == datetime(2026, 9, 21, 7, 0)
    assert entry.end == datetime(2026, 9, 22, 1, 30)


def test_parse_overnight_explicit_end_date() -> None:
    entry = parse_manual_entry("21.9. 7 Uhr bis 22.9. 1:30", TODAY)
    assert entry is not None
    assert entry.start == datetime(2026, 9, 21, 7, 0)
    assert entry.end == datetime(2026, 9, 22, 1, 30)


def test_parse_year_wrap_implicit() -> None:
    entry = parse_manual_entry("31.12. 22 Uhr bis 2 Uhr", TODAY)
    assert entry is not None
    assert entry.start == datetime(2026, 12, 31, 22, 0)
    assert entry.end == datetime(2027, 1, 1, 2, 0)


@pytest.mark.parametrize(
    "raw, start, end",
    [
        ("21.9. 8,5", None, None),
        ("21.9. 9:00 bis 18:00", datetime(2026, 9, 21, 9, 0), datetime(2026, 9, 21, 18, 0)),
        ("21.9. 9-18", datetime(2026, 9, 21, 9, 0), datetime(2026, 9, 21, 18, 0)),
        (
            "21. September 7 Uhr bis 22. September 1:30",
            datetime(2026, 9, 21, 7, 0),
            datetime(2026, 9, 22, 1, 30),
        ),
        ("21.9. 22 Uhr bis 6 Uhr", datetime(2026, 9, 21, 22, 0), datetime(2026, 9, 22, 6, 0)),
        (
            "31.12. 22 Uhr bis 1.1. 2 Uhr",
            datetime(2026, 12, 31, 22, 0),
            datetime(2027, 1, 1, 2, 0),
        ),
    ],
)
def test_parse_additional_manual_examples(
    raw: str,
    start: datetime | None,
    end: datetime | None,
) -> None:
    entry = parse_manual_entry(raw, TODAY)
    assert entry is not None
    assert entry.day.month == (12 if raw.startswith("31.12") else 9)
    assert entry.start == start
    assert entry.end == end
    if start is None:
        assert entry.hours == 8.5


def test_workday_manual_hours() -> None:
    day = WorkDay(date="2026-09-21", manual_hours=8.5)
    assert day.rounded_hours() == 8.5
    assert format_hours(day.rounded_hours()) == "8,5"
    assert day.work_minutes() == 8.5 * 60


def test_try_manual_range_hours_and_overwrite(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    first = tracker.try_manual("21.9. 8,5 Stunden", now=NOW)
    assert first is not None
    assert "21.09.2026: 8,5 Stunden eingetragen" in first
    day = tracker.state.days["2026-09-21"]
    assert day.manual_hours == 8.5
    assert day.work_start is None
    assert day.work_end is None
    assert day.pauses == []

    same_day = tracker.try_manual("21.9. 9 Uhr bis 18 Uhr", now=NOW)
    assert same_day is not None
    assert "Eintrag für 21.09.2026 ersetzt" in same_day
    day = tracker.state.days["2026-09-21"]
    assert day.rounded_hours() == 9
    assert day.work_start == "2026-09-21T09:00:00"
    assert day.work_end == "2026-09-21T18:00:00"
    assert day.manual_hours is None

    overnight = tracker.try_manual("21. September 7 Uhr bis 1 Uhr 30", now=NOW)
    assert overnight is not None
    day = tracker.state.days["2026-09-21"]
    assert day.work_end == "2026-09-22T01:30:00"
    assert day.rounded_hours() == 18.5


def test_invalid_calendar_date_raises() -> None:
    with pytest.raises(ParseError):
        parse_manual_entry("31.9.", TODAY)
    with pytest.raises(ParseError):
        parse_manual_entry("31.9. 8", TODAY)


def test_format_end_time_marks_next_day() -> None:
    start = datetime(2026, 9, 21, 7, 0)
    same_day = datetime(2026, 9, 21, 18, 0)
    next_day = datetime(2026, 9, 22, 1, 30)
    assert format_end_time(start, same_day) == "18:00"
    assert format_end_time(start, next_day) == "01:30 (+1)"


def test_live_stop_after_midnight(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    assert "gestartet" in tracker.start(now=datetime(2026, 9, 21, 7, 0, 0))
    message = tracker.stop(now=datetime(2026, 9, 22, 1, 30, 0))
    assert "01:30" in message
    day = tracker.state.days["2026-09-21"]
    assert day.work_start == "2026-09-21T07:00:00"
    assert day.work_end == "2026-09-22T01:30:00"
    assert day.rounded_hours() == 18.5


@pytest.mark.parametrize(
    "raw",
    ["s 7", "start 7", "s 7 Uhr", "start 7:00", "s um 7 Uhr", "start um 7.00"],
)
def test_parse_start_clock(raw: str) -> None:
    assert parse_start_clock(raw) == time(7, 0)


def test_start_with_earlier_clock(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    now = datetime(2026, 9, 22, 8, 11, 0)
    message = tracker.handle("s 7 Uhr", now=now)
    assert "07:00" in message
    assert tracker.state.current is not None
    assert tracker.state.current.work_start == "2026-09-22T07:00:00"
    tracker.stop(now=now)
    day = tracker.state.days["2026-09-22"]
    assert day.rounded_hours() == 1.25


def test_start_rejects_future_clock(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    message = tracker.handle("start 9 Uhr", now=datetime(2026, 9, 22, 8, 11, 0))
    assert "Zukunft" in message
    assert tracker.state.current is None


def test_handle_accepts_full_words_and_stop_updates_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "out.pdf"
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=pdf_path)
    started = datetime(2026, 9, 22, 7, 0, 0)
    assert "gestartet" in tracker.handle("start", now=started)
    assert "Pause gestartet" in tracker.handle("pause", now=started + timedelta(hours=3))
    assert "Pause beendet" in tracker.handle("pause stop", now=started + timedelta(hours=3, minutes=30))
    assert not pdf_path.exists()
    message = tracker.handle("STOP", now=started + timedelta(hours=8))
    assert "PDF aktualisiert" in message
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert tracker.state.current is None
    assert tracker.state.days["2026-09-22"].rounded_hours() == 7.5


def test_handle_stopp_also_updates_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "out.pdf"
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=pdf_path)
    tracker.handle("Start", now=datetime(2026, 9, 22, 9, 0, 0))
    message = tracker.handle("stopp", now=datetime(2026, 9, 22, 17, 0, 0))
    assert "PDF aktualisiert" in message
    assert pdf_path.exists()


class FakeReminderUI(ReminderUI):
    def __init__(
        self,
        result: str = "dismiss",
        still: str | list[str] = "ja",
        duration_ok: str = "ja",
        until: str | None = None,
    ) -> None:
        self.result = result
        self.still = still
        self.duration_ok = duration_ok
        self.until = until
        self.calls = 0
        self.pause_calls = 0
        self.last_timeout: int | None = None

    def alert(self, timeout: int) -> str:
        self.calls += 1
        self.last_timeout = timeout
        return self.result

    def pause_still_away(self, timeout: int) -> str:
        self.pause_calls += 1
        self.last_timeout = timeout
        if isinstance(self.still, list):
            return self.still.pop(0)
        return self.still

    def pause_duration_ok(self, duration_label: str, timeout: int) -> str:
        self.last_timeout = timeout
        return self.duration_ok

    def pause_end_time(self, timeout: int) -> str | None:
        self.last_timeout = timeout
        return self.until


def test_reminder_window_from_seventeen() -> None:
    start = datetime(2026, 9, 22, 7, 0, 0)
    assert reminder_window_open(datetime(2026, 9, 22, 16, 59, 0), start) is False
    assert reminder_window_open(datetime(2026, 9, 22, 17, 0, 0), start) is True
    assert reminder_window_open(datetime(2026, 9, 23, 0, 30, 0), start) is True


def test_reminder_dismiss_keeps_day_running(tmp_path: Path) -> None:
    ui = FakeReminderUI("dismiss")
    tracker = Tracker(
        json_path=tmp_path / "hours.json",
        pdf_path=tmp_path / "out.pdf",
        reminder_ui=ui,
    )
    tracker.start(now=datetime(2026, 9, 22, 7, 0, 0))
    assert tracker.process_reminder(now=datetime(2026, 9, 22, 16, 59, 0)) is None
    assert ui.calls == 0
    message = tracker.process_reminder(now=datetime(2026, 9, 22, 17, 0, 0))
    assert message is not None
    assert ui.last_timeout == REMINDER_TIMEOUT_SECONDS == 300
    assert "Arbeit läuft weiter" in message
    assert "18:00" in message
    assert tracker.state.current is not None
    assert tracker.process_reminder(now=datetime(2026, 9, 22, 17, 30, 0)) is None
    assert ui.calls == 1
    later = tracker.process_reminder(now=datetime(2026, 9, 22, 18, 0, 0))
    assert later is not None
    assert "19:00" in later
    assert ui.calls == 2
    assert tracker.state.current is not None


def test_reminder_timeout_auto_stops_and_writes_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "out.pdf"
    ui = FakeReminderUI("timeout")
    tracker = Tracker(
        json_path=tmp_path / "hours.json",
        pdf_path=pdf_path,
        reminder_ui=ui,
    )
    tracker.start(now=datetime(2026, 9, 22, 7, 0, 0))
    message = tracker.process_reminder(now=datetime(2026, 9, 22, 17, 0, 0))
    assert message is not None
    assert "nicht bestätigt" in message
    assert "PDF aktualisiert" in message
    assert tracker.state.current is None
    assert pdf_path.exists()
    day = tracker.state.days["2026-09-22"]
    assert day.work_end == "2026-09-22T17:00:00"
    assert day.rounded_hours() == 10


def test_closing_alarm_is_not_clocking_out(tmp_path: Path) -> None:
    ui = FakeReminderUI("dismiss")
    tracker = Tracker(
        json_path=tmp_path / "hours.json",
        pdf_path=tmp_path / "out.pdf",
        reminder_ui=ui,
    )
    tracker.start(now=datetime(2026, 9, 22, 7, 0, 0))
    tracker.process_reminder(now=datetime(2026, 9, 22, 17, 0, 0))
    tracker.process_reminder(now=datetime(2026, 9, 22, 18, 0, 0))
    tracker.process_reminder(now=datetime(2026, 9, 22, 19, 0, 0))
    assert ui.calls == 3
    assert tracker.state.current is not None
    assert tracker.state.current.work_end is None


def test_parse_edit_hours_and_end_clock() -> None:
    hours = parse_edit_entry("21.09. edit 8", TODAY)
    assert hours is not None
    assert hours.day == date(2026, 9, 21)
    assert hours.hours == 8
    assert hours.end is None

    clock = parse_edit_entry("21.09. edit 17:30", TODAY)
    assert clock is not None
    assert clock.hours is None
    assert clock.end == time(17, 30)

    named = parse_edit_entry("21. September edit 17 Uhr 30", TODAY)
    assert named is not None
    assert named.end == time(17, 30)

    assert parse_edit_entry("21.9. 8,5", TODAY) is None


def test_edit_hours_keeps_start_and_moves_end(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.handle("21.9. 7 Uhr bis 18:30", now=NOW)
    message = tracker.handle("21.09. edit 8", now=NOW)
    assert "8 Stunden" in message
    day = tracker.state.days["2026-09-21"]
    assert day.work_start == "2026-09-21T07:00:00"
    assert day.work_end == "2026-09-21T15:00:00"
    assert day.rounded_hours() == 8


def test_edit_end_time_recalculates_hours(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.handle("21.9. 7 Uhr bis 18:30", now=NOW)
    message = tracker.handle("21.09. edit 17:30", now=NOW)
    assert "17:30" in message
    day = tracker.state.days["2026-09-21"]
    assert day.work_end == "2026-09-21T17:30:00"
    assert day.rounded_hours() == 10.5


def test_edit_hours_keeps_pause_and_closes_open_day(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.start(now=datetime(2026, 9, 21, 7, 0, 0))
    tracker.pause(now=datetime(2026, 9, 21, 12, 0, 0))
    tracker.pausestop(now=datetime(2026, 9, 21, 12, 30, 0))
    message = tracker.handle("21.09. edit 8", now=NOW)
    assert tracker.state.current is None
    day = tracker.state.days["2026-09-21"]
    assert day.total_pause_minutes() == 30
    assert day.work_end == "2026-09-21T15:30:00"
    assert day.rounded_hours() == 8
    assert "PDF aktualisiert" in message


def test_edit_missing_day(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    message = tracker.handle("21.09. edit 8", now=NOW)
    assert "Kein Eintrag" in message


def test_format_duration_de() -> None:
    assert format_duration_de(45) == "45 Minuten"
    assert format_duration_de(60) == "1 Stunde"
    assert format_duration_de(70) == "1 Stunde und 10 Minuten"
    assert format_duration_de(80) == "1 Stunde und 20 Minuten"


def test_pause_reminder_yes_repeats_after_ten_minutes(tmp_path: Path) -> None:
    ui = FakeReminderUI(still=["ja", "ja"])
    tracker = Tracker(
        json_path=tmp_path / "hours.json",
        pdf_path=tmp_path / "out.pdf",
        reminder_ui=ui,
    )
    tracker.start(now=datetime(2026, 9, 22, 7, 0, 0))
    tracker.pause(now=datetime(2026, 9, 22, 12, 0, 0))
    assert tracker.process_pause_reminder(now=datetime(2026, 9, 22, 13, 9, 0)) is None
    first = tracker.process_pause_reminder(now=datetime(2026, 9, 22, 13, 10, 0))
    assert first is not None
    assert "10 Minuten" in first
    assert tracker.state.current is not None
    assert tracker.state.current.open_pause() is not None
    assert tracker.process_pause_reminder(now=datetime(2026, 9, 22, 13, 15, 0)) is None
    second = tracker.process_pause_reminder(now=datetime(2026, 9, 22, 13, 20, 0))
    assert second is not None
    assert ui.pause_calls == 2


def test_pause_reminder_confirms_elapsed_duration(tmp_path: Path) -> None:
    ui = FakeReminderUI(still="nein", duration_ok="ja")
    tracker = Tracker(
        json_path=tmp_path / "hours.json",
        pdf_path=tmp_path / "out.pdf",
        reminder_ui=ui,
    )
    tracker.start(now=datetime(2026, 9, 22, 7, 0, 0))
    tracker.pause(now=datetime(2026, 9, 22, 12, 0, 0))
    message = tracker.process_pause_reminder(now=datetime(2026, 9, 22, 13, 10, 0))
    assert message is not None
    assert "1 Stunde und 10 Minuten" in message
    pause = tracker.state.current.pauses[-1]
    assert pause.end == "2026-09-22T13:10:00"
    assert pause.minutes() == PAUSE_REMINDER_MINUTES
    assert tracker.state.current.open_pause() is None


def test_pause_reminder_custom_end_time(tmp_path: Path) -> None:
    ui = FakeReminderUI(still="nein", duration_ok="nein", until="12:45")
    tracker = Tracker(
        json_path=tmp_path / "hours.json",
        pdf_path=tmp_path / "out.pdf",
        reminder_ui=ui,
    )
    tracker.start(now=datetime(2026, 9, 22, 7, 0, 0))
    tracker.pause(now=datetime(2026, 9, 22, 12, 0, 0))
    message = tracker.process_pause_reminder(now=datetime(2026, 9, 22, 13, 10, 0))
    assert "12:45" in message
    pause = tracker.state.current.pauses[-1]
    assert pause.end == "2026-09-22T12:45:00"
    assert pause.minutes() == 45
    assert tracker.state.current.open_pause() is None


def test_pausestop_with_clock(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.start(now=datetime(2026, 9, 22, 7, 0, 0))
    tracker.pause(now=datetime(2026, 9, 22, 12, 0, 0))
    message = tracker.handle("ps 12:45", now=datetime(2026, 9, 22, 13, 10, 0))
    assert "12:45" in message
    assert tracker.state.current.pauses[-1].minutes() == 45


def test_edit_last_pause_minutes(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.handle("21.9. 7 Uhr bis 18:00", now=NOW)
    day = tracker.state.days["2026-09-21"]
    day.pauses.append(
        Pause(start="2026-09-21T12:00:00", end="2026-09-21T13:10:00")
    )
    tracker.state.days["2026-09-21"] = day
    message = tracker.handle("21.09. edit pause 45", now=NOW)
    assert "45 Min." in message
    assert tracker.state.days["2026-09-21"].pauses[-1].minutes() == 45
    assert tracker.state.days["2026-09-21"].rounded_hours() == 10.25
