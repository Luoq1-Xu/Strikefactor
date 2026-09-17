"""A ball a fielder is standing under is a ball a fielder can catch.

Two rules said otherwise, each for a reason that had stopped being true, and
both produced the same picture: the outfielder camped under the ball, the ball
landing on him, and an extra-base hit.

* **A ball on its way to the fence could not be caught at all.** The in-flight
  catch check was skipped outright for wall candidates, on the grounds that
  those are aimed past every fielder by design. True of the coin flip that once
  picked them — it aimed the ball into a gap — and false of `park.fence_verdict`,
  which picks them off this ball's own carry along its own bearing, so a fly
  that carries 402 ft straight at the centre fielder is one. Measured over
  2,500 balls in play, all 72 wall candidates were doubles, and on 60 of them
  a fielder stood inside glove range at glove height while the check was not
  allowed to run. And there was nothing left to protect: a ball is off the wall
  precisely when it reaches the fence *below* its 12 ft rim, so it arrives at
  catchable height by construction.

* **Outfielders could not catch pop-ups.** `POP_UP` is a launch angle over 50
  degrees and nothing else since the flight model became continuous, and at
  these exit velocities that carries a median of 178 ft and reaches 380 — so
  the shape's name stopped meaning "over the diamond" while the eligibility
  pool went on assuming it did. The infield-only pool showed up twice: 11 of
  those 2,500 balls fell with an outfielder a pixel and a half away, and every
  one of the 167 that *were* caught was caught by an infielder, the SS and 2B
  taking balls landing a median of 212 ft out.

What these do not assert is that the ball is always caught. Whether anybody
gets there is the fielding model's business and is meant to stay emergent;
what is pinned here is that the rules no longer forbid the catch, and that the
carom still happens for the ball that does beat the defense.
"""

import random

import conftest
import pytest

from strikefactor.gameplay import ball_flight, park, spray
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.hit_animation import (
    INFIELD_ROLES,
    OUTFIELD_ROLES,
    HitAnimation,
)


class _StubBatter:
    def get_handedness(self):
        return "R"


class _StubGame:
    def __init__(self):
        self.batter = _StubBatter()


def _play(anim, max_ms=20000, step=16):
    t = 0
    while not anim.finished and t < max_ms:
        t += step
        anim.update(t)
    return anim


# How high up the face the fixture's wall ball arrives. Chest height at the
# track, and well under the 8 ft glove *where the fielder meets it*: the catch
# is asked on the frame the shadow reaches the line a live ball is held at,
# `BALL_WALL_LIMIT_NORM`, about 2.7 ft in front of the face — and a ball on
# the real descent (`ball_flight.DRAG_APEX_ANCHORS`) is falling at close to a
# foot per foot of path there, so it is that much higher at the catch than at
# the fence. Bisecting for the *midpoint of the off-the-wall band*, as this
# fixture used to, put the ball 6 ft up the face and ~8.5 ft at the catch: a
# ball that struck the fence over every fielder's glove, on every seed, which
# left the ordering tests below with nothing to exercise.
_WALL_BALL_HEIGHT_FT = 4.0


def _wall_ball_ev(spray_deg, launch_deg=30.0, height_ft=_WALL_BALL_HEIGHT_FT):
    """An exit velocity that strikes the face `height_ft` up at this bearing.

    Bisected against the flight rather than written down, because the fence is
    an ellipse: the band that comes off the wall runs from the ball that lands
    at its foot to the one that just clears it, and both ends move with the
    bearing.
    """
    field_rad = spray.field_angle_rad(spray_deg, 1.0)
    wall_ft = park.wall_distance_ft(field_rad)
    lo, hi = 40.0, 160.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        carry = ball_flight.carry_distance_ft(launch_deg, mid)
        if ball_flight.height_at_distance_ft(launch_deg, carry, wall_ft) < height_ft:
            lo = mid
        else:
            hi = mid
    ev = hi
    assert park.fence_verdict(launch_deg, ev, field_rad) == park.OFF_THE_WALL
    return ev


