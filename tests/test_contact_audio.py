"""Contact-sound selection guards.

The point of the exit-velocity model is that the sample follows how hard
the ball was hit, not which outcome was rolled. Two behaviours matter
most and are easy to regress:

  * a home run that merely carried must not get the max-crack sample, and
  * fouls must span the ladder instead of playing one fixed sample.

The model is pure, so these run without a mixer.
"""

import random

import pytest

from strikefactor.engine.contact_audio import (
    CONTACT_LADDER,
    EV_CEIL_MPH,
    EV_FLOOR_MPH,
    HOMERUN_MIN_EV_MPH,
    contact_gain,
    contact_sound_for,
    exit_velocity_for_hr_distance,
    exit_velocity_mph,
    pick_contact_sound,
)

ALL_SAMPLES = {name for name, _, _ in CONTACT_LADDER}


def _fixed_rng(seed=0):
    return random.Random(seed)


# ---- EV model -----------------------------------------------------------

@pytest.mark.parametrize("quality", [0.0, 0.15, 0.35, 0.5, 0.75, 0.9, 1.0])
def test_exit_velocity_stays_in_range(quality):
    for seed in range(25):
        ev = exit_velocity_mph(quality, "power", rng=_fixed_rng(seed))
        assert EV_FLOOR_MPH <= ev <= EV_CEIL_MPH


def test_exit_velocity_rises_with_quality():
    """Monotonic on the mean — jitter is averaged out."""
    def mean_ev(q):
        return sum(exit_velocity_mph(q, "contact", rng=_fixed_rng(s))
                   for s in range(200)) / 200

    samples = [mean_ev(q) for q in (0.1, 0.3, 0.5, 0.7, 0.9)]
    assert samples == sorted(samples)
    # And the spread is wide enough to actually move between ladder rungs.
    assert samples[-1] - samples[0] > 25.0


def test_power_swings_outhit_contact_swings_at_equal_quality():
    def mean_ev(swing_type):
        return sum(exit_velocity_mph(0.6, swing_type, rng=_fixed_rng(s))
                   for s in range(200)) / 200

    assert mean_ev("power") > mean_ev("contact")


def test_none_quality_is_treated_as_worst_contact():
    """Fouls can reach the sound path before quality is known."""
    ev = exit_velocity_mph(None, "contact", rng=_fixed_rng(1))
    assert EV_FLOOR_MPH <= ev < 70.0


def test_calibration_reproduces_mlb_exit_velocity_quantiles():
    """The whole point of the calibration table.

    The game's contact_quality is heavily skewed high (median 0.81 over the
    contact the `bat_contact` sweep actually puts in play) because it is only
    computed for swings that squared the ball up. Feeding the observed quality
    quantiles in must yield roughly the MLB exit-velocity quantiles out — if
    this drifts, routine contact starts sounding like a barrel again, or the
    whole distribution goes soft and every ball in play is a little weaker
    than the swing that produced it.

    The quantiles below were last re-derived when the location term in `spray`
    was made to saturate, which released a population of *well-struck* balls
    (the inside-out reach on an outside pitch) back into fair territory from
    an automatic -59 deg foul. The bottom tail lifted and the top barely
    moved. Do not restate them from a uniform sweep of quality: see the
    warning over EV_CALIBRATION.
    """
    # (observed quality quantile, expected MLB EV, tolerance)
    checks = [
        (0.643, 74.0, 4.0),    # p10
        (0.689, 82.0, 4.0),    # p25
        (0.763, 91.0, 4.0),    # p50
        (0.871, 101.0, 4.0),   # p75
        (0.937, 106.0, 4.0),   # p90
    ]
    for quality, expected, tol in checks:
        mean_ev = sum(exit_velocity_mph(quality, "contact", rng=_fixed_rng(s))
                      for s in range(300)) / 300
        assert abs(mean_ev - expected) < tol, (
            f"q={quality} modelled {mean_ev:.1f} mph, expected ~{expected}")


def test_median_contact_does_not_sound_like_a_barrel():
    """Regression on the calibration bug found during implementation.

    With a naive uniform mapping the median contact modelled 111 mph and drew
    the crushed sample about half the time. The median moves whenever the
    contact geometry does — 0.886 for the rectangle, 0.81 for the anisotropic
    bat, 0.763 now — and this test has to move with it or it stops asking
    about the median at all.
    """
    picks = [contact_sound_for(0.763, "contact", ALL_SAMPLES, rng=_fixed_rng(s))[0]
             for s in range(400)]
    crushed_share = picks.count("contact_crushed") / len(picks)
    assert crushed_share < 0.02, f"median contact drew the crushed sample {crushed_share:.0%} of the time"


# ---- Selection ----------------------------------------------------------

def test_crushed_sample_is_gated_behind_hard_contact():
    """The headline fix: a HR that merely carried must not sound scorched."""
    for ev in (70.0, 85.0, 95.0, HOMERUN_MIN_EV_MPH - 0.1):
        picks = {pick_contact_sound(ev, ALL_SAMPLES, rng=_fixed_rng(s))[0]
                 for s in range(60)}
        assert "contact_crushed" not in picks, f"crushed sample leaked at {ev} mph"


