"""Regression checks for recorded outcomes in the batting report."""

import importlib.util
import sqlite3
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg", force=True)

from analysis import data
from analysis.filters import Filter

# A sacrifice fly, a fly ball that scored nobody, and a dropped fly that
# would have been one: (outcome, runs_scored_on_pitch, batted_ball_type,
# runner_3b, outs_before).
SACRIFICE_FLY_ROWS = (
    ("FLYOUT", 1, "FLY", 1, 0),
    ("FLYOUT", 0, "FLY", 0, 0),
    ("REACHED ON ERROR", 1, "FLY", 1, 1),
)


@pytest.fixture
def report(request, tmp_path, monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE pitches (outcome TEXT, swing_type INTEGER, on_time INTEGER, "
        "is_strike INTEGER, is_hit INTEGER, plate_x_ft REAL, plate_z_ft REAL, "
        "balls_before INTEGER, strikes_before INTEGER, pitch_type TEXT, "
        "difficulty TEXT, game_mode TEXT, batter_hand TEXT, pitcher_name TEXT)"
    )
    for outcome in ("SINGLE", "POP UP", "REACHED ON ERROR", "GROUNDOUT", "strikeout", "walk"):
        conn.execute(
            "INSERT INTO pitches VALUES (?, ?, ?, ?, ?, 0, 2.5, 0, 0, 'FF', "
            "'amateur', 'gameday', 'R', 'chrissale')",
            (outcome, int(outcome != "walk"), 0 if outcome == "strikeout" else 2,
             int(outcome == "strikeout"), int(outcome == "SINGLE")),
        )
    # The report's active slice must exclude this hit from both AVG panels.
    conn.execute(
        "INSERT INTO pitches VALUES ('HOME RUN', 1, 2, 0, 1, 0, 2.5, 0, 0, "
        "'FF', 'amateur', 'arcade', 'R', 'chrissale')"
    )
    # Left as the narrow table unless a test asks: that is the shape of an old
    # archive, which has nothing to rule a sacrifice fly from.
    for row in getattr(request, "param", ()):
        if "runs_scored_on_pitch" not in {
                r[1] for r in conn.execute("PRAGMA table_info(pitches)")}:
            for column in ("runs_scored_on_pitch INTEGER", "batted_ball_type TEXT",
                           "runner_3b INTEGER", "outs_before INTEGER"):
                conn.execute(f"ALTER TABLE pitches ADD COLUMN {column}")
        conn.execute(
            "INSERT INTO pitches VALUES (?, 1, 2, 0, 0, 0, 2.5, 0, 0, 'FF', "
            "'amateur', 'gameday', 'R', 'chrissale', ?, ?, ?, ?)", row)
    monkeypatch.setattr(data, "connect", lambda: conn)
    monkeypatch.setattr(data, "DEFAULT_OUT_DIR", str(tmp_path))

    spec = importlib.util.spec_from_file_location(
        "batting_analysis_under_test", Path(__file__).resolve().parents[1] / "batting_analysis.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.FILTER = Filter(modes=("gameday",))
    figures = []
    close = module.plt.close
    monkeypatch.setattr(module.plt.Figure, "savefig", lambda self, *a, **kw: None)
    monkeypatch.setattr(module.plt, "close", lambda fig: figures.append(fig))
    yield module, figures
    for fig in figures:
        close(fig)
    conn.close()


def test_batting_report_counts_pop_ups_and_errors_as_at_bats(report):
    module, figures = report
    module.fig7_batting_dashboard()
    axes = {ax.get_title(): ax for ax in figures[-1].axes}

    # One hit in five at-bats: popup, error, groundout, and strikeout all
    # lower AVG. The walk is a PA only; the Arcade homer is filtered away.
    assert axes["AVG by Count"].patches[0].get_height() == pytest.approx(0.2)
    assert axes["AVG vs Pitch Type"].patches[0].get_width() == pytest.approx(0.2)
    assert "Out (in play)\n(2)" in [t.get_text() for t in axes["All Pitch Outcomes"].texts]


@pytest.mark.parametrize("report", [SACRIFICE_FLY_ROWS], indirect=True)
def test_batting_report_charges_no_at_bat_for_a_sacrifice_fly(report):
    """Three more plate appearances and one more at-bat: the fly ball that
    scored nobody. The game's scorer charges none for the other two, and the
    report used to charge all three."""
    module, figures = report
    module.fig7_batting_dashboard()
    axes = {ax.get_title(): ax for ax in figures[-1].axes}

    assert axes["AVG by Count"].patches[0].get_height() == pytest.approx(1 / 6)
    assert axes["AVG vs Pitch Type"].patches[0].get_width() == pytest.approx(1 / 6)
    stats = axes["Key Batting Stats"].texts[0].get_text()
    assert "PA    9" in stats
    assert f"AVG   {1 / 6:.3f}" in stats
    assert f"OBP   {2 / 9:.3f}" in stats        # a sacrifice fly is still a PA


def test_pop_up_appears_in_both_outcome_figures(report):
    module, figures = report
    module.fig5_contact_vs_power()
    axes = {ax.get_title(): ax for ax in figures[-1].axes}
    # Two batted outs among five swings, including the popup.
    assert axes["Outcome Distribution"].containers[0][2].get_width() == pytest.approx(40.0)

    module.fig6_outcomes_by_zone()
    axes = {ax.get_title(): ax for ax in figures[-1].axes}
    labels = {collection.get_label() for collection in axes[next(
        title for title in axes if title.startswith("n = ")
    )].collections}
    assert "POP UP (1)" in labels
