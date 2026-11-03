"""The contact harness, and the batter it says the game produces.

`tools/calibrate_contact.py` is the instrument every quantile anchor in
`tools/sim.py` and `contact_audio.EV_CALIBRATION` is read off. It was written
because its predecessor was never committed, so none of those anchors could be
re-derived. Two things are guarded here: that the instrument is one (the same
arguments always give the same swings, however they are run), and that what it
reads is still what the anchors were taken from.

The bands are deliberately wider than the harness's own numbers at n = 52,000.
A test has to pass at a sample a test can afford; use the harness to tune and
this to catch a regression.
"""

import functools

import pytest

from strikefactor.gameplay import spray
from strikefactor.settings_manager import DifficultyLevel
from tools import calibrate_contact as harness
from tools import sim

# One run, many assertions. Deterministic, so handing the same summary to
# several tests is one simulation instead of several.
N = 2600


@functools.lru_cache(maxsize=None)
def _swings(level="amateur", hand="R", n=N, seed=17):
    return tuple(harness.run(n, seed=seed, hand=hand, level=level))


@functools.lru_cache(maxsize=None)
def _summary(level="amateur", hand="R", n=N, seed=17):
    return harness.summarise(list(_swings(level, hand, n, seed)))


# ---- The instrument ---------------------------------------------------------

def _key(swing):
    c = swing.contact
    return (swing.verdict, swing.timing_ms, None if c is None else
            (c.swing_t_s, c.ball_ft, c.along, c.exit_direction))


def test_a_swing_is_a_function_of_its_seed_and_its_index():
    """So a longer run is a superset of a shorter one, and nothing about how
    the work is split can change a number."""
    short = harness.run(40, seed=5)
    long = harness.run(90, seed=5)
    assert [_key(s) for s in long[:40]] == [_key(s) for s in short]
    again = harness.run(40, seed=5)
    assert [_key(s) for s in again] == [_key(s) for s in short]
    assert [_key(s) for s in harness.run(40, seed=6)] != [_key(s) for s in short]


def test_worker_processes_do_not_change_a_number():
    one = harness.run(60, seed=9, jobs=1)
    two = harness.run(60, seed=9, jobs=2)
    assert [_key(s) for s in two] == [_key(s) for s in one]


def test_the_player_is_the_canonical_one():
    """Aim scatter 0.75 ft per axis and timing N(+19, 48) ms: the model
    `settings_manager.DIFFICULTY_MULTIPLIERS` and `EV_CALIBRATION` quote. A
    different player here silently re-anchors everything downstream."""
    assert harness.AIM_SCATTER_FT == 0.75
    assert (harness.TIMING_MEAN_MS, harness.TIMING_SD_MS) == (19.0, 48.0)
    late = [s.timing_ms for s in _swings()]
    assert 16.0 < sum(late) / len(late) < 22.0


def test_an_override_reaches_the_swings_and_is_refused_if_misspelt(monkeypatch):
    """`--set` is how a constant is tried without editing it.

    An override is set on the module for the rest of the process, which is
    what a command-line run wants and not what a test does: the baseline is
    read first and `monkeypatch` puts the constant back.
    """
    from strikefactor.gameplay import bat_contact
    baseline = _summary()["fair"]
    monkeypatch.setattr(bat_contact, "FOUL_QUALITY_THRESHOLD",
                        bat_contact.FOUL_QUALITY_THRESHOLD)
    strict = harness.summarise(harness.run(
        300, overrides=(("bat_contact.FOUL_QUALITY_THRESHOLD", 0.95),)))
    assert strict["fair"] < 0.5 * baseline
    with pytest.raises(SystemExit):
        harness.apply_overrides((("bat_contact.NO_SUCH_CONSTANT", 1.0),))


# ---- What it reads ----------------------------------------------------------

def test_the_split_is_the_documented_one():
    """Whiff / foul / fair about 30 / 31 / 39 at AMATEUR."""
    s = _summary()
    assert 0.26 <= s["whiff"] <= 0.34, s["whiff"]
    assert 0.27 <= s["foul"] <= 0.35, s["foul"]
    assert 0.35 <= s["fair"] <= 0.43, s["fair"]


def test_both_ways_to_foul_a_ball_are_doing_work():
    """Direction and quality, neither one the whole verdict. They overlap on
    the balls struck glancingly enough to leave behind the plate."""
    s = _summary()
    assert 0.24 <= s["foul_by_direction"] <= 0.40
    assert 0.30 <= s["foul_by_quality"] <= 0.46
    assert s["foul_by_both"] > 0.15
    assert s["foul_by_direction"] - s["foul_by_both"] > 0.03
    assert s["foul_by_quality"] - s["foul_by_both"] > 0.06


def test_the_batted_ball_mix_is_the_leagues():
    """GB 42 / LD 24 / FB 27 / PU 7, off one collision and no prior. The
    launch angle's response is nearly twice what the fitted model gave, so
    this is the test that says fair contact is square enough to carry it."""
    mix = _summary()["mix"]
    assert 0.36 <= mix["GROUNDER"] <= 0.48, mix
    assert 0.19 <= mix["LINER"] <= 0.29, mix
    assert 0.22 <= mix["FLY"] <= 0.32, mix
    assert 0.03 <= mix["POP_UP"] <= 0.10, mix


