"""Guards for the recorded-outcome vocabulary.

Outcomes are stored as free text and matched by exact string in a dozen places
(scoring, GameDay out-counting, the analysis groups), so a spelling drifting
apart from the rest is a silent miscount rather than a crash. Pop-ups were
recorded as ``POP_UP`` until schema v5 renamed them to ``POP UP``, in line with
``HOME RUN``.
"""

import sqlite3

import pytest

from analysis import theme
from strikefactor import outcomes
from strikefactor.data.pitch_database import SCHEMA_VERSION, V5_OUTCOME_RENAMES, PitchDB


def test_recorded_outcomes_use_spaces_not_underscores():
    """No recorded outcome name may carry an underscore."""
    for group in (
        theme.HIT_OUTCOMES,
        theme.BATTED_OUT_OUTCOMES,
        theme.IN_PLAY_OUTCOMES,
        theme.OUT_OUTCOMES,
        theme.TERMINAL_OUTCOMES,
    ):
        offenders = [o for o in group if "_" in o]
        assert not offenders, f"underscored outcome names: {offenders}"


def test_pop_up_is_present_in_every_outcome_group():
    """The rename must not drop it out of the denominators it belongs in."""
    assert "POP UP" in theme.BATTED_OUT_OUTCOMES
    assert "POP UP" in theme.IN_PLAY_OUTCOMES
    assert "POP UP" in theme.OUT_OUTCOMES
    assert "POP UP" in theme.TERMINAL_OUTCOMES
    assert "POP UP" in theme.OUTCOME_ORDER
    assert "POP UP" in theme.OUTCOME_COLORS
    assert "POP UP" in theme.OUTCOME_ABBREV
    assert "POP UP" in theme.EVENT_RUN_VALUE


@pytest.mark.parametrize("outcome", ["POP UP", "HOME RUN"])
def test_terminal_outcomes_still_match_after_normalization(outcome):
    """PitchDataExtractor normalizes spaces to underscores before matching."""
    from strikefactor.data.pitch_database import PitchDataExtractor

    assert outcome.upper().replace(" ", "_") in PitchDataExtractor.TERMINAL_OUTCOMES


def test_migration_rewrites_legacy_pop_up(tmp_path):
    """A pre-v5 database has its old spelling rewritten on open, once."""
    db_path = str(tmp_path / "legacy.db")

    # Build a v4-shaped database carrying the old spelling.
    pitch_cols = "session_id, created_at, pitcher_name, pitch_type, outcome"
    seed = PitchDB(db_path)
    for outcome in ("POP_UP", "HOME RUN"):
        seed.conn.execute(
            f"INSERT INTO pitches ({pitch_cols}) VALUES ('s', 't', 'sale', 'FF', ?)",
            (outcome,),
        )
    seed.conn.execute(
        "INSERT INTO at_bats (session_id, created_at, final_outcome) "
        "VALUES ('s', 't', 'POP_UP')"
    )
    seed.conn.execute("PRAGMA user_version = 4")
    seed.conn.commit()
    seed.close()

    db = PitchDB(db_path)
    try:
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        counts = dict(
            db.conn.execute("SELECT outcome, COUNT(*) FROM pitches GROUP BY 1")
        )
        assert counts == {"POP UP": 1, "HOME RUN": 1}
        assert db.conn.execute(
            "SELECT final_outcome FROM at_bats"
        ).fetchone()[0] == "POP UP"
    finally:
        db.close()

    # Idempotent: re-opening an already-migrated db changes nothing.
    again = PitchDB(db_path)
    try:
        assert again.conn.execute(
            "SELECT COUNT(*) FROM pitches WHERE outcome = 'POP UP'"
        ).fetchone()[0] == 1
    finally:
        again.close()


def test_rename_table_maps_old_to_new():
    assert dict(V5_OUTCOME_RENAMES) == {"POP_UP": "POP UP"}


def test_gameday_history_normalizes_legacy_play_results():
    """Restored archives still carry POP_UP; the loader maps them on read."""
    from strikefactor.gameplay.gameday_manager import GameDayManager

    games = [
        {"result": "WIN", "play_log": [
            {"result": "POP_UP"}, {"result": "FLYOUT"}, {"result": "HOME RUN"},
        ]},
        {"result": "LOSS", "play_log": "not-a-list"},   # must not raise
        {"no_play_log": True},
    ]
    GameDayManager._normalize_legacy_outcomes(games)

    assert [p["result"] for p in games[0]["play_log"]] == [
        "POP UP", "FLYOUT", "HOME RUN",
    ]
    # Game-level result ('WIN'/'LOSS') is a different field and untouched.
    assert games[0]["result"] == "WIN"


