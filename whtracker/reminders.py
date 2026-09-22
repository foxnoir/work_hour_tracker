"""Checkout- und Pause-Hinweise (macOS)."""

from __future__ import annotations

import re
import subprocess
import threading
from datetime import date, datetime, time, timedelta

from .constants import (
    PAUSE_REMINDER_TEXT,
    PING_COUNT,
    PING_REPEAT_SECONDS,
    PING_SOUND,
    REMINDER_HOUR,
    REMINDER_TEXT,
    REMINDER_TITLE,
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