def test_all_three_fields_get_used():
    s = _summary()
    assert 0.24 <= s["pull"] <= 0.37
    assert 0.38 <= s["centre"] <= 0.52
    assert 0.19 <= s["oppo"] <= 0.31


def test_the_two_hands_are_the_same_batter():
    """A left-handed run mirrors the whole pitch, so every rate has to agree
    with the right-handed one to within sampling noise. A sign error anywhere
    in the chain shows up here as two different hitters."""
    r, l = _summary(hand="R"), _summary(hand="L")
    for key in ("whiff", "foul", "fair", "pull", "oppo"):
        assert abs(r[key] - l[key]) < 0.04, (key, r[key], l[key])
    for shape in harness.SHAPES:
        assert abs(r["mix"][shape] - l["mix"][shape]) < 0.05, shape
    # And deterministically, where there is no noise to hide in.
    assert harness.on_time_table("L") == harness.on_time_table("R")


def test_difficulty_runs_one_way_down_the_ladder():
    """Contact falls and the foul share of contact rises, at every rung.

    The aim assist is what turns swings into balls in play and the timing
    window is what turns whiffs into contact; neither may run backwards."""
    rows = [_summary(level=level.value, n=1200) for level in DifficultyLevel]
    contact = [s["contact"] for s in rows]
    fouled = [s["foul_of_contact"] for s in rows]
    fair = [s["fair"] for s in rows]
    assert contact == sorted(contact, reverse=True), contact
    assert fouled == sorted(fouled), fouled
    assert fair == sorted(fair, reverse=True), fair
    assert fair[0] > 5.0 * fair[-1], "the hard end is not much harder"


# ---- The acceptance geometry, on the deterministic table ---------------------

@pytest.mark.parametrize("hand", ["R", "L"])
def test_the_on_time_table_meets_the_geometry_the_rework_was_for(hand):
    """A square bat, met about half a foot out front, fair at every zone
    location, with the swing's own kinematics still inside their rails."""
    rows = harness.on_time_table(hand)
    middle = [r for r in rows if r["x"] == 0.0 and r["z"] == 2.5][0]
    assert abs(middle["bearing"]) < 10.0
    assert 0.3 < middle["depth"] < 1.0
    for r in rows:
        assert r["spray"] is not None, r
        assert spray.FOUL_LINE_DEG - abs(r["spray"]) >= 4.0, r
        assert 1.0 < r["hand_orbit"] < 2.0, r
        assert 1.9 < r["ease_k"] < 2.7, r
        assert r["quality"] > 0.96, r
    assert min(r["depth"] for r in rows) < 0.0, "the outside corner is met behind the plate"

    rate, pts = harness.timing_response(hand)
    assert len(pts) >= 12
    assert 1.3 < rate < 1.9, f"{rate:.2f} deg of spray per ms"


# ---- The anchors are this harness's -----------------------------------------

def test_the_sampler_anchors_describe_the_batter_the_harness_measures():
    """`tools/sim.py` is read off this harness at n = 52,000. At the sample a
    test can afford the two have to agree to within noise; if they do not,
    the contact geometry moved and the anchors were not re-derived
    (CLAUDE.md, rule 5)."""
    s = _summary()
    anchored = dict(sim.QUALITY_QUANTILES)
    for p in (0.25, 0.50, 0.75):
        assert harness.quantile(s["quality"], p) == pytest.approx(
            anchored[p], abs=0.02), p
    launch = dict(sim.LAUNCH_ANGLE_QUANTILES)
    for p in (0.25, 0.50, 0.75):
        assert harness.quantile(s["launch"], p) == pytest.approx(
            launch[p], abs=4.0), p
    for shape, share in sim.BATTED_BALL_MIX:
        assert s["mix"][shape] == pytest.approx(share, abs=0.04), shape
    mean = sum(s["spray"]) / len(s["spray"])
    assert mean == pytest.approx(sim.SPRAY_MEAN_DEG, abs=2.0)


def test_quality_by_shape_keeps_its_order():
    """Line drives are the best-struck ball and pop-ups the worst, with
    grounders and fly balls between. It is the geometry: quality peaks at dead
    centre, a line drive is just under it and a pop-up is an inch and a half
    under."""
    med = {shape: harness.quantile(rows, 0.5)
           for shape, rows in _summary()["quality_by_shape"].items()}
    assert med["LINER"] > med["GROUNDER"] > med["POP_UP"]
    assert med["LINER"] > med["FLY"] > med["POP_UP"]
    anchored = {shape: dict(rows)[0.50]
                for shape, rows in sim.QUALITY_BY_SHAPE.items()}
    assert anchored["LINER"] > anchored["GROUNDER"] > anchored["POP_UP"]
    assert anchored["LINER"] > anchored["FLY"] > anchored["POP_UP"]
