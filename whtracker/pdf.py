"""Monats-PDF erzeugen."""

from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .constants import ABSENCE_KINDS, EMPLOYMENT_START, MONTHS_DE, WEEKDAYS_DE
from .format import (
    format_end_time,
    format_hours,
    format_signed_hours,
    format_time,
    format_vacation_days,
)
from .models import WorkDay
from .workdays import TargetBreakdown, holiday_name, target_breakdown

WEEKEND_COLOR = colors.HexColor("#E8E8E8")
ABSENCE_COLORS = {
    "urlaub": colors.HexColor("#CDEBC5"),
    "krank": colors.HexColor("#F5C6C6"),
}
BEFORE_START_COLOR = colors.HexColor("#FFF1B8")
HOLIDAY_COLOR = colors.HexColor("#CFE2F7")
PAGE_MARGIN_X = 15 * mm
PAGE_MARGIN_TOP = 18 * mm
PAGE_MARGIN_BOTTOM = 14 * mm
PAGE_TEXT_COLOR = colors.HexColor("#555555")


class _MonthMarker(Flowable):
    """Unsichtbar: merkt sich den Monat für die Kopfzeile der Seite."""

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label
        self.width = self.height = 0

    def draw(self) -> None:
        self.canv._month_label = self.label


def _draw_page_header(canvas, document) -> None:
    label = getattr(canvas, "_month_label", "")
    page_width, page_height = document.pagesize
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(PAGE_TEXT_COLOR)
    canvas.setStrokeColor(colors.HexColor("#BBBBBB"))
    canvas.setLineWidth(0.4)
    header_y = page_height - 10 * mm
    canvas.drawRightString(page_width - PAGE_MARGIN_X, header_y, label)
    canvas.line(PAGE_MARGIN_X, header_y - 2 * mm, page_width - PAGE_MARGIN_X, header_y - 2 * mm)
    canvas.restoreState()

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
    absences: dict[str, dict[str, float]] | None = None,
    absence_totals: dict[str, dict[str, float]] | None = None,
) -> Path:
    today = today or date.today()
    absences = absences or {}
    absence_totals = absence_totals or {}
    has_absences = any(absences.values()) or any(absence_totals.values())
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if pdf_path.exists() and not days and not has_absences:
        return pdf_path

    months: set[tuple[int, int]] = set()
    dated_keys = [key for values in absences.values() for key in values]
    for key in [*days, *dated_keys]:
        day = date.fromisoformat(key)
        months.add((day.year, day.month))
    for values in absence_totals.values():
        for key in values:
            year_text, month_text = key.split("-")
            months.add((int(year_text), int(month_text)))
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

    footer_bold_style = ParagraphStyle(
        "pdf_footer_bold", parent=footer_style, fontName="Helvetica-Bold"
    )
    legend_style = ParagraphStyle(
        "pdf_legend", parent=footer_style, fontSize=7, leading=9
    )

    story: list = []
    page_width, _page_height = A4
    usable_width = page_width - 2 * PAGE_MARGIN_X
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
        "Pause(n)",
        "Arbeit beendet",
        "Pause gesamt",
        "Stunden",
    ]

    for index, (year, month) in enumerate(sorted(months)):
        if index > 0:
            story.append(PageBreak())
        month_label = f"{MONTHS_DE[month]} {year}"
        story.append(_MonthMarker(month_label))
        story.append(Paragraph(f"Arbeitszeitenüberblick {month_label}", title_style))
        story.append(Spacer(1, 4 * mm))

        table_data = [[Paragraph(text, header_style) for text in headers]]
        row_colors: list[tuple[int, colors.Color]] = []
        month_total = 0.0
        _, day_count = calendar.monthrange(year, month)

        for day_num in range(1, day_count + 1):
            current = date(year, month, day_num)
            weekday = current.weekday()
            row_index = day_num
            key = current.isoformat()
            holiday = holiday_name(current)
            absence_kind = next(
                (kind for kind in ABSENCE_KINDS if (absences.get(kind) or {}).get(key)),
                None,
            )
            if absence_kind is not None:
                row_colors.append((row_index, ABSENCE_COLORS[absence_kind]))
            elif current < EMPLOYMENT_START:
                row_colors.append((row_index, BEFORE_START_COLOR))
            elif holiday is not None:
                row_colors.append((row_index, HOLIDAY_COLOR))
            elif weekday >= 5:
                row_colors.append((row_index, WEEKEND_COLOR))

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

            notes: list[str] = []
            if holiday is not None:
                notes.append(holiday)
            if absence_kind is not None:
                name = ABSENCE_KINDS[absence_kind]
                notes.append(name if absences[absence_kind][key] >= 1 else f"½ {name}")
            if notes:
                hours_text = "<br/>".join([hours_text, *notes] if hours_text else notes)

            cells = [started, pauses_html, ended, pause_total, hours_text]
            if work_day is not None:
                # Eingetragener Tag: leere Felder als „–“, damit er nicht vergessen aussieht.
                cells = [text or "–" for text in cells]
            table_data.append(
                [Paragraph(tag, cell_style), *(Paragraph(text, cell_style) for text in cells)]
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
        for row, color in row_colors:
            style_commands.append(("BACKGROUND", (0, row), (-1, row), color))

        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle(style_commands))
        story.append(table)
        breakdown = target_breakdown(year, month, absences, absence_totals)
        story.append(
            KeepTogether(
                [
                    Spacer(1, 2 * mm),
                    _legend_table(usable_width, legend_style),
                    Spacer(1, 5 * mm),
                    _summary_table(breakdown, month_total, footer_style, footer_bold_style),
                ]
            )
        )

    document = BaseDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=PAGE_MARGIN_X,
        rightMargin=PAGE_MARGIN_X,
        topMargin=PAGE_MARGIN_TOP,
        bottomMargin=PAGE_MARGIN_BOTTOM,
        title="Arbeitszeitenüberblick",
    )
    frame = Frame(
        document.leftMargin,
        document.bottomMargin,
        document.width,
        document.height,
        id="content",
    )
    # onPageEnd: Marker der Seite sind dann schon gezeichnet, der Monat stimmt auch auf Folgeseiten.
    document.addPageTemplates(
        [PageTemplate(id="month", frames=[frame], onPageEnd=_draw_page_header)]
    )
    document.build(story)
    return pdf_path


