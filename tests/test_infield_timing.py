"""The infield play as a race between the throw and the runner.

These pin the model to the sourced MLB figures (see
docs/infield-timing-refactor.md §3) and to the qualitative facts that make
an infield hit an infield hit — the slow roller beaten out, the left-handed
batter's half-step, the backhand in the hole.

Bands rather than point values: the underlying figures are league averages
with real spread, and a test that pins 1.44 s exactly would fail on any
honest recalibration while catching nothing.
"""

import random

import pytest

from strikefactor.gameplay import infield_timing as it

# ---- Ball to the fielder --------------------------------------------------

@pytest.mark.parametrize("ev_mph, distance_ft, lo, hi", [
    (95.0, 140.0, 1.30, 1.50),      # scorched to a normally-positioned IF
    (87.0, 140.0, 1.55, 1.85),      # medium
    (45.0, 110.0, 2.50, 3.50),      # topped chopper toward third
])
def test_ball_travel_matches_the_reference_table(ev_mph, distance_ft, lo, hi):
    assert lo <= it.ball_travel_time_s(ev_mph, distance_ft) <= hi


def test_a_grounder_never_travels_at_its_exit_velocity():
    """It bleeds most of its speed to the first bounce and to friction.
    Using EV directly would put every grounder in the fielder's glove
    roughly a second early and make infield hits impossible."""
    ev = 95.0
    naive = 140.0 / (ev * it.MPH_TO_FTS)
    assert it.ball_travel_time_s(ev, 140.0) > naive * 1.3


def test_weak_contact_loses_proportionally_more_speed():
    """The curve is not a constant fraction of EV — a topped ball dies,
    a scorched one skips. That difference is the whole reason the slow
    roller is the canonical infield hit."""
    assert (it._interpolate(45.0, it.GROUND_SPEED_RETENTION)
            < it._interpolate(100.0, it.GROUND_SPEED_RETENTION))


# ---- Runner ---------------------------------------------------------------

def test_league_average_runner_is_the_max_effort_figure():
    """4.30 s, not Statcast's 4.62 — that average includes jogs on obvious
    outs, and our batter is always running out a close play."""
    assert it.home_to_first_s("R", 27.0) == pytest.approx(4.30, abs=0.02)


def test_left_handed_batters_get_their_half_step():
    for v in (23.0, 27.0, 30.0):
        assert (it.home_to_first_s("R", v) - it.home_to_first_s("L", v)
                == pytest.approx(it.LHB_HOME_TO_FIRST_BONUS_S, abs=1e-6))


def test_sprint_speed_is_not_treated_as_an_average_speed():
    """The trap this mapping exists to avoid. Sprint Speed is a top-speed
    metric over the fastest one-second window, so dividing 90 ft by it
    gives 3.33 s against a real 4.30 s — a runner averages ~77% of top
    speed over the distance."""
    naive = 90.0 / it.SPRINT_SPEED_LEAGUE_FTS
    assert naive < 3.5                                   # the wrong answer
    assert it.home_to_first_s("R", it.SPRINT_SPEED_LEAGUE_FTS) > 4.0


def test_faster_runners_reach_first_sooner_within_realistic_bounds():
    elite, league, slow = (it.home_to_first_s("R", v) for v in (30.0, 27.0, 23.0))
    assert elite < league < slow
    assert 3.7 <= elite <= 4.0        # Buxton's 3.72 is the record
    assert 4.7 <= slow <= 5.0


def test_runner_time_is_clamped_against_absurd_speeds():
    assert it.home_to_first_s("R", 99.0) >= it.HOME_TO_FIRST_MIN_S
    assert it.home_to_first_s("R", 1.0) <= it.HOME_TO_FIRST_MAX_S


def test_difficulty_enters_as_time_not_as_a_probability():
    """Difficulty moves the runner's clock, which is inspectable and
    composes with the physics, instead of scaling the verdict."""
    base = it.home_to_first_s("R", 27.0)
    assert it.home_to_first_s("R", 27.0, difficulty_offset_s=-0.25) < base
    assert it.home_to_first_s("R", 27.0, difficulty_offset_s=+0.15) > base


# ---- Throw ----------------------------------------------------------------

def test_throw_flight_times_match_the_reference_distances():
    # A shortstop at normal depth is ~120-135 ft from first.
    ss = it.throw_time_s((-40.0, 135.0))
    assert 1.05 <= ss <= 1.30
    # A second baseman is much closer.
    second = it.throw_time_s((48.0, 140.0))
    assert 0.60 <= second <= 0.85
    assert second < ss


def test_a_fielder_on_the_bag_does_not_throw():
    assert it.throw_time_s(it.FIRST_BASE_FT) == 0.0


