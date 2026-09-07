"""Shared white visual theme for the integrated research bundle.

The indicator-specific Pine colours stay untouched. This module only changes the
research canvas, panels, labels and structural accents so every research image
uses the same white, print-friendly visual language.
"""

from __future__ import annotations


def apply_white_theme() -> None:
    """Apply the white research palette to all four research renderers."""
    from src import fundamental_card, moving_average_card, research_card, research_chart

    white = "#FFFFFF"
    panel = "#F8FAFC"
    panel_2 = "#F1F5F9"
    grid = "#D7E0EA"
    text = "#172033"
    muted = "#64748B"
    green = "#15803D"
    red = "#C62828"
    amber = "#B7791F"
    accent = "#0F6CBD"
    teal = "#0F8A83"

    fundamental_card.BG = white
    fundamental_card.PANEL = white
    fundamental_card.TEXT = text
    fundamental_card.MUTED = muted
    fundamental_card.GRID = grid
    fundamental_card.TEAL = "#DDF4F2"
    fundamental_card.TEAL_DARK = teal
    fundamental_card.GREEN = green
    fundamental_card.RED = red
    fundamental_card.AMBER = amber

    moving_average_card.BG = white
    moving_average_card.PANEL = white
    moving_average_card.GRID = grid
    moving_average_card.TEXT = text
    moving_average_card.MUTED = muted
    moving_average_card.GREEN = green
    moving_average_card.RED = red
    moving_average_card.AMBER = amber
    moving_average_card.CYAN = accent

    research_card.BG = white
    research_card.PANEL = panel
    research_card.TEXT = text
    research_card.MUTED = muted
    research_card.GRID = grid
    research_card.GREEN = green
    research_card.RED = red
    research_card.AMBER = amber
    research_card.TEAL = accent

    research_chart.BG = white
    research_chart.PANEL = white
    research_chart.PANEL_2 = panel_2
    research_chart.GRID = grid
    research_chart.TEXT = text
    research_chart.MUTED = muted
    research_chart.GREEN = "#089981"
    research_chart.RED = "#F23645"
    research_chart.AMBER = amber
    research_chart.CYAN = accent
