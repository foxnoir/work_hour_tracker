#!/usr/bin/env python3
"""Generate local README badges.

Every badge is a vertical dark → mid → light gradient, same contrast as Instagram.
The mid stop is the brand or playground color. Official colors stay official
except black — it is hard to see. When a tool has no published color, or the
official color is black, pick from the playground palette (purple / blue /
turquoise / pink / green). Avoid black, orange, red, and yellow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

ROOT = Path(__file__).resolve().parent

# Mix amounts match the Instagram badge: mid #8B5FBF → #4A2F6B / #C9A8E0.
_DARKEN = 0.45
_LIGHTEN = 0.48


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(red: int, green: int, blue: int) -> str:
    return f"#{red:02X}{green:02X}{blue:02X}"


def _mix(color: str, toward: str, amount: float) -> str:
    red, green, blue = _hex_to_rgb(color)
    to_red, to_green, to_blue = _hex_to_rgb(toward)
    return _rgb_to_hex(
        round(red + (to_red - red) * amount),
        round(green + (to_green - green) * amount),
        round(blue + (to_blue - blue) * amount),
    )


def shade_gradient(mid: str) -> Tuple[str, str, str]:
    return _mix(mid, "#000000", _DARKEN), mid, _mix(mid, "#FFFFFF", _LIGHTEN)


# slug, label, mid color, note
BADGES: list[tuple[str, str, str, str]] = [
    ("python", "Python", "#3776AB", "official Python"),
    ("reportlab", "ReportLab", "#2D8A86", "teal (no published badge color)"),
    ("pytest", "pytest", "#4A8C6F", "green (replaces yellow)"),
    ("linkedin", "LinkedIn", "#0A66C2", "official LinkedIn"),
    ("instagram", "Instagram", "#8B5FBF", "lilac"),
    ("x", "X", "#7EB8D6", "pastel light blue (replaces black)"),
]


def badge_svg(label: str, mid: str) -> str:
    width = max(72, 22 + len(label) * 8)
    dark, mid, light = shade_gradient(mid)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="28" role="img" aria-label="{label}">
  <title>{label}</title>
  <defs>
    <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{dark}"/>
      <stop offset="50%" stop-color="{mid}"/>
      <stop offset="100%" stop-color="{light}"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="28" fill="url(#fill)"/>
  <text x="{width / 2}" y="18" text-anchor="middle" fill="#fff" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11" font-weight="700">{label}</text>
</svg>
"""


def write_all(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for slug, label, mid, _note in BADGES:
        (out_dir / f"{slug}.svg").write_text(badge_svg(label, mid), encoding="utf-8")


def main() -> int:
    write_all(ROOT)
    print(f"wrote {len(BADGES)} badges → {ROOT}")
    for slug, _label, mid, note in BADGES:
        dark, mid, light = shade_gradient(mid)
        print(f"  {slug}: {dark} → {mid} → {light}  ({note})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
