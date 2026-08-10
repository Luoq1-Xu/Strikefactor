"""Home-run distance and spray guards.

These numbers used to run 392-476 ft with a mean of 423 — every home run a
no-doubter — because the landing angle was clamped to 50-130 degrees of
screen angle, well inside the foul lines at ~30.7/149.3, so the corners
(where the wall is nearest) were unreachable. Carry was also specified in
pixels, which buys 17% more feet at centre field than down the line.

Bounds are deliberately loose: this guards the calibration against drifting
back to "every homer is a moonshot", not any exact distribution.
"""

import math
import statistics

import pytest

from strikefactor.gameplay.hit_animation import (
    FOUL_LINE_SCREEN_LEFT_RAD,
    FOUL_LINE_SCREEN_RIGHT_RAD,
    HOME,
    HR_FOUL_MARGIN_RAD,
    HitAnimation,
    _px_per_ft_at,
    _sample_hr_angle,
    _wall_r_at,
)

N = 600


class _StubBatter:
    def __init__(self, hand):
        self._hand = hand

    def get_handedness(self):
        return self._hand


class _StubGame:
    def __init__(self, hand="R"):
        self.batter = _StubBatter(hand)


def _home_run(quality, hand="R", inside=0.0):
    return HitAnimation(
        _StubGame(hand),
        outcome="HOME RUN",
        on_complete=lambda: None,
        vertical_offset=3.0,
        quality=quality,
        batted_ball_type=None,
        horizontal_inside=inside,
    )


@pytest.fixture(scope="module")
def sample():
    anims = [_home_run(0.5 + 0.5 * (i % 100) / 99.0) for i in range(N)]
    dists = sorted(a.hr_distance_ft for a in anims)
    angles = [math.degrees(math.atan2(HOME[1] - a._hit_end[1],
                                      a._hit_end[0] - HOME[0]))
              for a in anims]
    return dists, angles


def _pct(values, p):
    return values[min(len(values) - 1, int(len(values) * p))]


def test_mean_home_run_distance_is_mlb_realistic(sample):
    """MLB averages ~400 ft. This was 423 before the recalibration."""
    dists, _ = sample
    assert 385 <= statistics.fmean(dists) <= 420


def test_median_home_run_distance_is_mlb_realistic(sample):
    dists, _ = sample
    assert 385 <= _pct(dists, 0.50) <= 415


def test_moonshots_are_rare(sample):
    """~5% of MLB home runs clear 440 ft. It was 21%."""
    dists, _ = sample
    over_440 = sum(1 for d in dists if d > 440) / len(dists)
    assert over_440 < 0.15, f"{over_440:.0%} of home runs cleared 440 ft"


def test_no_absurd_distances(sample):
    dists, _ = sample
    assert dists[-1] < 500, f"longest home run was {dists[-1]} ft"
    # Nothing may land short of the wall — it would not be a home run.
    assert dists[0] > 350, f"shortest home run was {dists[0]} ft"


def test_home_runs_reach_both_corners(sample):
    """The old clamp made corner home runs geometrically impossible."""
    _, angles = sample
    assert min(angles) < 55.0, f"nothing pulled to the RF corner (min {min(angles):.0f}deg)"
    assert max(angles) > 125.0, f"nothing to the LF corner (max {max(angles):.0f}deg)"


def test_spray_leans_to_the_pull_side(sample):
    """RHB with a centred pitch should still favour left field."""
    _, angles = sample
    pull = sum(1 for a in angles if a > 100)
    oppo = sum(1 for a in angles if a < 80)
    assert pull > oppo


def test_landing_angles_stay_inside_the_foul_poles(sample):
    _, angles = sample
    lo = math.degrees(FOUL_LINE_SCREEN_RIGHT_RAD + HR_FOUL_MARGIN_RAD)
    hi = math.degrees(FOUL_LINE_SCREEN_LEFT_RAD - HR_FOUL_MARGIN_RAD)
    assert min(angles) >= lo - 0.01
    assert max(angles) <= hi + 0.01


def test_angle_sampling_does_not_pile_up_on_the_boundary():
    """Rejection sampling, not clamping.

    A clamp would stack every out-of-range draw onto the two boundary
    angles — a visible line of home runs landing on the foul poles.
    """
    lo = FOUL_LINE_SCREEN_RIGHT_RAD + HR_FOUL_MARGIN_RAD
    hi = FOUL_LINE_SCREEN_LEFT_RAD - HR_FOUL_MARGIN_RAD
    angles = [_sample_hr_angle(math.radians(97)) for _ in range(3000)]
    at_edge = sum(1 for a in angles
                  if abs(a - lo) < 1e-6 or abs(a - hi) < 1e-6)
    assert at_edge / len(angles) < 0.01, "angles are piling up on the clamp"
    assert all(lo <= a <= hi for a in angles)


def test_carry_in_feet_is_angle_independent():
    """A foot of carry must be a foot everywhere on the field.

    Carry used to be specified in pixels, which is worth ~0.78 ft down the
    line and ~0.91 ft to centre — the same constant bought 17% more
    distance to centre field.
    """
    for deg in (35, 60, 90, 120, 145):
        angle = math.radians(deg)
        wall_r = _wall_r_at(angle)
        carry_ft = 25.0
        landed_r = wall_r + carry_ft * _px_per_ft_at(angle)

        def to_ft(r):
            return r * math.hypot(math.cos(angle) / 1.85,
                                  math.sin(angle) / 1.10)

        assert to_ft(landed_r) - to_ft(wall_r) == pytest.approx(carry_ft, abs=0.01)