def test_live_database_has_no_legacy_spelling():
    """The user's real db was migrated; catch a regression that reintroduces it."""
    from strikefactor.config import get_path

    conn = sqlite3.connect(get_path("data/strikefactor.db"))
    try:
        for table, col in (("pitches", "outcome"), ("at_bats", "final_outcome")):
            stale = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} = 'POP_UP'"
            ).fetchone()[0]
            assert stale == 0, f"{table}.{col} still has {stale} POP_UP rows"
    finally:
        conn.close()


def test_reached_on_error_is_in_the_right_groups():
    """A ball in play and a terminal outcome, but neither a hit nor an out.

    Getting the grouping wrong fails silently in both directions: left out of
    IN_PLAY_OUTCOMES it drops from every PA/BF denominator (the bug the pop-up
    comment above records), and slipped into HIT_OUTCOMES it inflates AVG and
    BABIP with hits the batter never earned. The membership *and* the
    non-membership are both load-bearing, so both are asserted.
    """
    assert "REACHED ON ERROR" in theme.REACH_OUTCOMES
    assert "REACHED ON ERROR" in theme.IN_PLAY_OUTCOMES
    assert "REACHED ON ERROR" in theme.TERMINAL_OUTCOMES
    assert "REACHED ON ERROR" in theme.OUTCOME_ORDER
    assert "REACHED ON ERROR" in theme.OUTCOME_COLORS
    assert "REACHED ON ERROR" in theme.OUTCOME_ABBREV
    assert "REACHED ON ERROR" in theme.EVENT_RUN_VALUE

    assert "REACHED ON ERROR" not in theme.HIT_OUTCOMES
    assert "REACHED ON ERROR" not in theme.BATTED_OUT_OUTCOMES
    assert "REACHED ON ERROR" not in theme.OUT_OUTCOMES


def test_reaching_on_an_error_closes_the_at_bat():
    """`PitchDataExtractor.TERMINAL_OUTCOMES` is a closed set compared against
    the underscored form. An outcome missing from it does not raise — the
    at-bat is simply never closed, which is the quietest possible failure."""
    from strikefactor.data.pitch_database import PitchDataExtractor

    assert ("REACHED ON ERROR".upper().replace(" ", "_")
            in PitchDataExtractor.TERMINAL_OUTCOMES)


def test_reaching_on_an_error_is_an_at_bat_but_not_a_hit_or_an_out():
    """The GameDay batting line counts `ab` only inside its result lists, so
    an outcome in none of them vanishes from the AVG denominator entirely."""
    from strikefactor.gameplay.game_states import GameDayTransitionState as G

    assert "REACHED ON ERROR" in G._REACH_RESULTS
    assert "REACHED ON ERROR" not in G._HIT_RESULTS
    assert "REACHED ON ERROR" not in G._OUT_RESULTS


def test_the_scorekeeper_puts_the_batter_on_without_an_out():
    """It used to work by falling through to the catch-all `else`, which
    happened to be right for one base and could not express a two-base error
    at all."""
    from strikefactor.helpers import ScoreKeeper

    sk = ScoreKeeper()
    sk.update_hit_event("REACHED ON ERROR")
    assert sk.isRunnerOnBase(1)
    assert sk.get_score() == 0

    sk2 = ScoreKeeper()
    sk2.update_hit_event("REACHED ON ERROR", bases=2)
    assert sk2.isRunnerOnBase(2)
    assert not sk2.isRunnerOnBase(1)


def test_the_banner_says_error_while_the_record_still_says_reached_on_error():
    """The two vocabularies are separate, and only one of them is load-bearing.

    Everything above this line matches "REACHED ON ERROR" by exact string and
    fails *silently* on anything else, so the shorter word the player reads has
    to be a display name applied at the seam where an outcome becomes text --
    not a rename of the value. If this ever passes by the record having been
    renamed too, the tests above are what break.
    """
    from strikefactor.gameplay.pitch_simulation import PitchSimulation

    assert PitchSimulation._format_display_outcome("REACHED ON ERROR") == "ERROR"
    # ...and the seam is still the plain underscore-to-space rule for the rest.
    for outcome in ("SINGLE", "DOUBLE", "TRIPLE", "HOME RUN", "GROUNDOUT",
                    "FLYOUT", "LINEOUT", "POP UP"):
        assert PitchSimulation._format_display_outcome(outcome) == outcome
    assert PitchSimulation._format_display_outcome("POP_UP") == "POP UP"