def test_crushed_sample_is_reachable_on_scorched_contact():
    picks = {pick_contact_sound(114.0, ALL_SAMPLES, rng=_fixed_rng(s))[0]
             for s in range(60)}
    assert "contact_crushed" in picks


def test_selection_climbs_the_ladder_with_exit_velocity():
    """Weak contact must never reach for a top-rung sample, and vice versa."""
    order = [name for name, _, _ in CONTACT_LADDER]

    def mean_rung(ev):
        idx = [order.index(pick_contact_sound(ev, ALL_SAMPLES, rng=_fixed_rng(s))[0])
               for s in range(120)
               if pick_contact_sound(ev, ALL_SAMPLES, rng=_fixed_rng(s))[0] in order]
        return sum(idx) / len(idx)

    rungs = [mean_rung(ev) for ev in (65.0, 80.0, 92.0, 101.0, 112.0)]
    assert rungs == sorted(rungs)


def test_fouls_span_multiple_samples():
    """The reported bug: every foul used to play one identical sample."""
    picks = set()
    for seed in range(300):
        rng = _fixed_rng(seed)
        quality = rng.random()
        name, _, _ = contact_sound_for(quality, "contact", ALL_SAMPLES, rng=rng)
        picks.add(name)
    assert len(picks) >= 4, f"foul variety collapsed to {picks}"


# ---- Home runs ----------------------------------------------------------

def test_home_runs_never_play_the_two_quietest_samples():
    """Nobody hits a home run off the end of the bat.

    Reported symptom: a soft "medium" crack under a ball that then showed
    460 FT on screen.
    """
    quiet = {"contact_weak", "contact_medium"}
    for distance in range(320, 500, 10):
        for quality in (0.0, 0.3, 0.5, 0.7, 1.0):
            picks = {contact_sound_for(quality, "power", ALL_SAMPLES,
                                       rng=_fixed_rng(s),
                                       hr_distance_ft=distance)[0]
                     for s in range(20)}
            leaked = picks & quiet
            assert not leaked, f"{distance} ft HR played {leaked}"


def test_hr_exit_velocity_follows_the_distance_not_the_quality():
    """The fix: distance drives the sound, so what you hear matches the FT."""
    # Same mediocre quality, wildly different carry.
    _, _, short_ev = contact_sound_for(0.5, "power", ALL_SAMPLES,
                                       rng=_fixed_rng(0), hr_distance_ft=335)
    _, _, long_ev = contact_sound_for(0.5, "power", ALL_SAMPLES,
                                      rng=_fixed_rng(0), hr_distance_ft=465)
    assert long_ev > short_ev + 10.0


def test_hr_distance_to_ev_is_monotonic_and_bounded():
    evs = [exit_velocity_for_hr_distance(d) for d in range(300, 520, 10)]
    assert evs == sorted(evs)
    assert all(90.0 <= ev <= EV_CEIL_MPH for ev in evs)
    assert exit_velocity_for_hr_distance(None) is None


def test_a_moonshot_sounds_crushed():
    picks = [contact_sound_for(0.5, "power", ALL_SAMPLES, rng=_fixed_rng(s),
                               hr_distance_ft=470)[0] for s in range(200)]
    assert picks.count("contact_crushed") / len(picks) > 0.4


def test_a_wall_scraper_does_not_sound_crushed():
    """The floor must not collapse into 'home runs are always loudest'."""
    picks = [contact_sound_for(0.9, "power", ALL_SAMPLES, rng=_fixed_rng(s),
                               hr_distance_ft=335)[0] for s in range(200)]
    assert picks.count("contact_crushed") == 0
    assert "contact_solid" in picks


def test_min_sample_floor_is_respected_directly():
    for ev in (55.0, 70.0, 85.0, 95.0):
        picks = {pick_contact_sound(ev, ALL_SAMPLES, rng=_fixed_rng(s),
                                    min_sample="contact_solid")[0]
                 for s in range(40)}
        assert picks <= {"contact_solid", "contact_hard", "contact_crushed"}


def test_non_home_run_contact_keeps_the_full_ladder():
    """The floor is HR-only — weak contact in play must still sound weak."""
    picks = {contact_sound_for(0.15, "contact", ALL_SAMPLES, rng=_fixed_rng(s))[0]
             for s in range(200)}
    assert picks & {"contact_weak", "contact_medium"}


def test_missing_assets_degrade_instead_of_going_silent():
    """A trimmed asset set must still yield a playable sample."""
    available = {"contact_medium"}
    for ev in (55.0, 75.0, 95.0, 115.0):
        name, gain = pick_contact_sound(ev, available, rng=_fixed_rng(0))
        assert name == "contact_medium"
        assert 0.0 <= gain <= 1.0


def test_empty_asset_set_still_returns_a_name():
    name, gain = pick_contact_sound(95.0, set(), rng=_fixed_rng(0))
    assert isinstance(name, str) and name
    assert 0.0 <= gain <= 1.0


# ---- Gain ---------------------------------------------------------------

def test_gain_is_monotonic_and_bounded():
    gains = [contact_gain(ev) for ev in range(40, 130, 5)]
    assert gains == sorted(gains)
    assert all(0.0 < g <= 1.0 for g in gains)
    # Soft contact must be audibly quieter than a barrel.
    assert contact_gain(60.0) < contact_gain(110.0) - 0.3
