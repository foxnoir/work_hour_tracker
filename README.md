<a name="readme-top"></a>

<!-- Top Links Bar -->

[![LinkedIn](assets/badges/linkedin.svg)](https://www.linkedin.com/in/tanja-polz-5636401a5/)
[![X](assets/badges/x.svg)](https://twitter.com/_foxnoir_?lang=de)
[![Instagram](assets/badges/instagram.svg)](https://www.instagram.com/codeincouture/)

<!-- PROJECT LOGO -->
<br />

<div align="center">
  <img src="assets/logo.png" alt="Logo" width="179" height="179">
  <h1 align="center">Work Hour Tracker</h1>
  <p>
     Interactive CLI to track workdays, pauses, and monthly PDF summaries.
  </p>
</div>

---

<div align="left">

[![Python](assets/badges/python.svg)](https://www.python.org/)
[![ReportLab](assets/badges/reportlab.svg)](https://www.reportlab.com/)
[![pytest](assets/badges/pytest.svg)](https://docs.pytest.org/)

</div>

<details>
  <summary>Table of Contents</summary>
  <ol>
    <li><a href="#about-this-project">About this project</a></li>
    <li><a href="#getting-started">Getting started</a></li>
    <li><a href="#commands">Commands</a></li>
    <li><a href="#manual-entries">Manual entries</a></li>
    <li><a href="#edit-a-day">Edit a day</a></li>
    <li><a href="#checkout-reminder">Checkout reminder</a></li>
    <li><a href="#pause-reminder">Pause reminder</a></li>
    <li><a href="#hours">Hours</a></li>
    <li><a href="#pdf">PDF</a></li>
    <li><a href="#badges">Badges</a></li>
  </ol>
</details>

---

## About this project

A personal CLI for my own timesheets. Start a day, pause as often as needed, finish, and get a monthly PDF. Forgotten starts, leftover days, and long pauses can be corrected. From 17:00 and after a long pause the tracker pings on macOS so I do not forget to clock back in.

That is a conscious choice: it should please me first, not necessarily meet every timesheet standard.

Live state sits in `data/hours.json` (gitignored). Completing or correcting a day regenerates `data/Arbeitszeiten.pdf`.

<p align="right"><a href="#readme-top">back to top</a></p>

---

## Getting started

Requires **Python 3.10** or newer.

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 tracker.py
```

Leave the process running if you want the 17:00 and pause reminders. `quit` keeps an open day in the JSON file but stops the alarms.

<p align="right"><a href="#readme-top">back to top</a></p>

---

## Commands

Type one of the inputs in **Command**. Uppercase and lowercase are the same.

| Command | Meaning | Example |
| --- | --- | --- |
| `start` / `s` | Start the workday at the current time | `start` |
| `start` + time / `s` + time | Start at an earlier time today (forgot to punch in). Future clocks are rejected. | `s 7 Uhr` |
| `pause` / `p` | Start a pause | `pause` |
| `pausestop` / `pause stop` / `pause-stop` / `ps` | End the open pause now. Only full minutes count. | `ps` |
| `pausestop` + time / `ps` + time | End the open pause at that clock | `ps 13:15` |
| `stop` / `stopp` / `finished` / `fertig` / `ende` / `f` | End the workday and refresh the PDF | `stop` |
| `status` | Show the open day | `status` |
| `pdf` | Rebuild the PDF from every saved day | `pdf` |
| `abbruch` / `cancel` | Discard the open day. Nothing is written to the PDF. | `abbruch` |
| `help` / `h` / `?` | Show help | `help` |
| `quit` / `q` / `exit` | Leave the program. An open day stays in the JSON file. Reminders stop. | `quit` |

Every command is saved immediately. A crash or a closed terminal does not lose an open day.

A leftover open day from a **previous date** blocks `start`. Finish it with `stop`, discard it with `abbruch`, or correct it with `edit`.

If a pause is still open at `stop`, it is closed automatically.

<p align="right"><a href="#readme-top">back to top</a></p>

---

## Manual entries

No extra command word. Date first, then hours or a time range. Year defaults to the current year. A finished day is replaced. An open live day cannot be overwritten this way — use `stop`, `abbruch`, or `edit`. The PDF updates immediately.

| Command | Meaning | Example |
| --- | --- | --- |
| date + hours | Fill only **Stunden**. Start, pause, and end stay empty. | `21.9. 8,5` |
| date + range | Set start and end, then calculate hours. | `21.9. 9 Uhr bis 18 Uhr` |
| date + range past midnight | Same row as the start date. End is shown as `01:30 (+1)`. | `21. September 7 Uhr bis 1 Uhr 30` |

Same date, other spellings: `21.9.`, `21.09.`, `21. Sept`, `21. September`, `21.9.2026`, `21.9.26`. Same range, other spellings: `9:00 bis 18:00`, `9-18`, `7 Uhr bis 22.9. 1:30`.

<p align="right"><a href="#readme-top">back to top</a></p>

---

## Edit a day

Correct a saved or leftover day. Start stays. The PDF updates immediately. `edit` / `editiere` / `korrigiere` are the same word.

| Command | Meaning | Example |
| --- | --- | --- |
| date + `edit` + hours | Set **Stunden**. Move **Arbeit beendet** so the math fits. Pauses stay. | `21.09. edit 8` |
| date + `edit` + clock | Set **Arbeit beendet**. Recalculate **Stunden**. Pauses stay. | `21.09. edit 17:30` |
| date + `edit pause` + minutes | Change the last pause to that length. | `21.09. edit pause 45` |
| date + `edit pause` + clock | End the last pause at that clock. | `21.09. edit pause 13:15` |

Hours-only rows (no start saved) can change hours, not an end clock.

<p align="right"><a href="#readme-top">back to top</a></p>

---

## Checkout reminder

While a live day is running and you are **not** on pause, from **17:00** the tracker pings and opens a macOS notification plus a dialog: *Nicht vergessen, dich auszustempeln.*

Closing the alarm is **not** clocking out. You stay punched in. The same reminder comes back on the next full hour (18:00, 19:00, … and after midnight if you are still clocked in).

- **OK** or close the dialog — work continues. Ask again in one hour.
- Ignore it for **five minutes** — then the day is stopped at the **alarm time** (17:00, not 17:05), because you were already away. The PDF is updated.
- While the dialog is open it pings three times, then again every 30 seconds.
- `quit` — leave the program; reminders stop because the process is gone. An open day stays saved.

macOS may ask once for notification permission for `osascript`. The dialog still works without that.

<p align="right"><a href="#readme-top">back to top</a></p>

---

## Pause reminder

If a pause stays open for **1 hour 10 minutes**, you get pings, a notification, and a dialog: *Bist du noch in Pause?*

- **Ja** (or ignore for five minutes) — stay on pause. The same question comes back in **10 minutes**.
- **Nein** — next dialog: *1 Stunde und 10 Minuten Pause — ist das korrekt?*
  - **Ja** — pause ends at that duration (the alarm time, not later). You are working again.
  - **Nein** — type when the pause actually ended (e.g. `12:45` after 45 minutes). The pause length is corrected; work continues.

Checkout-at-17 reminders wait while you are on pause. Same five-minute dialog window and 30-second pings as the checkout alarm.

<p align="right"><a href="#readme-top">back to top</a></p>

---

## Hours

- Work minutes = time from start to finish minus every pause
- Pauses count full minutes only (`5:59` → 5 minutes)
- Hours round to the nearest quarter (15 min. = 0.25; 30 = 0.5; 45 = 0.75)
- Display uses a German comma: `8,5` / `8,25` / `8`
- An end after midnight is shown as `01:30 (+1)` on the start date

<p align="right"><a href="#readme-top">back to top</a></p>

---

## PDF

File: `data/Arbeitszeiten.pdf`

- One page per month that has data (without data: the current month)
- Title, e.g. `Arbeitszeitenüberblick September 2026`
- Table of every day in that month
- Columns: Tag, Arbeit gestartet, Pause gestartet (several pauses stacked, e.g. `10:15–10:30`), Arbeit beendet, Pause gesamt, Stunden
- Footer: `Monat Gesamtstunden: …`
- Weekends slightly gray, dark header, portrait A4

The PDF is rebuilt from **all** completed days on `stop` / `fertig`, on a manual entry, on `edit`, and when the 17:00 reminder clocks you out. `pdf` rebuilds it without ending the day.

Before a PDF is replaced, the tracker checks for an existing file. The previous PDF and `hours.json` are copied to `data/backups/` (timestamped, last 30 kept). If `hours.json` is missing, empty, or broken after a pull, the newest hours backup is loaded instead. An existing PDF is never overwritten with an empty calendar.

<p align="right"><a href="#readme-top">back to top</a></p>

---

## Badges

Tech-stack and social badges live once in [`assets/badges/`](assets/badges/). After changing labels or colors:

```
python3 assets/badges/generate.py
```

Target URLs sit **on the badge line** (`[![Python](assets/badges/python.svg)](https://www.python.org/)`). GitHub cannot import another file into a README, so there is no footer of `[python-url]:` refs. The href list is [`assets/badges/links.json`](assets/badges/links.json) when you add a badge.

Every badge is a vertical dark → mid → light gradient (same contrast as Instagram). The mid stop is the brand or playground color. Official colors stay official, except black — it is hard to see. Everything else uses purple, blue, turquoise, pink, or green — not black, orange, red, or yellow.

| File | Color (dark → mid → light) | Why |
| --- | --- | --- |
| `python.svg` | `#1E415E` → `#3776AB` → `#97B8D3` | official Python |
| `reportlab.svg` | `#194C4A` → `#2D8A86` → `#92C2C0` | teal |
| `pytest.svg` | `#294D3D` → `#4A8C6F` → `#A1C3B4` | green (replaces yellow) |
| `linkedin.svg` | `#06386B` → `#0A66C2` → `#80AFDF` | official LinkedIn |
| `instagram.svg` | `#4C3469` → `#8B5FBF` → `#C3ACDE` | lilac |
| `x.svg` | `#456576` → `#7EB8D6` → `#BCDAEA` | pastel light blue |

<p align="right"><a href="#readme-top">back to top</a></p>