def _wall_ball(seed, spray_deg=0.0, launch_deg=30.0):
    random.seed(seed)
    anim = HitAnimation(_StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
                        quality=0.9, batted_ball_type="FLY", spray_deg=spray_deg,
                        launch_deg=launch_deg,
                        ev_mph=_wall_ball_ev(spray_deg, launch_deg))
    assert anim._is_wall_candidate, "expected a ball that reaches the fence"
    return anim


def _pop_up(seed, ev_mph, spray_deg=18.0, launch_deg=52.0):
    random.seed(seed)
    return HitAnimation(_StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
                        quality=0.75, batted_ball_type="POP_UP",
                        spray_deg=spray_deg, launch_deg=launch_deg, ev_mph=ev_mph)


# ---- How high a fielder can reach ------------------------------------------


def test_the_catch_ceiling_is_the_glove_and_is_stated_in_feet():
    """One definition of how high a fielder can catch, converted at the seam.

    It was a bare `25`, under a comment reading "px ≈ ft × 2.5 at the render
    scale" — and the render scale is `FT_TO_PX_Y` = 1.10, so the ceiling it
    described as 10 ft was 23. Nothing in the file could state it in feet,
    which is the tell; this is the same units drift CLAUDE.md records for
    `EV_CALIBRATION`, one axis over.
    """
    assert ha.INTERCEPT_MAX_LIFT_PX == pytest.approx(
        ha.GLOVE_REACH_FT * ha.FT_TO_PX_Y)
    # The number that matters is the one in feet, so say what it may be: a
    # standing glove, not a second storey.
    assert 6.0 <= ha.INTERCEPT_MAX_LIFT_PX / ha.FT_TO_PX_Y <= 11.0


def _overhead_catch_fires(anim, height_ft):
    """Put a fielder on the ball's shadow, with the ball `height_ft` up.

    The height is set by **moving the ball along its own flight** to the point
    where the flight model says it is that high, not by writing a pixel offset
    into `_ball`. That distinction is the whole change: the gate used to read
    the drawn lift, so a test could synthesise one and never touch the arc —
    which is exactly what this did, and it would have gone on passing against
    an arc that had nothing to do with the launch angle.
    """
    f = anim.fielders["CF"]
    anim._elapsed = max(anim._elapsed, f.reaction_delay_ms + 1.0)
    anim._current_flight_progress = _progress_at_height(anim, height_ft)
    shadow = (f.pos[0], f.pos[1])
    anim._ball_shadow = shadow
    anim._ball = (shadow[0], shadow[1] - anim._flight_lift_px(
        anim._current_flight_progress))
    return anim._check_in_flight_intercept()


def _progress_at_height(anim, height_ft):
    """Path fraction on the climb at which the flight is `height_ft` up."""
    lo, hi = 0.0, 0.5
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if anim._flight_height_ft(mid) < height_ft:
            lo = mid
        else:
            hi = mid
    return hi


def test_a_ball_over_a_fielders_head_is_not_caught():
    """The ceiling doing its job, asked of the geometry directly rather than
    through a whole play: same fielder, same flight, two heights."""
    def liner():
        random.seed(4)
        return HitAnimation(_StubGame(), outcome="IN_PLAY",
                            on_complete=lambda: None, quality=0.8,
                            batted_ball_type="LINER", spray_deg=0.0,
                            launch_deg=18.0, ev_mph=100.0)

    below, above = liner(), liner()
    # The flight has to be able to reach both heights for the question to
    # mean anything; a liner peaking under the glove could never be over it.
    assert below._flight_height_ft(0.5) > ha.GLOVE_REACH_FT + 2.0
    assert _overhead_catch_fires(below, ha.GLOVE_REACH_FT - 2.0)
    assert not _overhead_catch_fires(above, ha.GLOVE_REACH_FT + 2.0)


def test_the_catch_ceiling_is_asked_of_the_flight_and_not_the_picture():
    """The gate reads feet off the flight model. Drawing the ball somewhere
    else cannot buy a catch — which it could when the gate read the drawn
    lift, and the drawn lift was `random.uniform(25, 40)` on a line drive."""
    random.seed(11)
    anim = HitAnimation(_StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
                        quality=0.8, batted_ball_type="LINER", spray_deg=0.0,
                        launch_deg=18.0, ev_mph=100.0)
    f = anim.fielders["CF"]
    anim._elapsed = max(anim._elapsed, f.reaction_delay_ms + 1.0)
    anim._ball_shadow = (f.pos[0], f.pos[1])
    anim._current_flight_progress = _progress_at_height(
        anim, ha.GLOVE_REACH_FT + 2.0)
    # Drawn at the fielder's feet, modelled over their head. The model wins.
    anim._ball = anim._ball_shadow
    assert not anim._check_in_flight_intercept()