def test_the_pitch_selection_ai_is_not_punished_for_its_defense():
    """`GameStats.outcome_value` is the Q-learning reward, read as
    `.get(outcome, 0)` and scored from the *pitcher's* side. Unmapped, an
    error would return a neutral 0 for a pitch that did its job; scored like a
    single it would teach the AI to stop inducing ground balls."""
    from strikefactor.main import GameStats

    values = GameStats().outcome_value
    assert values["REACHED ON ERROR"] > 0
    assert values["REACHED ON ERROR"] < values["GROUNDOUT"]
    assert values["REACHED ON ERROR"] > values["SINGLE"]


# ---- One vocabulary, four consumers ---------------------------------------
#
# These pin the composition rather than the contents. Every set above used to
# be enumerated by hand in its own module, in its own spelling, and the three
# failure modes were all silent — an outcome missing from `TERMINAL_OUTCOMES`
# never closes the at-bat, one missing from `_OUT_RESULTS` vanishes from the
# AVG denominator, one missing from `is_out` is credited as a hit. What makes
# a fifth outcome cheap is that it joins one group in `strikefactor.outcomes`
# and every derived set follows; what these tests guard is that the sets are
# still *derived*.

def test_every_consumer_composes_the_shared_vocabulary():
    from strikefactor.data.pitch_database import PitchDataExtractor
    from strikefactor.gameplay.game_states import GameDayTransitionState as G
    from strikefactor.helpers import OUTCOME_COLORS

    assert G._HIT_RESULTS == tuple(o.upper() for o in outcomes.HIT_OUTCOMES)
    assert G._OUT_RESULTS == tuple(o.upper() for o in outcomes.OUT_OUTCOMES)
    assert G._REACH_RESULTS == tuple(o.upper() for o in outcomes.REACH_OUTCOMES)
    assert PitchDataExtractor.TERMINAL_OUTCOMES is outcomes.DB_TERMINAL_OUTCOMES
    assert OUTCOME_COLORS is outcomes.COLORS


def test_the_analysis_groups_agree_with_the_games():
    """`analysis/theme.py` deliberately keeps its own copy — it is an offline
    process that must read an archived DB without the game installed. That
    makes it the one place a drift cannot be prevented by construction, so it
    is prevented by assertion instead."""
    assert set(theme.HIT_OUTCOMES) == set(outcomes.HIT_OUTCOMES)
    assert set(theme.BATTED_OUT_OUTCOMES) == set(outcomes.BATTED_OUT_OUTCOMES)
    assert set(theme.REACH_OUTCOMES) == set(outcomes.REACH_OUTCOMES)
    assert set(theme.IN_PLAY_OUTCOMES) == set(outcomes.IN_PLAY_OUTCOMES)
    assert set(theme.OUT_OUTCOMES) == set(outcomes.OUT_OUTCOMES)
    assert set(theme.TERMINAL_OUTCOMES) == set(outcomes.TERMINAL_OUTCOMES)


def test_the_underscored_spelling_has_one_producer():
    """`db_key` is the only place `POP UP` becomes `POP_UP`. It used to be
    written out at each comparison, which is how two spellings of one outcome
    both came to need matching."""
    assert outcomes.db_key("POP UP") == "POP_UP"
    assert outcomes.db_key("HOME RUN") == "HOME_RUN"
    assert outcomes.db_key("strikeout") == "STRIKEOUT"
    assert outcomes.db_key(None) == ""
    assert all(" " not in k for k in outcomes.DB_TERMINAL_OUTCOMES)


def test_the_error_amber_has_one_definition():
    """It was a literal in four files, and the constant that was meant to be
    authoritative carried a comment listing the other three copies."""
    from strikefactor.gameplay import hit_animation as ha

    assert ha.ERROR_MARK_COLOR == outcomes.ERROR_COLOR
    assert outcomes.COLORS[outcomes.REACHED_ON_ERROR] == outcomes.ERROR_COLOR


def test_a_hit_and_the_bases_it_is_worth_cannot_disagree():
    assert set(outcomes.HIT_BASES) == set(outcomes.HIT_OUTCOMES)
    assert sorted(outcomes.HIT_BASES.values()) == [1, 2, 3, 4]
