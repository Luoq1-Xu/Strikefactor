"""The fence, and the one question asked of it.

Whether a ball left the park used to be a quality-indexed probability in
`hit_outcome_manager` that could not see how far the ball was about to be
flown, while `ball_flight` was separately computing exactly that. One batted
ball, two models, and at the median they disagreed *systematically*: a line
drive carrying 241 ft was given a 9.8% chance of clearing a fence no nearer
than 360 ft, and a fly carrying 327 ft got 25.9%.

`park.fence_verdict` is the replacement, and these are the properties that make
it a single model rather than a third one.
"""

import math

import pytest

from strikefactor.gameplay import ball_flight, park
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.hit_animation import HOME, HitAnimation


class _StubBatter:
    def get_handedness(self):
        return "R"


class _StubGame:
    batter = _StubBatter()


# ---- The wall itself -------------------------------------------------------

def test_the_wall_runs_360_down_the_lines_to_400_to_centre():
    """The park's actual dimensions, which are not its two semi-axes.

    `FOUL_LINE_SEMI_FT` is the ellipse's semi-axis at a bearing of 0 degrees,
    out in foul territory. Fair territory starts at 45, where the wall measures
    360 ft — deep by MLB standards (325-335 down the line), which is why a
    sub-360 ft home run is geometrically impossible here.
    """
    assert park.wall_distance_ft(math.radians(45)) == pytest.approx(360.0, abs=0.5)
    assert park.wall_distance_ft(math.radians(135)) == pytest.approx(360.0, abs=0.5)
    assert park.wall_distance_ft(math.radians(90)) == pytest.approx(400.0, abs=0.5)
    # Symmetric, and deepest at centre.
    for deg in (50, 60, 75):
        assert park.wall_distance_ft(math.radians(deg)) == pytest.approx(
            park.wall_distance_ft(math.radians(180 - deg)), abs=1e-6)
        assert (park.wall_distance_ft(math.radians(deg))
                < park.wall_distance_ft(math.radians(90)))


def test_the_drawn_wall_is_the_wall_the_verdict_uses():
    """One fence, not two.

    `hit_animation` derives its render semi-axes from these constants, and an
    ellipse scaled along its own axes is still that ellipse — so the polar
    radius the animation draws and `wall_distance_ft` agree at every bearing by
    construction rather than by coincidence. They were two independent pairs of
    numbers before, and the verdict had no access to either.
    """
    assert ha.WALL_SEMI_X == park.FOUL_LINE_SEMI_FT * ha.FT_TO_PX_X
    assert ha.WALL_SEMI_Y == park.CENTRE_FIELD_FT * ha.FT_TO_PX_Y
    for deg in (45, 60, 90, 120, 135):
        field_rad = math.radians(deg)
        screen_rad = math.atan2(math.sin(field_rad) * ha.FT_TO_PX_Y,
                                math.cos(field_rad) * ha.FT_TO_PX_X)
        drawn_px = ha._wall_r_at(screen_rad)
        drawn_ft = drawn_px * math.hypot(math.cos(screen_rad) / ha.FT_TO_PX_X,
                                         math.sin(screen_rad) / ha.FT_TO_PX_Y)
        assert drawn_ft == pytest.approx(park.wall_distance_ft(field_rad), rel=1e-9)


# ---- The verdict -----------------------------------------------------------

def test_a_ground_ball_never_leaves_the_park_without_a_special_case():
    """`height_at_distance_ft` goes negative past the carry, so nothing struck
    into the dirt is above a fence 360 ft away — no shape check needed."""
    for ev in (60.0, 90.0, 115.0):
        for launch in (-10.0, 0.0, 5.0, 9.0):
            assert park.fence_verdict(
                launch, ev, math.radians(90)) == park.SHORT_OF_WALL


def test_the_three_verdicts_are_ordered_in_exit_velocity():
    """Hit the same ball harder and it goes further: short, then off the wall,
    then out. The middle state is what makes a wall ball a consequence of the
    physics rather than a separate roll."""
    field_rad = math.radians(90)
    seen = []
    for ev in [60.0 + 0.25 * i for i in range(240)]:
        v = park.fence_verdict(30.0, ev, field_rad)
        if not seen or seen[-1] != v:
            seen.append(v)
    assert seen == [park.SHORT_OF_WALL, park.OFF_THE_WALL, park.OUT_OF_PARK], seen