# ---- The ball that reaches the fence ---------------------------------------


def test_the_fence_is_taller_than_a_fielder_can_reach():
    """The invariant that lets a ball off the wall be a double at all.

    A ball is off the wall exactly when it arrives *below the rim*, so if the
    rim were no higher than a glove, every wall ball would arrive inside a
    fielder's reach and a fielder standing there would catch it — the ladder
    measured 50 of 58 caught at an 8 ft fence, and doubles ran 0.16 per single
    against MLB's 0.33. The band between the glove and the rim is where a
    double off the wall lives, and this asserts the band exists.
    """
    assert park.FENCE_HEIGHT_FT > ha.GLOVE_REACH_FT
    assert ha.WALL_FACE_HEIGHT_PX > ha.INTERCEPT_MAX_LIFT_PX


def test_a_ball_that_reaches_the_wall_over_the_glove_is_not_caught():
    """The band, exercised: a flight arriving between the glove and the rim
    is over the fielder at the fence, so it comes off the wall."""
    spray_deg, launch_deg = 8.0, 30.0
    field_rad = spray.field_angle_rad(spray_deg, 1.0)
    wall_ft = park.wall_distance_ft(field_rad)
    target_ft = 0.5 * (ha.GLOVE_REACH_FT + park.FENCE_HEIGHT_FT)

    lo, hi = 40.0, 160.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        carry = ball_flight.carry_distance_ft(launch_deg, mid)
        h = ball_flight.height_at_distance_ft(launch_deg, carry, wall_ft)
        if h < target_ft:
            lo = mid
        else:
            hi = mid
    ev = hi
    assert park.fence_verdict(launch_deg, ev, field_rad) == park.OFF_THE_WALL

    for seed in range(8):
        random.seed(seed)
        anim = _play(HitAnimation(_StubGame(), outcome="IN_PLAY",
                                  on_complete=lambda: None, quality=0.9,
                                  batted_ball_type="FLY", spray_deg=spray_deg,
                                  launch_deg=launch_deg, ev_mph=ev))
        assert not anim._secured_in_flight, (
            f"seed {seed}: a ball arriving {target_ft:.1f} ft up a "
            f"{park.FENCE_HEIGHT_FT:.0f} ft fence was caught")
        assert anim._wall_hit


def test_a_ball_off_the_wall_is_not_an_automatic_extra_base_hit():
    """The measured defect: every wall candidate was a double. Hit at the
    centre fielder, most of them are catches now."""
    outs = [_play(_wall_ball(seed)).classified_outcome in ("FLYOUT", "LINEOUT")
            for seed in range(20)]
    assert sum(outs) >= 10, (
        f"only {sum(outs)}/20 balls hit at the centre fielder were caught")


def test_the_catch_is_asked_before_the_fence_is():
    """A caught wall ball was caught *in front of* the wall.

    The ordering is the whole of it: run the impact check first, as it used to
    be, and on the crossing frame the ball is planted at the face and the
    flight truncated — and the catch check would then hand the carom to
    whichever fielder happened to be standing at the impact point, which is a
    ball rebounding into somebody rather than a catch.
    """
    caught = 0
    for seed in range(20):
        anim = _play(_wall_ball(seed))
        if anim._secured_in_flight:
            caught += 1
            assert not anim._wall_hit, (
                "seed %d: the ball struck the fence and was then caught" % seed)
    assert caught, "no wall ball was caught at all; nothing was exercised"


def test_a_ball_nobody_reaches_still_comes_off_the_wall():
    """The carom path is still live — this only changed who gets a say first.

    Held off explicitly rather than searched for, for the reason
    `conftest.uncaught` gives.
    """
    anim = _play(conftest.uncaught(_wall_ball(3)))
    assert anim._wall_hit
    assert anim.classified_outcome in ("DOUBLE", "TRIPLE")


