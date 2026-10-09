"""Home-run distance and spray guards.

These numbers used to run 392-476 ft with a mean of 423 — every home run a
no-doubter — because the landing angle was clamped to 50-130 degrees of
screen angle, well inside the foul lines at ~30.7/149.3, so the corners
(where the wall is nearest) were unreachable. Carry was also specified in
pixels, which buys 17% more feet at centre field than down the line.

**A home run is not rolled any more**, and that changes what this file can
usefully assert. `park.fence_verdict` decides it — is this flight higher than
the fence when it reaches the fence's own distance — and the landing is the
carry `ball_flight` gives the same launch angle and exit velocity. So the
distance distribution is no longer a thing to tune; it is a *consequence*, and
these bounds measure it rather than pin the roll that used to produce it.

The sample is built the way the game builds one: contacts drawn from the shared
batter, kept only when the fence clears them. It used to sweep contact quality
from 0.5 to 1.0 and assert HOME RUN directly, which was all that was available
while the outcome came out of a quality-indexed table — and over half of that
population was contact that could not have left any park.

**The park is deep, and it shows up here.** `park.wall_distance_ft` runs 360 ft
down the lines to 400 to centre, against an MLB norm of 325-335 down the line,
so a sub-360 ft home run is geometrically impossible and the whole distribution
sits ~20 ft right of MLB's. That is the drawn field's geometry, not this
model's; see the note in `park.py`.

Bounds are deliberately loose: this guards against drifting back to "every
homer is a moonshot", not any exact distribution.
"""

import math
import random
import statistics

import conftest
import pytest

from strikefactor.engine import contact_audio
from strikefactor.gameplay import park, spray
from strikefactor.gameplay.hit_animation import (
    FOUL_LINE_SCREEN_LEFT_RAD,
    FOUL_LINE_SCREEN_RIGHT_RAD,
    HOME,
    HR_DISTANCE_FADE_MS,
    HR_DISTANCE_REVEAL_DELAY_MS,
    HitAnimation,
    _screen_angle_of,
)

N = 400


class _StubBatter:
    def __init__(self, hand):
        self._hand = hand

    def get_handedness(self):
        return self._hand


class _StubGame:
    def __init__(self, hand="R"):
        self.batter = _StubBatter(hand)


