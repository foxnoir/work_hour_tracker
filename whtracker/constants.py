"""Pfade, Texte und feste Tracker-Werte."""

from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
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

EMPLOYMENT_START = date(2026, 9, 21)
DAILY_TARGET_HOURS = 8.0
ABSENCE_KINDS = {"urlaub": "Urlaub", "krank": "Krank"}
ABSENCE_ALIASES = {"urlaub": "urlaub", "u": "urlaub", "krank": "krank", "k": "krank"}

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
                           am selben Tag nach stop: Vormittag bleibt, weiterzählen
  start 7, s 7 Uhr         Nachträglich um 7:00 starten
                           auch: start 7:00, s um 7 Uhr
  pause, p                 Pause starten
  pausestop, ps            Pause beenden (volle Minuten)
                           auch: pause stop, pause-stop
  ps 13:15                 Pause nachträglich um 13:15 beenden
  + pause 10, + p 13       Extra-Pause in Minuten abziehen
                           auch: + Pause 20, 21.09. + pause 10
  + St. 8:00, + s 8        Startuhrzeit ändern
                           auch: + start 8 Uhr, 21.09. + St. 7:30
  + F 17:30, + f 17        Enduhrzeit ändern
                           auch: + fertig 17 Uhr, 21.09. + F 16:00

Urlaub (u, U, urlaub) und Krank (k, K, krank), Einheit immer Tage:
  + urlaub 2, + k 2        pauschal vom Soll abziehen (aktueller Monat)
  + u 2 september          pauschal für einen bestimmten Monat
  - urlaub 1, - k          pauschal wieder abziehen / ganz löschen
  24.09. k, 24.09. krank   genau dieser Tag (Zeile im PDF rot/grün)
  24.09. u 0,5             halber Tag
  25.09. bis 28.09. u      Zeitraum, nur Arbeitstage zählen (auch 25.9.-28.9. u)
  24.09. - k               Eintrag für den Tag entfernen
  stop, stopp, f, fertig   Arbeitstag beenden und PDF aktualisieren
                           auch: finished, ende
  status                   Aktuellen Tag anzeigen
  stunden                  Stunden heute bisher
  stunden monat            Stunden im aktuellen Monat bisher
                           (jeweils mit Sollstunden)
  stunden september        Stunden eines Monats
                           auch: monat, monat 9, stunden 09.2026
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
