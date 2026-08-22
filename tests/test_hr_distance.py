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
import random
import statistics

import pytest

from strikefactor.gameplay.hit_animation import (
    FOUL_LINE_SCREEN_LEFT_RAD,
    FOUL_LINE_SCREEN_RIGHT_RAD,
    HOME,
    HR_DISTANCE_FADE_MS,
    HR_DISTANCE_REVEAL_DELAY_MS,
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


def _home_run(quality, hand="R", spray_deg=None):
    """A home run at a given contact quality.

    `spray_deg` is the ball's bearing, pull-positive (see `spray`). It replaced
    an `inside` argument that was the *pitch's* inside/outside location in
    screen pixels — the animation no longer knows or cares where the pitch was,
    only where the bat was pointing when it met it. `None` samples the same
    spread of bearings a real swing produces, which is what the distribution
    tests below want.
    """
    if spray_deg is None:
        spray_deg = random.gauss(8.0, 20.0)
    return HitAnimation(
        _StubGame(hand),
        outcome="HOME RUN",
        on_complete=lambda: None,
        vertical_offset=3.0,
        quality=quality,
        batted_ball_type=None,
        spray_deg=spray_deg,
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


def _play_to(anim, elapsed_ms, step=16):
    """Drive one animation out to `elapsed_ms`, yielding every frame."""
    t = 0
    while t < elapsed_ms:
        t += step
        anim.update(t)
        yield t


def test_the_distance_is_not_revealed_until_the_ball_is_down():
    """The suspense is the point: the number used to fade in at 70% of the
    flight, answering the only question the flight is asking while the ball
    was still on its way to the wall."""
    anim = _home_run(0.9)
    for t in _play_to(anim, anim.duration_ms):
        assert anim._hr_distance_alpha() == 0.0, f"readout showing at {t} ms, mid-flight"


def test_the_distance_appears_after_the_landing_beat():
    anim = _home_run(0.9)
    reveal = anim.duration_ms + HR_DISTANCE_REVEAL_DELAY_MS
    for _t in _play_to(anim, reveal - 20):
        pass
    assert anim._hr_distance_alpha() == 0.0, "revealed before the beat elapsed"

    for _t in _play_to(anim, reveal + HR_DISTANCE_FADE_MS + 20):
        pass
    assert anim._hr_distance_alpha() == 1.0, "readout never reached full opacity"


def test_the_ball_is_already_out_of_sight_when_the_number_lands():
    """The two halves of the reveal agree: the ball drops behind the fence,
    then the number appears into an empty outfield. If the delay were ever
    shortened past the flight, the number would land on top of a ball still
    in the air."""
    for _ in range(10):
        anim = _home_run(0.9)
        for _t in _play_to(anim, anim.duration_ms + HR_DISTANCE_REVEAL_DELAY_MS + 16):
            pass
        assert anim._hr_distance_alpha() > 0.0
        assert anim._ball_behind_wall(), "number revealed with the ball still visible"