def test_effective_throw_speed_is_not_release_velocity():
    """Statcast arm strength is the average of a player's top 5% of
    throws — max effort. Using 90 mph (132 ft/s) as the flight average
    would shave a tenth off every throw across the diamond."""
    max_effort_fts = 90.0 * it.MPH_TO_FTS
    assert it.THROW_EFFECTIVE_FTS < max_effort_fts
    assert 100.0 <= it.THROW_EFFECTIVE_FTS <= 118.0


# ---- Release --------------------------------------------------------------

def test_charging_a_slow_roller_is_faster_than_a_set_throw():
    """Counterintuitive but real: the fielder is already moving toward
    first. Modelling the charge as *slower* would delete the play where a
    third baseman barehands a chopper and gets the runner."""
    assert it.release_time_s(is_charging=True) < it.release_time_s(ranging_ft=0.0)


def test_ranging_costs_release_time_up_to_a_ceiling():
    routine = it.release_time_s(ranging_ft=0.0)
    stretched = it.release_time_s(ranging_ft=it.RELEASE_STRETCH_FT)
    assert routine < stretched
    assert it.release_time_s(ranging_ft=200.0) == pytest.approx(stretched, abs=1e-6)


def test_release_jitter_is_opt_in_so_timings_are_reproducible():
    """No rng passed means no randomness consumed — the timing can be
    computed for display or logging without perturbing the play."""
    a = it.release_time_s(ranging_ft=5.0)
    b = it.release_time_s(ranging_ft=5.0)
    assert a == b


# ---- The verdict ----------------------------------------------------------

def test_a_dead_heat_is_a_coin_flip():
    assert it.p_out_from_margin(0.0) == pytest.approx(0.5)


def test_a_tenth_of_a_second_is_not_a_certainty():
    """The reason the verdict is a logistic and not a threshold. A
    bang-bang play should feel like one."""
    p = it.p_out_from_margin(0.10)
    assert 0.65 <= p <= 0.85


def test_the_verdict_is_monotonic_and_saturates_without_overflowing():
    ps = [it.p_out_from_margin(m) for m in (-3.0, -0.5, -0.1, 0.0, 0.1, 0.5, 3.0)]
    assert ps == sorted(ps)
    assert ps[0] == pytest.approx(0.0, abs=1e-6)
    assert ps[-1] == pytest.approx(1.0, abs=1e-6)
    assert it.p_out_from_margin(1e6) == 1.0        # no math.exp OverflowError
    assert it.p_out_from_margin(-1e6) == 0.0


# ---- The plays the model exists to produce --------------------------------

def _play(**kw):
    base = dict(ev_mph=92.0, fielder_xy_ft=(-40.0, 135.0), ball_distance_ft=140.0,
                ranging_ft=4.0, is_charging=False, handedness="R", sprint_fts=27.0)
    base.update(kw)
    return it.resolve_infield_play(**base)


def test_a_routine_grounder_is_comfortably_an_out():
    t = _play()
    assert t.p_out > 0.95
    assert not t.is_bang_bang


def test_a_slow_roller_is_far_more_likely_a_hit_than_a_scorched_one():
    """The sign flip that proves the timing model is doing the work. Under
    the old geometric test the slow roller was converted MORE often,
    because dawdling to the fielder gave them more time to get there."""
    scorched = _play(ev_mph=104.0)
    roller = _play(ev_mph=45.0, ball_distance_ft=100.0,
                   fielder_xy_ft=(-52.0, 82.0), ranging_ft=25.0, is_charging=True)
    assert roller.p_out < scorched.p_out
    assert roller.ball_to_glove_s > scorched.ball_to_glove_s


def test_the_same_play_is_closer_for_a_fast_left_handed_batter():
    right = _play(ev_mph=60.0, ball_distance_ft=120.0)
    left = _play(ev_mph=60.0, ball_distance_ft=120.0, handedness="L", sprint_fts=30.0)
    assert left.p_out < right.p_out


def test_ranging_into_the_hole_turns_an_out_into_a_close_play():
    routine = _play()
    hole = _play(fielder_xy_ft=(-78.0, 140.0), ball_distance_ft=160.0, ranging_ft=30.0)
    assert hole.p_out < routine.p_out
    assert hole.defense_s > routine.defense_s


def test_the_components_account_for_the_whole_defensive_clock():
    t = _play()
    assert t.defense_s == pytest.approx(
        t.ball_to_glove_s + t.release_s + t.throw_flight_s)
    assert t.margin_s == pytest.approx(t.runner_s - t.defense_s)


def test_resolving_a_play_consumes_no_randomness():
    """Timing is deterministic; only `roll_verdict` samples. That keeps the
    displayed numbers and the verdict derivable from the same inputs."""
    random.seed(1)
    before = random.random()
    random.seed(1)
    _play()
    assert random.random() == before


def test_rolling_the_verdict_respects_the_probability():
    t = _play(ev_mph=45.0, ball_distance_ft=100.0)
    rng = random.Random(0)
    outs = sum(it.roll_verdict(t, rng) == "OUT" for _ in range(4000))
    assert abs(outs / 4000 - t.p_out) < 0.03
