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
    backup_existing,
    format_duration_de,
    format_end_time,
    generate_pdf,
    load_hours_payload,
    REMINDER_TIMEOUT_SECONDS,
    format_hours,
    normalize_command,
    parse_add_pause_entry,
    parse_clock_adjust_entry,
    parse_hours_query,
    parse_edit_entry,
    parse_manual_entry,
    parse_start_clock,
    parse_absence_entry,
    pause_full_minutes,
    reminder_window_open,
    round_to_quarter_hours,
    berlin_holidays,
    target_breakdown,
    target_hours,
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


def test_parse_add_pause_entry() -> None:
    today = parse_add_pause_entry("+ pause 10", TODAY)
    assert today is not None
    assert today.minutes == 10
    assert today.day is None

    plus_p = parse_add_pause_entry("+ p 13", TODAY)
    assert plus_p is not None
    assert plus_p.minutes == 13

    titled = parse_add_pause_entry("+ Pause 20 min", TODAY)
    assert titled is not None
    assert titled.minutes == 20

    dated = parse_add_pause_entry("21.09. + pause 10", TODAY)
    assert dated is not None
    assert dated.minutes == 10
    assert dated.day == date(2026, 9, 21)

    assert parse_add_pause_entry("+ start 10", TODAY) is None
    with pytest.raises(ParseError, match="Minuten"):
        parse_add_pause_entry("+ pause", TODAY)