def test_a_ball_that_clears_the_fence_is_still_a_home_run():
    """The catch check has no business on a ball that left the park, and the
    boundary between the two is `park.fence_verdict`'s, not this module's."""
    ev = _wall_ball_ev(0.0) + 12.0
    assert park.fence_verdict(30.0, ev, spray.field_angle_rad(0.0, 1.0)) == park.OUT_OF_PARK
    random.seed(5)
    anim = _play(HitAnimation(_StubGame(), outcome="HOME RUN",
                              on_complete=lambda: None, quality=0.9,
                              batted_ball_type="FLY", spray_deg=0.0,
                              launch_deg=30.0, ev_mph=ev))
    assert not anim._secured_in_flight
    assert anim.classified_outcome == "HOME RUN"


# ---- The pop-up that is not over the diamond -------------------------------


def _caught_by(anim):
    """Who caught this ball *in the air*, or None if it was not caught.

    Deliberately not `fielder_role`, which is also set by the fielder who picks
    the ball up off the grass — so the reported defect, an outfielder standing
    under a pop-up and retrieving it after the bounce, satisfies that property
    and passes a test written against it. It is the catch that is in question.
    """
    return anim.fielder_role if anim._secured_in_flight else None


def test_a_deep_pop_up_belongs_to_the_outfield():
    """The 300 ft pop-up the outfielder used to stand under and watch land.
    Asserted on who caught it, not merely that somebody ended up with it: an
    infielder converting it from 200 ft out is the other half of the defect."""
    ev = 105.0
    landing_ft = ball_flight.carry_distance_ft(52.0, ev)
    assert landing_ft > 250, f"expected a deep pop-up, got {landing_ft:.0f} ft"

    catchers = [_caught_by(_play(_pop_up(seed, ev))) for seed in range(12)]
    assert all(r is not None for r in catchers), (
        f"a deep pop-up fell in with a fielder under it: {catchers}")
    assert all(r in OUTFIELD_ROLES for r in catchers), (
        f"a 300 ft pop-up was caught by the infield: {catchers}")
    assert all(_play(_pop_up(seed, ev)).classified_outcome == "POP UP"
               for seed in range(12))


def test_a_pop_up_over_the_diamond_still_belongs_to_the_infield():
    """The other end of the same range, so the fix does not simply hand the
    outfield everything that leaves the bat above 50 degrees."""
    ev = 55.0
    landing_ft = ball_flight.carry_distance_ft(52.0, ev)
    assert landing_ft < 150, f"expected a shallow pop-up, got {landing_ft:.0f} ft"

    catchers = [_caught_by(_play(_pop_up(seed, ev))) for seed in range(12)]
    assert all(r in INFIELD_ROLES for r in catchers), (
        f"an infield pop-up was caught by the outfield: {catchers}")


@pytest.mark.parametrize("ev_mph", [55.0, 105.0])
def test_the_pitcher_and_catcher_still_do_not_chase_pop_ups(ev_mph):
    """The part of the old rule that was right, and the reason it is written
    as an exclusion rather than an infield list: infielders call both of them
    off in fair territory."""
    pool = _pop_up(0, ev_mph)._eligible_intercept_pool()
    assert "P" not in pool and "C" not in pool
    assert set(OUTFIELD_ROLES) <= set(pool)


def test_no_airborne_shape_excludes_a_fielder_by_shape_alone():
    """The general form of both halves above, and the thing that let each of
    them sit unnoticed: a shape is a *trajectory*, and which trajectories a
    given fielder may catch is a question about where the ball goes, which the
    geometry answers per frame. Only the grounder keeps a shape-level rule —
    a ball on the ground has to reach the outfield to be an outfielder's.
    """
    for shape in ("LINER", "FLY", "POP_UP"):
        pool = set(_pop_up(0, 95.0)._eligible_intercept_pool()) if shape == "POP_UP" else None
        if pool is None:
            random.seed(0)
            anim = HitAnimation(_StubGame(), outcome="IN_PLAY",
                                on_complete=lambda: None, quality=0.8,
                                batted_ball_type=shape, spray_deg=10.0)
            pool = set(anim._eligible_intercept_pool())
        assert set(OUTFIELD_ROLES) <= pool, shape
        assert set(INFIELD_ROLES) <= pool, shape