def _home_run(quality, hand="R", spray_deg=None, launch_deg=None, ev_mph=None):
    """One home run, built the way `PitchSimulation` builds one.

    `launch_deg` and `ev_mph` are this ball's flight; the animation takes both
    rather than deriving them, because each is drawn once upstream. Omitting
    them falls back to the shape's band centre and a quality-derived exit
    velocity, which is what a caller predating the carried flight meant.
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
        launch_deg=launch_deg,
        ev_mph=ev_mph,
    )


def _draw_home_runs(count, hand="R", seed=20260910):
    """`count` home runs, drawn from the shared batter and cleared by the fence.

    The swing type alternates because a power swing is worth
    `contact_audio.EV_POWER_BONUS_MPH` of exit velocity and therefore real
    carry — sampling only one of them would measure half the game.
    """
    rng = random.Random(seed)
    out = []
    while len(out) < count:
        quality, launch, _shape = conftest.realistic_contact(rng)
        deg = conftest.realistic_spray(rng)
        swing = "power" if len(out) % 2 else "contact"
        ev = contact_audio.exit_velocity_mph(quality, swing, rng=rng)
        field_rad = spray.field_angle_rad(deg, spray.spin_for(hand))
        if park.fence_verdict(launch, ev, field_rad) != park.OUT_OF_PARK:
            continue
        out.append(_home_run(quality, hand, spray_deg=deg,
                             launch_deg=launch, ev_mph=ev))
    return out


@pytest.fixture(scope="module")
def sample():
    anims = _draw_home_runs(N)
    dists = sorted(a.hr_distance_ft for a in anims)
    angles = [math.degrees(math.atan2(HOME[1] - a._hit_end[1],
                                      a._hit_end[0] - HOME[0]))
              for a in anims]
    return dists, angles


def _pct(values, p):
    return values[min(len(values) - 1, int(len(values) * p))]


def test_mean_home_run_distance_is_mlb_realistic(sample):
    """MLB averages ~400 ft. This was 423 before the first recalibration.

    The band sits high of MLB's because the park does: nothing here can land
    inside 360 ft, so the left tail MLB has is missing by construction.
    """
    dists, _ = sample
    assert 400 <= statistics.fmean(dists) <= 445


def test_median_home_run_distance_is_mlb_realistic(sample):
    dists, _ = sample
    assert 400 <= _pct(dists, 0.50) <= 445


def test_moonshots_are_rare(sample):
    """~5% of MLB home runs clear 440 ft. It was 21%.

    Higher than MLB for the same reason the mean is: with a 360 ft floor the
    whole distribution is shifted right, so the share past a fixed 440 ft line
    is not comparable to MLB's without shifting the line too.
    """
    dists, _ = sample
    over_440 = sum(1 for d in dists if d > 440) / len(dists)
    assert over_440 < 0.40, f"{over_440:.0%} of home runs cleared 440 ft"


def test_no_absurd_distances(sample):
    dists, _ = sample
    assert dists[-1] < 520, f"longest home run was {dists[-1]} ft"
    # Nothing may land short of the wall — it would not be a home run.
    assert dists[0] > 355, f"shortest home run was {dists[0]} ft"


def test_home_runs_reach_both_corners(sample):
    """The old clamp made corner home runs geometrically impossible."""
    _, angles = sample
    assert min(angles) < 55.0, f"nothing pulled to the RF corner (min {min(angles):.0f}deg)"
    assert max(angles) > 125.0, f"nothing to the LF corner (max {max(angles):.0f}deg)"


def test_spray_leans_to_the_pull_side():
    """A right-hander's home runs still favour left field.

    Measured on the bearings alone, at a sample size this property can actually
    be seen at, rather than off the `sample` fixture. The lean is genuinely
    small — `conftest.SPRAY_MEAN_DEG` is +1.25 degrees against a spread of 21 —
    so at the few hundred animations the fixture can afford the standard error
    on the mean is about a degree and the sign of the difference is noise. This
    seed's first 400 come out at -1.6 degrees; its first 5,000 at +1.3.

    A property that needs 5,000 draws to see is still a property; asserting it
    off 400 is asserting a coin flip.
    """
    rng = random.Random(4242)
    kept = []
    while len(kept) < 5000:
        quality, launch, _shape = conftest.realistic_contact(rng)
        deg = conftest.realistic_spray(rng)
        ev = contact_audio.exit_velocity_mph(
            quality, "power" if len(kept) % 2 else "contact", rng=rng)
        if park.fence_verdict(
                launch, ev, spray.field_angle_rad(deg, 1.0)) == park.OUT_OF_PARK:
            kept.append(deg)
    # Six degrees of spray is where a screen bearing crosses 100/80 degrees.
    pull = sum(1 for d in kept if d > 6.0)
    oppo = sum(1 for d in kept if d < -6.0)
    assert pull > oppo, f"{pull} pulled against {oppo} the other way"


def test_landing_angles_stay_inside_the_foul_poles(sample):
    _, angles = sample
    lo = math.degrees(FOUL_LINE_SCREEN_RIGHT_RAD)
    hi = math.degrees(FOUL_LINE_SCREEN_LEFT_RAD)
    assert min(angles) >= lo, f"{min(angles):.1f} deg is foul of the RF pole"
    assert max(angles) <= hi, f"{max(angles):.1f} deg is foul of the LF pole"


def test_the_home_run_flies_the_bearing_the_bat_gave_it():
    """No jitter, no rejection sampling — the swing already decided this.

    `_sample_hr_angle` used to scatter the landing 7 degrees around the swing's
    own bearing, rejection-sampled against the poles. It was the last place in
    the animation that re-drew a direction the bat had given, and it had to go
    once the fence decided home runs: the park is 40 ft deeper to centre than
    down the line, so a bearing jittered inward could put a ball the fence
    verdict had certified as gone back in front of the fence.

    Replaces `test_angle_sampling_does_not_pile_up_on_the_boundary`, whose
    subject no longer exists.
    """
    for deg in (-38.0, -20.0, -5.0, 0.0, 5.0, 20.0, 38.0):
        anim = _home_run(0.95, spray_deg=deg, launch_deg=30.0, ev_mph=108.0)
        landed = math.atan2(HOME[1] - anim._hit_end[1],
                            anim._hit_end[0] - HOME[0])
        assert landed == pytest.approx(
            _screen_angle_of(anim.spray_field_rad), abs=math.radians(1.0)), (
            f"spray {deg} deg landed at {math.degrees(landed):.1f} deg screen")


def test_the_distance_is_the_carry_the_flight_model_gives():
    """The readout, the fence verdict and the physics are one number.

    Measured off the landing point (`hr_distance_ft`), which is placed at
    `ball_flight.carry_distance_ft` — the same call `park.fence_verdict` made
    upstream to decide this was a home run at all. Before this the carry past
    the fence was `random.random() ** 3.5` scaled by contact quality, so the
    distance a player read had nothing to do with how hard they hit the ball.
    """
    from strikefactor.gameplay import ball_flight
    for launch, ev in ((28.0, 108.0), (32.0, 112.0), (35.0, 105.0)):
        anim = _home_run(0.9, spray_deg=6.0, launch_deg=launch, ev_mph=ev)
        assert anim.hr_distance_ft == pytest.approx(
            ball_flight.carry_distance_ft(launch, ev), abs=2.0)


def test_a_home_run_reports_the_velocity_it_was_flown_at():
    """EXIT and DISTANCE are drawn side by side in the review stack, and they
    have to describe one flight.

    They did not. `PitchSimulation` handed the landing distance to the contact
    sound, took an exit velocity back out of it through a six-row table with no
    launch-angle term, and wrote that over `sim.exit_velocity_mph` — which is
    what `SwingRecord` carries into the swing replay's EXIT VELO and what the
    DB records. `FieldingRecord` takes the *animation's* copy, which was never
    overwritten, so `review_views` drew a different number for the same home
    run, a few pixels from the distance the round trip had come out of.

    Deterministic, and wrong by the launch angle alone: 112 mph at 20 degrees
    carries 412 ft and read back 105.6; 95 mph at 40 degrees carries 370 ft and
    read back 101.0. Swept across the launch range here for that reason — the
    table's error changes sign somewhere in the middle of it, so a single
    angle could have been picked that looked fine.

    The three flights all clear the fence at this bearing on their own carry;
    a ball that does not is floored onto `HR_MIN_CLEARANCE_FT` and would be
    testing that floor rather than the physics.
    """
    from strikefactor.gameplay import ball_flight
    for launch, ev in ((22.0, 114.0), (30.0, 106.0), (38.0, 108.0)):
        anim = _home_run(0.9, spray_deg=6.0, launch_deg=launch, ev_mph=ev)
        assert anim.exit_velocity_mph == ev
        # ...and the distance beside it is that same velocity's carry, so the
        # two readouts cannot be describing two different balls.
        assert anim.hr_distance_ft == pytest.approx(
            ball_flight.carry_distance_ft(launch, ev), abs=2.0)


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
        # A frame past the reveal, not the reveal instant itself. `duration_ms`
        # is the ball's own flight time now rather than a scripted 5000, so it
        # no longer sits at a fixed offset from the 16 ms step grid, and landing
        # exactly on the reveal returns an alpha of 0.0 by definition.
        for _t in _play_to(anim, anim.duration_ms + HR_DISTANCE_REVEAL_DELAY_MS
                           + HR_DISTANCE_FADE_MS):
            pass
        assert anim._hr_distance_alpha() > 0.0
        assert anim._ball_behind_wall(), "number revealed with the ball still visible"