def test_add_pause_subtracts_from_finished_day(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.start(now=datetime(2026, 9, 22, 8, 0, 0))
    tracker.stop(now=datetime(2026, 9, 22, 16, 0, 0))
    message = tracker.handle("+ pause 13", now=datetime(2026, 9, 22, 16, 5, 0))
    day = tracker.state.days["2026-09-22"]
    assert "13 Min. Extra-Pause" in message
    assert "Pause gesamt 13 Min." in message
    assert day.extra_pause_minutes == 13
    assert day.total_pause_minutes() == 13
    assert day.rounded_hours() == 7.75
    assert (tmp_path / "out.pdf").exists()


def test_add_pause_aliases_and_date(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.handle("21.9. 8 Uhr bis 16 Uhr", now=NOW)
    missing = tracker.handle("+ p 10", now=NOW)
    assert "Kein Eintrag für heute" in missing
    message = tracker.handle("21.09. + Pause 20", now=NOW)
    day = tracker.state.days["2026-09-21"]
    assert "20 Min. Extra-Pause" in message
    assert day.extra_pause_minutes == 20
    assert day.rounded_hours() == 7.75


def test_add_pause_accumulates_and_hours_only(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.handle("21.9. 8,5", now=NOW)
    tracker.handle("21.09. + pause 10", now=NOW)
    tracker.handle("21.09. + p 20", now=NOW)
    day = tracker.state.days["2026-09-21"]
    assert day.extra_pause_minutes == 30
    assert day.total_pause_minutes() == 30
    assert day.rounded_hours() == 8.0


def test_add_pause_on_open_day_then_stop(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.start(now=datetime(2026, 9, 22, 8, 0, 0))
    message = tracker.handle("+ pause 15", now=datetime(2026, 9, 22, 15, 50, 0))
    assert "PDF" not in message
    assert tracker.state.current is not None
    assert tracker.state.current.extra_pause_minutes == 15
    tracker.stop(now=datetime(2026, 9, 22, 16, 0, 0))
    day = tracker.state.days["2026-09-22"]
    assert day.extra_pause_minutes == 15
    assert day.rounded_hours() == 7.75


def test_parse_clock_adjust_entry() -> None:
    start = parse_clock_adjust_entry("+ St. 8:00", TODAY)
    assert start is not None
    assert start.field == "start"
    assert start.clock == time(8, 0)
    assert start.day is None

    short = parse_clock_adjust_entry("+ s 7 Uhr", TODAY)
    assert short is not None
    assert short.clock == time(7, 0)

    end = parse_clock_adjust_entry("+ F 17:30", TODAY)
    assert end is not None
    assert end.field == "end"
    assert end.clock == time(17, 30)

    dated = parse_clock_adjust_entry("21.09. + f 16", TODAY)
    assert dated is not None
    assert dated.field == "end"
    assert dated.clock == time(16, 0)
    assert dated.day == date(2026, 9, 21)

    assert parse_clock_adjust_entry("+ pause 10", TODAY) is None
    with pytest.raises(ParseError, match="Uhrzeit"):
        parse_clock_adjust_entry("+ St.", TODAY)
    with pytest.raises(ParseError, match="Uhrzeit"):
        parse_clock_adjust_entry("+ F", TODAY)


def test_plus_start_changes_start_clock(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.start(now=datetime(2026, 9, 22, 8, 0, 0))
    tracker.stop(now=datetime(2026, 9, 22, 16, 0, 0))
    message = tracker.handle("+ St. 7:00", now=datetime(2026, 9, 22, 16, 10, 0))
    day = tracker.state.days["2026-09-22"]
    assert "Start auf 07:00" in message
    assert day.work_start == "2026-09-22T07:00:00"
    assert day.work_end == "2026-09-22T16:00:00"
    assert day.rounded_hours() == 9


def test_plus_f_changes_end_clock(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.handle("21.9. 8 Uhr bis 16 Uhr", now=NOW)
    message = tracker.handle("21.09. + F 17:30", now=NOW)
    day = tracker.state.days["2026-09-21"]
    assert "Ende auf 17:30" in message
    assert day.work_end == "2026-09-21T17:30:00"
    assert day.rounded_hours() == 9.5


def test_plus_f_finishes_open_day(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.start(now=datetime(2026, 9, 22, 8, 0, 0))
    message = tracker.handle("+ f 15:00", now=datetime(2026, 9, 22, 16, 0, 0))
    assert tracker.state.current is None
    day = tracker.state.days["2026-09-22"]
    assert "Ende auf 15:00" in message
    assert day.work_end == "2026-09-22T15:00:00"
    assert day.rounded_hours() == 7


def test_plus_start_on_open_day_keeps_running(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.start(now=datetime(2026, 9, 22, 8, 0, 0))
    message = tracker.handle("+ St. 7:30", now=datetime(2026, 9, 22, 12, 0, 0))
    assert "PDF" not in message
    assert tracker.state.current is not None
    assert tracker.state.current.work_start == "2026-09-22T07:30:00"
    assert tracker.state.current.work_end is None


def test_plus_clock_rejects_future_and_start_after_end(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.start(now=datetime(2026, 9, 22, 8, 0, 0))
    future = tracker.handle("+ St. 13:00", now=datetime(2026, 9, 22, 12, 0, 0))
    assert "Zukunft" in future
    tracker.handle("21.9. 8 Uhr bis 16 Uhr", now=NOW)
    late = tracker.handle("21.09. + St. 17:00", now=NOW)
    assert "vor dem Ende" in late


def test_parse_hours_query() -> None:
    today = parse_hours_query("stunden", TODAY)
    assert today is not None
    assert today.kind == "day"

    assert parse_hours_query("stunden heute", TODAY).kind == "day"
    month = parse_hours_query("stunden monat", TODAY)
    assert month.kind == "month"
    assert month.year == 2026
    assert month.month == 9

    named = parse_hours_query("monat september", TODAY)
    assert named.year == 2026
    assert named.month == 9

    numbered = parse_hours_query("stunden 8", TODAY)
    assert numbered.month == 8
    assert numbered.year == 2026

    dated = parse_hours_query("stunden 09.2025", TODAY)
    assert dated.year == 2025
    assert dated.month == 9

    assert parse_hours_query("pause", TODAY) is None
    with pytest.raises(ParseError, match="Monat"):
        parse_hours_query("stunden xyz", TODAY)


def test_stunden_today_running_and_finished(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    empty = tracker.handle("stunden", now=NOW)
    assert "noch keine Stunden" in empty

    tracker.start(now=datetime(2026, 9, 22, 8, 0, 0))
    running = tracker.handle("stunden", now=datetime(2026, 9, 22, 12, 0, 0))
    assert "Heute bisher" in running
    assert "4 Stunden" in running
    status = tracker.status(now=datetime(2026, 9, 22, 12, 0, 0))
    assert "Stunden bisher: 4" in status

    tracker.pause(now=datetime(2026, 9, 22, 12, 0, 0))
    paused = tracker.handle("std", now=datetime(2026, 9, 22, 12, 30, 0))
    assert "4 Stunden" in paused

    tracker.pausestop(now=datetime(2026, 9, 22, 12, 30, 0))
    tracker.stop(now=datetime(2026, 9, 22, 16, 30, 0))
    finished = tracker.handle("hours today", now=datetime(2026, 9, 22, 18, 0, 0))
    assert "8 Stunden" in finished


def test_stunden_month_current_and_named(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.handle("21.9. 8", now=NOW)
    tracker.handle("1.8. 7,5", now=NOW)
    tracker.start(now=datetime(2026, 9, 22, 8, 0, 0))

    current = tracker.handle("monat", now=datetime(2026, 9, 22, 12, 0, 0))
    assert "September 2026 bisher" in current
    assert "12 Stunden" in current
    assert "2 Tage" in current

    august = tracker.handle("stunden august", now=NOW)
    assert "August 2026:" in august
    assert "bisher" not in august
    assert "7,5 Stunden" in august
    assert "1 Tag" in august

    numbered = tracker.handle("monat 8", now=NOW)
    assert "7,5 Stunden" in numbered

    empty = tracker.handle("stunden 03.2026", now=NOW)
    assert "März 2026" in empty
    assert "noch keine Stunden" in empty


def test_same_day_second_start_adds_hours(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.start(now=datetime(2026, 9, 22, 8, 0, 0))
    tracker.stop(now=datetime(2026, 9, 22, 12, 0, 0))
    morning = tracker.state.days["2026-09-22"]
    assert morning.rounded_hours() == 4

    message = tracker.start(now=datetime(2026, 9, 22, 13, 0, 0))
    assert "fortgesetzt" in message
    assert "4 Stunden" in message
    assert tracker.state.current is not None
    assert tracker.state.current.work_start == "2026-09-22T08:00:00"
    assert tracker.state.current.work_end is None
    assert tracker.state.days["2026-09-22"].rounded_hours() == 4

    tracker.stop(now=datetime(2026, 9, 22, 16, 0, 0))
    day = tracker.state.days["2026-09-22"]
    assert day.work_start == "2026-09-22T08:00:00"
    assert day.work_end == "2026-09-22T16:00:00"
    assert day.total_pause_minutes() == 60
    assert day.pauses[-1].start == "2026-09-22T12:00:00"
    assert day.pauses[-1].end == "2026-09-22T13:00:00"
    assert day.rounded_hours() == 7


def test_abbruch_after_resume_keeps_morning(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.start(now=datetime(2026, 9, 22, 8, 0, 0))
    tracker.stop(now=datetime(2026, 9, 22, 12, 0, 0))
    tracker.start(now=datetime(2026, 9, 22, 13, 0, 0))
    tracker.abbruch()
    day = tracker.state.days["2026-09-22"]
    assert tracker.state.current is None
    assert day.work_end == "2026-09-22T12:00:00"
    assert day.rounded_hours() == 4


def test_backup_existing_copies_file(tmp_path: Path) -> None:
    source = tmp_path / "Arbeitszeiten.pdf"
    source.write_bytes(b"old-pdf")
    dest = backup_existing(source)
    assert dest is not None
    assert dest.read_bytes() == b"old-pdf"
    assert dest.parent.name == "backups"


def test_generate_pdf_keeps_existing_when_days_empty(tmp_path: Path) -> None:
    pdf_path = tmp_path / "out.pdf"
    pdf_path.write_bytes(b"keep-me")
    result = generate_pdf({}, pdf_path)
    assert result == pdf_path
    assert pdf_path.read_bytes() == b"keep-me"


def test_write_pdf_backs_up_old_file(tmp_path: Path) -> None:
    pdf_path = tmp_path / "out.pdf"
    json_path = tmp_path / "hours.json"
    pdf_path.write_bytes(b"previous")
    tracker = Tracker(json_path=json_path, pdf_path=pdf_path)
    tracker.handle("21.9. 8,5", now=NOW)
    backups = list((tmp_path / "backups").glob("out-*.pdf"))
    assert backups
    assert any(item.read_bytes() == b"previous" for item in backups)
    assert pdf_path.stat().st_size > 0
    assert pdf_path.read_bytes() != b"previous"


def test_load_uses_backup_when_hours_json_is_empty(tmp_path: Path) -> None:
    json_path = tmp_path / "hours.json"
    tracker = Tracker(json_path=json_path, pdf_path=tmp_path / "out.pdf")
    tracker.handle("21.9. 8,5", now=NOW)
    backup_existing(json_path)
    json_path.write_text('{"current": null, "days": {}}', encoding="utf-8")
    restored = Tracker(json_path=json_path, pdf_path=tmp_path / "out.pdf")
    assert restored._hours_source == "backup"
    assert "2026-09-21" in restored.state.days
    assert restored.state.days["2026-09-21"].rounded_hours() == 8.5


def test_load_hours_payload_prefers_file_with_days(tmp_path: Path) -> None:
    json_path = tmp_path / "hours.json"
    json_path.write_text(
        '{"current": null, "days": {"2026-09-21": {"date": "2026-09-21", "work_start": null, "work_end": null, "pauses": [], "manual_hours": 8.5}}}',
        encoding="utf-8",
    )
    payload, source = load_hours_payload(json_path)
    assert source == "file"
    assert "2026-09-21" in payload["days"]


def test_berlin_holidays_2026() -> None:
    holidays = berlin_holidays(2026)
    assert holidays[date(2026, 4, 3)] == "Karfreitag"
    assert holidays[date(2026, 5, 25)] == "Pfingstmontag"
    assert holidays[date(2026, 3, 8)] == "Frauentag"
    assert holidays[date(2026, 12, 31)] == "Silvester"


def test_target_hours_start_in_september() -> None:
    # 21.–30.09.2026: 8 Arbeitstage à 8 Std.
    assert target_hours(2026, 9) == 64.0
    assert target_hours(2026, 8) == 0.0
    # Oktober 2026: 22 Werktage, 03.10. ist Samstag
    assert target_hours(2026, 10) == 22 * 8.0
    # Dezember 2026: 23 Werktage minus 24., 25., 31. (26. ist Samstag)
    assert target_hours(2026, 12) == 20 * 8.0


def test_target_breakdown_dated_and_lump() -> None:
    absences = {"urlaub": {"2026-09-25": 1.0, "2026-09-28": 1.0}, "krank": {"2026-09-24": 0.5}}
    totals = {"urlaub": {"2026-09": 2.0}}
    breakdown = target_breakdown(2026, 9, absences, totals)
    assert breakdown.base_hours == 64.0
    rows = [(item.name, item.days, item.dates) for item in breakdown.deductions]
    assert rows == [
        ("Feiertage", 0.0, []),
        ("Urlaub", 4.0, [date(2026, 9, 25), date(2026, 9, 28)]),
        ("Krank", 0.5, [date(2026, 9, 24)]),
    ]
    assert breakdown.target_days == 3.5
    assert breakdown.total == 64.0 - 16 - 16 - 4


def test_target_breakdown_lists_weekday_holidays() -> None:
    breakdown = target_breakdown(2026, 12)
    assert breakdown.weekdays == 23
    holidays = breakdown.deductions[0]
    assert holidays.name == "Feiertage"
    assert holidays.dates == [date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 31)]
    assert breakdown.total == 20 * 8.0


def test_parse_absence_entry_lump() -> None:
    lump = parse_absence_entry("+ urlaub 2", TODAY)
    assert lump is not None and lump.kind == "urlaub" and lump.days == 2.0
    assert (lump.year, lump.month) == (2026, 9) and lump.start is None
    sick = parse_absence_entry("+ K 0,5", TODAY)
    assert sick is not None and sick.kind == "krank" and sick.days == 0.5
    other_month = parse_absence_entry("+ krank 1 oktober", TODAY)
    assert other_month is not None and other_month.month == 10
    cleared = parse_absence_entry("- u", TODAY)
    assert cleared is not None and cleared.remove and cleared.days is None
    assert parse_absence_entry("+ pause 10", TODAY) is None
    with pytest.raises(ParseError, match="Anzahl"):
        parse_absence_entry("+ urlaub", TODAY)
    with pytest.raises(ParseError, match="halbe"):
        parse_absence_entry("+ u 0,3", TODAY)


def test_parse_absence_entry_dated() -> None:
    single = parse_absence_entry("24.09. K", TODAY)
    assert single is not None and single.kind == "krank"
    assert single.start == single.end == date(2026, 9, 24) and single.days == 1.0
    half = parse_absence_entry("24.9. urlaub 0,5", TODAY)
    assert half is not None and half.days == 0.5
    spanned = parse_absence_entry("25.09. bis 28.09. Urlaub", TODAY)
    assert spanned is not None
    assert (spanned.start, spanned.end) == (date(2026, 9, 25), date(2026, 9, 28))
    dashed = parse_absence_entry("25.9.-28.9. u", TODAY)
    assert dashed is not None and dashed.end == date(2026, 9, 28)
    removed = parse_absence_entry("24.09. - k", TODAY)
    assert removed is not None and removed.remove
    assert parse_absence_entry("21.9. 9-18", TODAY) is None
    assert parse_absence_entry("21.9. 8,5", TODAY) is None


def test_vacation_range_skips_weekend(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    message = tracker.handle("25.09. bis 28.09. urlaub", now=NOW)
    assert tracker.state.absences["urlaub"] == {"2026-09-25": 1.0, "2026-09-28": 1.0}
    assert "2 Arbeitstag(e)" in message
    assert "Soll September 2026: 48 Stunden." in message
    assert (tmp_path / "out.pdf").exists()

    reloaded = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    reloaded.load()
    assert reloaded.state.absences == tracker.state.absences

    tracker.handle("28.09. - u", now=NOW)
    assert tracker.state.absences["urlaub"] == {"2026-09-25": 1.0}


def test_sick_day_replaces_vacation_on_same_day(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.handle("24.09. u", now=NOW)
    tracker.handle("24.09. krank", now=NOW)
    assert tracker.state.absences["urlaub"] == {}
    assert tracker.state.absences["krank"] == {"2026-09-24": 1.0}


def test_lump_absence_accumulates_and_clears(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.handle("+ urlaub 1", now=NOW)
    message = tracker.handle("+ U 1", now=NOW)
    assert tracker.state.absence_totals["urlaub"] == {"2026-09": 2.0}
    assert "Soll September 2026: 48 Stunden." in message
    tracker.handle("+ k 2", now=NOW)
    assert tracker._target(2026, 9) == 32.0
    tracker.handle("- k 1", now=NOW)
    assert tracker.state.absence_totals["krank"] == {"2026-09": 1.0}
    tracker.handle("- urlaub", now=NOW)
    assert tracker.state.absence_totals["urlaub"] == {}


def test_absence_on_non_workday_is_rejected(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    assert "Heiligabend" in tracker.handle("24.12. urlaub", now=NOW)
    assert "Wochenende" in tracker.handle("26.09. k", now=NOW)
    assert "vor Arbeitsbeginn" in tracker.handle("18.09. k", now=NOW)
    assert not tracker.state.has_absences()


def test_month_hours_show_target(tmp_path: Path) -> None:
    tracker = Tracker(json_path=tmp_path / "hours.json", pdf_path=tmp_path / "out.pdf")
    tracker.handle("21.9. 7", now=NOW)
    message = tracker.handle("stunden september", now=NOW)
    assert "Soll: 64 Stunden, Differenz: -57." in message
