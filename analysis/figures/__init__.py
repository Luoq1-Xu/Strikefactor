"""Figure registry.

Each entry knows its output filename, the section it belongs to, and how to
render itself. The CLI, the HTML report, and `--sections` all read this one
list, so adding a figure means adding a row here and nothing else.
"""

from dataclasses import dataclass
from typing import Callable

from . import arsenal, location, overview, results, sequencing, trends


@dataclass(frozen=True)
class Figure:
    key: str
    filename: str
    section: str
    title: str
    caption: str
    render: Callable


FIGURES = [
    Figure("dashboard", "01_dashboard.png", "overview",
           "Dashboard",
           "Pitching line, batting results, pitch mix, and velocity at a glance.",
           overview.dashboard),

    Figure("velocity", "02_velocity.png", "arsenal",
           "Velocity",
           "Speed distribution per pitch type, one panel per pitcher.",
           arsenal.velocity),
    Figure("movement", "03_movement.png", "arsenal",
           "Movement",
           "Horizontal vs induced-vertical break, with 1σ spread ellipses.",
           arsenal.movement),
    Figure("scouting", "04_scouting_card.png", "arsenal",
           "Scouting Card",
           "Per-pitch-type quality vs MLB benchmarks and within-slice rank.",
           arsenal.scouting_card),
    Figure("run_value", "05_run_value.png", "arsenal",
           "Run Value",
           "Runs saved per 100 pitches, the count-value surface, and count states.",
           arsenal.run_value),

    Figure("zone", "06_zone_profile.png", "location",
           "Zone Profile",
           "Binned 5×5 location grids: density, swing, whiff, and damage.",
           location.zone_profile),
    Figure("platoon", "07_platoon.png", "location",
           "Platoon Splits",
           "Zone grids and rate stats split by batter handedness.",
           location.platoon_splits),
    Figure("umpire", "08_umpire.png", "location",
           "Umpire Accuracy",
           "AI umpire calls vs ground truth, and where the misses cluster.",
           location.umpire),

    Figure("sequencing", "09_sequencing.png", "sequencing",
           "Sequencing",
           "How much a pitch gains from what preceded it.",
           sequencing.sequencing),
    Figure("tunneling", "10_tunneling.png", "sequencing",
           "Tunneling",
           "Mean flight paths with the commit point marked, plus tunnel ratios.",
           sequencing.tunneling),

    Figure("outcomes", "11_outcomes.png", "results",
           "Outcomes",
           "Terminal at-bat outcomes per pitcher, as counts and as a share of PA.",
           results.outcomes),
    Figure("counts", "12_count_usage.png", "results",
           "Count Usage",
           "Pitch selection by ball-strike count and how each count state plays.",
           results.count_usage),
    Figure("discipline", "13_plate_discipline.png", "results",
           "Plate Discipline",
           "Full per-pitcher rate-stat table with stuff and K%/BB% charts.",
           results.plate_discipline),

    Figure("trends", "14_trends.png", "trends",
           "Trends",
           "Rolling CSW%, chase, wOBA, and run value across the sample window.",
           trends.trends),
    Figure("volume", "15_volume.png", "trends",
           "Sample Composition",
           "Where the sample comes from: mode, difficulty, and pitches per day.",
           trends.volume),
]

SECTIONS = ["overview", "arsenal", "location", "sequencing", "results", "trends"]

SECTION_TITLES = {
    "overview": "Overview",
    "arsenal": "Arsenal",
    "location": "Location & Umpiring",
    "sequencing": "Sequencing & Deception",
    "results": "Results",
    "trends": "Trends",
}


def select(sections=None, keys=None):
    """Filter the registry by section name or figure key."""
    figs = FIGURES
    if sections:
        wanted = {s.strip().lower() for s in sections}
        figs = [f for f in figs if f.section in wanted]
    if keys:
        wanted = {k.strip().lower() for k in keys}
        figs = [f for f in figs if f.key in wanted]
    return figs