def _legend_table(width: float, style: ParagraphStyle) -> Table:
    entries = [
        (BEFORE_START_COLOR, "vor Arbeitsbeginn"),
        (ABSENCE_COLORS["krank"], "Krank"),
        (HOLIDAY_COLOR, "Feiertag"),
        (ABSENCE_COLORS["urlaub"], "Urlaub"),
        (WEEKEND_COLOR, "Wochenende"),
    ]
    cells: list = []
    widths: list[float] = []
    commands: list[tuple] = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]
    for color, label in entries:
        column = len(cells)
        cells.extend(["", Paragraph(label, style)])
        widths.extend([4 * mm, 30 * mm])
        commands.append(("BACKGROUND", (column, 0), (column, 0), color))
        commands.append(("BOX", (column, 0), (column, 0), 0.4, colors.HexColor("#666666")))
    table = Table([cells], colWidths=widths, rowHeights=[4 * mm], hAlign="LEFT")
    table.setStyle(TableStyle(commands))
    return table


def _summary_table(
    breakdown: TargetBreakdown,
    month_total: float,
    style: ParagraphStyle,
    bold: ParagraphStyle,
) -> Table:
    right = ParagraphStyle("pdf_footer_right", parent=style, alignment=TA_RIGHT)
    right_bold = ParagraphStyle("pdf_footer_right_bold", parent=bold, alignment=TA_RIGHT)
    small = ParagraphStyle("pdf_footer_small", parent=style, fontSize=8, textColor=PAGE_TEXT_COLOR)
    head = ParagraphStyle("pdf_footer_head", parent=right, fontSize=8, textColor=PAGE_TEXT_COLOR)

    def days_text(days: float) -> str:
        return format_vacation_days(days) if days else "0"

    rows = [
        ["", Paragraph("Tage", head), Paragraph("Stunden", head), ""],
        [
            Paragraph("Arbeitstage (Mo–Fr)", style),
            Paragraph(days_text(breakdown.weekdays), right),
            Paragraph(f"{format_hours(breakdown.base_hours)} Std.", right),
            "",
        ],
    ]
    for item in breakdown.deductions:
        details = [day.strftime("%d.%m.") for day in item.dates]
        if item.lump_days:
            details.append(f"{format_vacation_days(item.lump_days)} pauschal")
        rows.append(
            [
                Paragraph(f"– {item.name}", style),
                Paragraph(days_text(item.days), right),
                Paragraph(f"– {format_hours(item.hours)} Std.", right),
                Paragraph(", ".join(details), small),
            ]
        )
    target = breakdown.total
    rows.append(
        [
            Paragraph("= Sollstunden", bold),
            Paragraph(days_text(breakdown.target_days), right_bold),
            Paragraph(f"{format_hours(target)} Std.", right_bold),
            "",
        ]
    )
    rows.append(
        [
            Paragraph("Gesamtstunden (Ist)", style),
            "",
            Paragraph(f"{format_hours(month_total)} Std.", right),
            "",
        ]
    )
    rows.append(
        [
            Paragraph("Differenz (Ist – Soll)", bold),
            "",
            Paragraph(f"{format_signed_hours(month_total - target)} Std.", right_bold),
            "",
        ]
    )
    target_row = len(breakdown.deductions) + 2
    table = Table(rows, colWidths=[45 * mm, 15 * mm, 30 * mm, 90 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (3, 0), (3, -1), 6 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LINEABOVE", (0, target_row), (2, target_row), 0.6, colors.black),
                ("LINEABOVE", (0, -1), (2, -1), 0.6, colors.black),
            ]
        )
    )
    return table