def test_the_same_flight_clears_down_the_line_and_not_to_centre():
    """40 ft of park is worth a home run, and it is why the bearing is an
    argument. The old scalar `WALL_REACH_FT = 380` could not express this."""
    for launch, ev in ((30.0, 101.0), (28.0, 103.0)):
        down_the_line = park.fence_verdict(launch, ev, math.radians(46))
        to_centre = park.fence_verdict(launch, ev, math.radians(90))
        if down_the_line == park.OUT_OF_PARK:
            assert to_centre != park.OUT_OF_PARK, (
                f"{launch} deg / {ev} mph cleared everywhere; not a discriminating case")
            break
    else:
        pytest.fail("no flight distinguished the line from centre field")


def test_a_ball_that_only_just_clears_is_barely_over_the_fence():
    """The verdict is a *height* test, not a distance test.

    A ball whose carry equals the wall distance lands at the foot of it, which
    is off the wall and not out; it has to be `FENCE_HEIGHT_FT` up to be gone.
    """
    field_rad = math.radians(75)
    wall = park.wall_distance_ft(field_rad)
    launch = 30.0
    # The exit velocity whose carry is exactly the wall distance.
    lo, hi = 60.0, 160.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if ball_flight.carry_distance_ft(launch, mid) < wall:
            lo = mid
        else:
            hi = mid
    assert park.fence_verdict(launch, hi, field_rad) == park.OFF_THE_WALL
    assert ball_flight.height_at_distance_ft(
        launch, ball_flight.carry_distance_ft(launch, hi), wall) < park.FENCE_HEIGHT_FT


# ---- The verdict and the picture ------------------------------------------

def test_the_animation_lands_a_home_run_past_the_fence_the_verdict_cleared():
    """The property the whole change is for: the banner and the picture are one
    event.

    `hit_outcome_manager` calls `fence_verdict` at contact and `hit_animation`
    places the ball from the same three inputs, so a ball ruled gone lands past
    the fence *at its own bearing*. It could not before: the landing was
    `wall_r` plus a random 0-61 ft that had never seen the exit velocity, and
    the bearing was scattered 7 degrees away from the one the verdict used.
    """
    for spray_deg in (-40.0, -20.0, 0.0, 20.0, 40.0):
        field_rad = ha._fair_field_angle(math.radians(90.0 + spray_deg))
        for launch, ev in ((28.0, 110.0), (32.0, 108.0), (35.0, 112.0)):
            if park.fence_verdict(launch, ev, field_rad) != park.OUT_OF_PARK:
                continue
            anim = HitAnimation(_StubGame(), outcome="HOME RUN",
                                on_complete=lambda: None, quality=0.95,
                                spray_deg=spray_deg, launch_deg=launch,
                                ev_mph=ev)
            dx = anim._hit_end[0] - HOME[0]
            dy = HOME[1] - anim._hit_end[1]
            assert math.hypot(dx / ha.WALL_SEMI_X, dy / ha.WALL_SEMI_Y) >= 1.0, (
                f"spray {spray_deg}, {launch} deg / {ev} mph was ruled gone but "
                f"landed inside the fence")


def test_a_wall_ball_is_aimed_past_the_fence_and_stopped_by_it():
    """The candidate branch aims at the real carry, which is past the fence by
    construction for anything the verdict calls a wall ball — and the in-flight
    detector is what ends the flight at the face. It used to aim at a random
    5-35 ft past the fence, discarding the carry it had just computed."""
    field_rad = math.radians(90)
    lo, hi = 60.0, 160.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if park.fence_verdict(30.0, mid, field_rad) == park.SHORT_OF_WALL:
            lo = mid
        else:
            hi = mid
    anim = HitAnimation(_StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
                        quality=0.9, batted_ball_type="FLY", spray_deg=0.0,
                        launch_deg=30.0, ev_mph=hi + 0.5)
    assert anim._is_wall_candidate
    assert anim._hit_end is not None
