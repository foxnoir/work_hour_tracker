"""Monats-PDF erzeugen."""

from __future__ import annotations

import calendar
from datetime import date
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

from .constants import MONTHS_DE, WEEKDAYS_DE
from .format import format_end_time, format_hours, format_time
from .models import WorkDay

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
                pause_bits = [pause.range_label() for pause in work_day.pauses]
                if work_day.extra_pause_minutes:
                    pause_bits.append(f"manuell {work_day.extra_pause_minutes} Min.")
                if pause_bits:
                    pauses_html = "<br/>".join(pause_bits)
                if work_day.total_pause_minutes():
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
