"""The outfield wall is a boundary, for the defenders and for the camera.

Two reported artifacts, one cause each:

* Fielders ran through the wall. Every target a defender is given is the
  answer to a physical question — where the ball is, where it will land,
  where it will stop — and a HOME RUN or wall-candidate `_hit_end` is
  beyond the fence by construction. Nothing between that target and the
  mover had a notion of a boundary.
* A home run's ball was parked at its landing point and left sitting in
  the black beyond the wall for the rest of the animation, because the
  HOME RUN branch of `_update_hit` freezes the ball there and `draw`
  rendered it unconditionally.

The second fix has a failure mode of its own — hiding the ball the
moment it crosses the fence line, mid-flight, at the top of its arc —
so it is guarded from both sides here.
"""

import math

import pytest

from strikefactor.gameplay import ball_flight, park, spray
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.hit_animation import HitAnimation


class _StubBatter:
    def get_handedness(self):
        return "R"


class _StubGame:
    def __init__(self):
        self.batter = _StubBatter()


def _make(outcome="IN_PLAY", shape=None, quality=0.85):
    return HitAnimation(_StubGame(), outcome=outcome, on_complete=lambda: None,
                        quality=quality, batted_ball_type=shape)


def _outside_by(point):
    """Pixels past the wall ellipse, negative when inside the park."""
    dx = point[0] - ha.HOME[0]
    dy_math = ha.HOME[1] - point[1]
    dist = math.hypot(dx, dy_math)
    if dist == 0:
        return -ha.WALL_SEMI_X
    return dist - ha._wall_r_at(math.atan2(dy_math, dx))


def _play(anim, max_ms=14000, step=16):
    """Step one animation to completion, yielding after each frame."""
    t = 0
    while not anim.finished and t < max_ms:
        t += step
        anim.update(t)
        yield t


@pytest.mark.parametrize("outcome,shape", [
    ("HOME RUN", None),
    ("IN_PLAY", "FLY"),
    ("IN_PLAY", "LINER"),
    ("IN_PLAY", "GROUNDER"),
])
def test_no_fielder_ever_leaves_the_park(outcome, shape):
    """The whole marker stays on the grass, not just its centre — the
    containment margin is measured to the base of the fence and then in
    by a body radius."""
    for _ in range(25):
        anim = _make(outcome, shape)
        for _t in _play(anim):
            for role, f in anim.fielders.items():
                over = _outside_by(f.pos)
                assert over <= -ha.BODY_RADIUS_PX + 0.5, (
                    f"{role} was {over:.1f} px past the wall ellipse")


def test_a_home_run_ball_is_gone_once_it_lands():
    """The reported artifact: a white dot sitting in the black beyond the
    fence for the several seconds the HR animation runs on for.

    Asked against the animation's *own* clock. `_play` yields the caller's
    timestamps, and `update` zeroes `start_time` on the first of them, so
    `t` runs one frame ahead of `_elapsed` — which put the last frame of
    the flight, with the ball a pixel short of the fence and correctly
    still drawn, inside the "landed" window. It passed only because
    `_point_outside_wall` used to draw the boundary 8 px in front of the
    fence and called that frame out of the park too.
    """
    for _ in range(20):
        anim = _make("HOME RUN")
        landed = False
        for _t in _play(anim):
            if anim._elapsed > anim.duration_ms:
                landed = True
                assert anim._ball_behind_wall(), (
                    "landed home run is still being drawn beyond the wall")
        assert landed, "never got past the flight"


def test_a_home_run_is_watchable_the_whole_way_out():
    """The failure mode of the fix, and the reason `_ball_behind_wall`
    has a height term at all. A ball clearing the fence is *above* it, so
    hiding it the frame its ground point crossed the wall line would
    blink it out mid-arc — including at the apex, the most watchable part
    of the play. It should vanish where a real one does: on the way down,
    at the fence."""
    for _ in range(20):
        anim = _make("HOME RUN")
        visible = hidden = 0
        for _t in _play(anim):
            if anim._elapsed > anim.duration_ms:
                break
            if anim._ball_behind_wall():
                hidden += 1
            else:
                visible += 1
                assert hidden == 0, "ball reappeared after going behind the wall"
        frac = visible / max(1, visible + hidden)
        assert frac > 0.9, f"ball was hidden for {1 - frac:.0%} of the flight"


def test_a_ball_at_the_foot_of_the_fence_is_still_drawn():
    """`_point_outside_wall` has no margin on purpose: a live ball is
    contained *inside* the ellipse by BALL_WALL_MARGIN_PX, so nothing
    that rolled to the wall and rattled around there can be hidden by
    the out-of-the-park test."""
    for _ in range(30):
        anim = _make("IN_PLAY", "LINER", quality=1.0)
        for _t in _play(anim):
            if anim._elapsed <= anim.duration_ms:
                continue        # in flight; a wall candidate is aimed past it
            assert not anim._ball_behind_wall(), (
                "a ball on the ground in the park was hidden")


# ---- A ball off the wall ------------------------------------------------------
#
# Reported: the ball appears to go *over* the wall, then clips and abruptly
# reappears in play at the fielder's feet. Three separate causes, all of them
# in the handful of frames around the carom, and all of them purely how the
# ball is drawn — the A/B over 900 balls in play is 0 differing outcomes.
#
# Reported again after that fix, and the reason these tests now measure the
# ball against `_wall_geometry()` — the fence that is actually drawn — rather
# than against a height restated from constants. The first fix bounded the
# ball's lift at the ellipse correctly, but the ellipse was drawn as the
# fence's *top*, so any lift at all put the ball over the drawn rim: 98% of
# wall balls, by a median 9 px. Every test here passed throughout.


def _drawn_rim_y(x):
    """Screen y of the drawn fence's top edge at screen x."""
    pts = ha._wall_geometry()['top']
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if min(x0, x1) <= x <= max(x0, x1):
            f = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            return y0 + f * (y1 - y0)
    raise AssertionError(f"x={x:.1f} is outside the drawn fence")


def _ellipse_d(point):
    return math.hypot((point[0] - ha.HOME[0]) / ha.WALL_SEMI_X,
                      (ha.HOME[1] - point[1]) / ha.WALL_SEMI_Y)


def test_the_drawn_fence_is_the_fence_everything_else_uses():
    """One fence. It stands on the ellipse — `park.wall_distance_ft`, which
    the verdict, the carom and `_point_outside_wall` all use — and is as tall
    as `park.FENCE_HEIGHT_FT`, which decides home runs. The ball is held a
    ball's radius in front of it and a fielder a body's radius, so both are
    drawn touching the face rather than stopping short of it."""
    geo = ha._wall_geometry()
    face = park.FENCE_HEIGHT_FT * ha.FT_TO_PX_Y
    assert ha.WALL_FACE_HEIGHT_PX == pytest.approx(face)
    for (bx, by), (tx, ty) in zip(geo['bot'], geo['top']):
        assert _ellipse_d((bx, by)) == pytest.approx(1.0, abs=1e-9)
        assert (tx, ty) == pytest.approx((bx, by - face))
    assert ha.BALL_WALL_MARGIN_PX == ha.BALL_RADIUS_PX
    assert ha.FIELDER_WALL_MARGIN_PX == ha.BODY_RADIUS_PX


_WALL_BALL_LAUNCH_DEG = 30.0


def _wall_ball_band(spray_deg):
    """(reaches, clears): the exit velocities that bound the off-the-wall
    window at this bearing — see `_wall_ball_ev`."""
    field_rad = spray.field_angle_rad(spray_deg, 1.0)

    def first_ev(reached):
        lo, hi = 40.0, 160.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if reached(park.fence_verdict(_WALL_BALL_LAUNCH_DEG, mid,
                                          field_rad)):
                hi = mid
            else:
                lo = mid
        return hi

    return (first_ev(lambda v: v != park.SHORT_OF_WALL),
            first_ev(lambda v: v == park.OUT_OF_PARK))


def _wall_ball_ev(spray_deg):
    """An exit velocity whose carry strikes this fence rather than clearing it.

    Solved rather than written down. `park.fence_verdict` decides this now —
    the ball is off the wall when its carry reaches the fence but its *height*
    there is under `park.FENCE_HEIGHT_FT` — and that window is narrow: about
    13 ft of carry at a 30 degree launch, because a ball carrying much past the
    fence is already well above it. A magic exit velocity would silently stop
    landing inside the window the first time the drag anchors moved; bisecting
    for one keeps the test about the geometry.

    It used to be `quality=1.0`, which qualified every time against a scalar
    `WALL_REACH_FT = 380`. Under the physics a max-quality fly carries ~440 ft
    and is a *home run*, which is the point of the change.
    """
    field_rad = spray.field_angle_rad(spray_deg, 1.0)

    def first_ev(reached):
        lo, hi = 40.0, 160.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if reached(park.fence_verdict(_WALL_BALL_LAUNCH_DEG, mid,
                                          field_rad)):
                hi = mid
            else:
                lo = mid
        return hi

    # The bottom of the band is the ball that lands at the foot of the fence;
    # the top is the one that just clears it. Take the middle, so the ball
    # strikes the face about halfway up rather than grazing either edge —
    # at the very bottom the arc reaches the fence with essentially no height
    # left and there is nothing for `_begin_wall_drop` to drop.
    reaches = first_ev(lambda v: v != park.SHORT_OF_WALL)
    clears = first_ev(lambda v: v == park.OUT_OF_PARK)
    ev = 0.5 * (reaches + clears)
    assert park.fence_verdict(_WALL_BALL_LAUNCH_DEG, ev,
                              field_rad) == park.OFF_THE_WALL, (
        "no exit velocity strikes the fence at %.1f deg" % spray_deg)
    return ev


def _wall_ball(seed):
    """A ball that will strike the fence on the fly, with nobody catching it.

    The spray is spread across the outfield on purpose. Built without one,
    every ball goes to *exactly* dead centre — the one bearing at which the
    ellipse's radius equals the semi-axis BALL_WALL_LIMIT_NORM is
    normalized against, so the two ways of expressing the containment line
    coincide and the defect they disagree about is invisible.

    `conftest.uncaught` is what keeps these about the picture: a ball that
    reaches the fence arrives below its rim and so within an outfielder's
    reach, and the ones the defense does run down never get here to be drawn.
    """
    import random

    import conftest

    random.seed(seed)
    spray_deg = -28.0 + (seed % 15) * 4.0
    anim = HitAnimation(_StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
                        quality=1.0, batted_ball_type="FLY",
                        spray_deg=spray_deg,
                        launch_deg=_WALL_BALL_LAUNCH_DEG,
                        ev_mph=_wall_ball_ev(spray_deg))
    assert anim._is_wall_candidate, "expected a ball aimed past the fence"
    return conftest.uncaught(anim)


def _wall_frames(anim, after=10):
    """Frames around the carom: (lift_px, ellipse_d, hidden, wall_hit, ball)."""
    frames = []
    struck = None
    for _t in _play(anim):
        frames.append((
            anim._ball_shadow[1] - anim._ball[1],
            _ellipse_d(anim._ball_shadow),
            anim._ball_behind_wall(),
            anim._wall_hit,
            tuple(anim._ball),
        ))
        if anim._wall_hit:
            if struck is None:
                struck = len(frames) - 1
            elif len(frames) > struck + after:
                break
    assert struck is not None, "never reached the wall"
    return frames, struck


def test_a_ball_off_the_wall_strikes_the_face_and_not_the_sky():
    """The whole drawn ball has to be *below the drawn rim* when it gets
    there, and stay below it as it comes down the face.

    Nothing asked at first: the arc was aimed 5–35 ft past the fence and the
    height at the fence was whatever fell out of it. Then a cap asked, of
    the wrong edge — see the section comment. Asked of the drawing now.
    """
    for seed in range(40):
        anim = _wall_ball(seed)
        frames, struck = _wall_frames(anim, after=40)
        # From the last frame before it strikes the fence onward. The impact
        # frame alone would be a tautology: the old code planted the ball on
        # the grass there, so it read 0 px up — the ball the player saw over
        # the wall was the frame before, still on its arc.
        for k, (_lift, _d, _hidden, _wall, ball) in enumerate(frames[struck - 1:]):
            over = _drawn_rim_y(ball[0]) - (ball[1] - ha.BALL_RADIUS_PX)
            assert over <= 0.0, (
                f"seed {seed}: frame {k - 1} from impact, the ball's top edge "
                f"is {over:.1f} px over the drawn rim")


def test_a_ball_off_the_wall_is_still_drawn_as_a_fly_ball():
    """Nothing has to flatten the arc to put the ball on the face any more.

    Two generations did: `_wall_impact_peak_cap` capped the peak and
    `_wall_impact_landing_phase` moved where the arc came down, both because
    the fence sits near the end of a *sine*, where there is almost no height
    left — the cap had to be severe enough that a 400 ft double drew a
    median apex of 44 px, lower than any caught fly ball. An arc over the
    carry is already at the verdict's height when it reaches the fence, so
    the only correction left is the drawn ball's own radius, and the apex
    stays the one the physics gives — `ball_flight.apex_height_ft`, not a
    vacuum `R tan(theta) / 4` restated here."""
    for seed in range(20):
        anim = _wall_ball(seed)
        apex_ft = ball_flight.apex_height_ft(anim.launch_deg, anim._carry_ft)
        drawn = max(anim._flight_lift_px(i / 400.0) for i in range(401))
        # The radius correction, and only the radius correction.
        assert 0.7 <= anim._fence_lift_scale <= 1.0, anim._fence_lift_scale
        assert drawn == pytest.approx(
            apex_ft * ha.FT_TO_PX_Y * anim._fence_lift_scale, rel=1e-3)
        # Still unmistakably a fly ball: several times over the rim it is
        # about to come down onto.
        assert drawn > 3.0 * ha.WALL_FACE_HEIGHT_PX, drawn


def test_where_it_strikes_the_face_is_where_the_verdict_had_it():
    """A ball that barely reached the fence hits it low; one that nearly
    cleared it hits just under the rim. The height is the one `park`
    computed to call it off the wall, not a constant."""
    spray_deg = 12.0
    field_rad = spray.field_angle_rad(spray_deg, 1.0)
    # Three exit velocities across the off-the-wall band, as fractions of it
    # rather than as a fixed +/- mph: the band is only ~2.4 mph wide at a 30
    # degree launch, because past the fence a real ball is still 60-90 ft up
    # and the height there climbs about 4 ft per mph.
    reaches, clears = _wall_ball_band(spray_deg)
    lifts = []
    for frac in (0.2, 0.5, 0.8):
        ev = reaches + frac * (clears - reaches)
        anim = HitAnimation(_StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
                            quality=1.0, batted_ball_type="FLY", spray_deg=spray_deg,
                            launch_deg=_WALL_BALL_LAUNCH_DEG, ev_mph=ev)
        assert park.fence_verdict(_WALL_BALL_LAUNCH_DEG, ev,
                                  field_rad) == park.OFF_THE_WALL
        lifts.append(anim._wall_impact_lift_px())
    assert 0.0 <= lifts[0] < lifts[1] < lifts[2] <= ha.WALL_IMPACT_MAX_LIFT_PX


def test_the_ball_never_teleports_at_the_wall():
    """The visible artifact, measured directly: how far the drawn ball can
    move *downward* in a single frame, and how far it can move at all on
    the frame it strikes the fence.

    It used to drop the whole way from wherever the arc had it to the grass
    in one frame — 19 to 31 px on the balls sampled — and it now falls down
    the face under gravity. And it used to be pulled 8–11 px back toward
    the camera on the impact frame, because the impact fired at the fence
    and then moved the ball to the holding line in front of it; it fires on
    that line now, so the impact frame's step is an ordinary frame's."""
    worst_drop = worst_jump = 0.0
    for seed in range(40):
        anim = _wall_ball(seed)
        frames, struck = _wall_frames(anim, after=40)
        lifts = [f[0] for f in frames]
        worst_drop = max(worst_drop, max(lifts[k] - lifts[k + 1]
                                         for k in range(len(lifts) - 1)))
        balls = [f[4] for f in frames]
        before = math.dist(balls[struck - 2], balls[struck - 1])
        at = math.dist(balls[struck - 1], balls[struck])
        worst_jump = max(worst_jump, at - before)
    assert worst_drop < 4.0, f"the ball dropped {worst_drop:.1f} px in one frame"
    assert worst_jump < 2.0, (
        f"the impact frame moved the ball {worst_jump:.1f} px more than the "
        f"frame before it")


def test_a_ball_that_hops_into_the_fence_falls_down_it():
    """The same fault on the ground. A ball that landed short and reached
    the fence mid-hop had its hop cut to the grass in that frame — a median
    2.3 px, up to 5.7 px, straight down. It comes down the face now, from
    wherever the hop had it.

    Set up directly rather than searched for: whether a real ball gets to
    the fence before a fielder does depends on the whole defense, and a
    test of how the carom is *drawn* should not. `conftest.uncaught` is what
    holds the defense off, for the reason it exists — without it this liner
    is fielded before it ever hops and the search below finds no frame.

    A FLY rather than a LINER, because the hop has to be tall enough to be
    worth cutting: a liner lands shallow and its first hop is 2.4 px, while a
    fly comes down steeply off `ground_roll`'s descent angle and clears 5-7.
    That is the whole reason this artifact was visible on fly balls."""
    import conftest
    anim = conftest.uncaught(HitAnimation(
        _StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
        quality=1.0, batted_ball_type="FLY", spray_deg=0.0,
        launch_deg=30.0, ev_mph=88.0))
    t = 0
    while t < 14000 and anim._ball_pos is None:
        t += 16
        anim.update(t)
    assert anim._ball_pos is not None, "never landed"

    # Taken off the hop schedule rather than searched for in the play, which
    # is what the note above means by "set up directly": a fly ball is
    # secured within a few frames of landing, so there is no frame of live
    # play with the ball loose at the top of a hop, and hunting for one is
    # how this test came to depend on where the defense was standing.
    t_start, dur, _h, _r = anim._bounces[0]
    tau = t_start + dur / 2.0
    assert anim._current_bounce_lift(tau) > 3.0, "the first hop is not a hop"

    # Put it just short of the holding line along its own bearing, then step
    # it into the fence.
    s = ha.BALL_WALL_LIMIT_NORM * 0.9995 / _ellipse_d(anim._ball_pos)
    anim._ball_pos = [ha.HOME[0] + (anim._ball_pos[0] - ha.HOME[0]) * s,
                      ha.HOME[1] + (anim._ball_pos[1] - ha.HOME[1]) * s]
    hop_lift = anim._current_bounce_lift(tau + 16)
    anim._step_ball_on_ground(16, tau + 16)
    assert anim._wall_hit, "the step did not reach the fence"
    assert anim._current_bounce_lift(tau + 16) == pytest.approx(hop_lift, abs=1e-6)
    lifts = [anim._current_bounce_lift(tau + 16 + dt) for dt in range(0, 2000, 16)]
    assert all(b <= a + 1e-9 for a, b in zip(lifts, lifts[1:]))
    assert lifts[-1] == 0.0


# ---- A home run over the wall --------------------------------------------------


def _home_run_ev(spray_deg, launch_deg):
    """The slowest exit velocity that clears the fence: a wall-scraper, the
    home run whose drawn arc has the least height left at the fence."""
    field_rad = spray.field_angle_rad(spray_deg, 1.0)
    lo, hi = 40.0, 200.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if park.fence_verdict(launch_deg, mid, field_rad) == park.OUT_OF_PARK:
            hi = mid
        else:
            lo = mid
    return hi


@pytest.mark.parametrize("launch_deg", [24.0, 32.0, 45.0])
@pytest.mark.parametrize("spray_deg", [-40.0, -15.0, 0.0, 20.0, 40.0])
@pytest.mark.parametrize("extra_mph", [0.01, 8.0])
def test_a_home_run_is_drawn_over_the_rim(launch_deg, spray_deg, extra_mph):
    """The mirror of the wall ball: on the frame its ground point reaches the
    fence, the whole drawn ball is above the drawn rim. Before the fence
    stood on the ellipse this held by accident — the rim *was* the ellipse —
    and moving the fence is what made a wall-scraper's arc, which has almost
    no height left a few feet from its landing, able to pass through the
    face."""
    ev = _home_run_ev(spray_deg, launch_deg) + extra_mph
    anim = HitAnimation(_StubGame(), outcome="HOME RUN", on_complete=lambda: None,
                        quality=1.0, batted_ball_type="FLY", spray_deg=spray_deg,
                        launch_deg=launch_deg, ev_mph=ev)
    for _t in _play(anim):
        if ha._point_outside_wall(anim._ball_shadow):
            clear = _drawn_rim_y(anim._ball[0]) - (anim._ball[1] + ha.BALL_RADIUS_PX)
            # One frame's sampling: the crossing frame is taken just after
            # the crossing, on the way down.
            assert clear >= -0.5, (
                f"crossed the fence with the ball {-clear:.1f} px into the face")
            return
    raise AssertionError("the home run never reached the fence")


def test_the_ball_is_never_hidden_on_its_way_to_the_wall():
    """Nothing in the park may be hidden by the out-of-the-park test.

    Two things did it. `_point_outside_wall` drew the boundary at
    BALL_WALL_LIMIT_NORM — the line a *rolling* ball is held at, 8 px inside
    the fence at centre — so a ball still in flight was called out of the
    park for the last several frames of its approach and blinked out. And
    the impact point was placed at `wall_r - BALL_WALL_MARGIN_PX`, which is
    outside that same normalized line at every angle but dead centre, so the
    ball was hidden on the very frame it struck the wall as well.
    """
    for seed in range(40):
        anim = _wall_ball(seed)
        frames, struck = _wall_frames(anim, after=40)
        for k, (lift, ellipse_d, hidden, _wall, _ball) in enumerate(frames):
            assert not hidden, (
                f"seed {seed}: ball hidden at frame {k} "
                f"(d={ellipse_d:.4f}, lift={lift:.1f}, struck at {struck})")


def test_the_impact_point_is_the_line_a_live_ball_is_held_at():
    """One line, one expression of it. The carom point and the containment
    step have to agree, or `_step_ball_on_ground` shoves the ball again on
    the next frame and `_point_outside_wall` disagrees about which side of
    the fence it is on."""
    for seed in range(20):
        anim = _wall_ball(seed)
        _frames, _struck = _wall_frames(anim, after=0)
        dx = anim._hit_end[0] - ha.HOME[0]
        dy = ha.HOME[1] - anim._hit_end[1]
        d = math.hypot(dx / ha.WALL_SEMI_X, dy / ha.WALL_SEMI_Y)
        assert d == pytest.approx(ha.BALL_WALL_LIMIT_NORM, abs=1e-9)


def test_the_ball_comes_down_off_the_wall_under_gravity():
    """It hits the fence several feet up and has to get to the grass. Free
    fall from rest, so how long it takes is a consequence of how high it
    hit — not a duration anybody picked."""
    for seed in range(20):
        anim = _wall_ball(seed)
        frames, struck = _wall_frames(anim, after=0)
        height_px, fall_ms = anim._wall_drop
        assert height_px == pytest.approx(frames[struck][0], abs=1e-6)
        expected = anim._anim_ms(
            math.sqrt(2.0 * (height_px / ha.FT_TO_PX_Y) / ball_flight.G_FT_S2))
        assert fall_ms == pytest.approx(expected, rel=1e-3)
        # Monotone down to the grass, never back up.
        lifts = [anim._current_bounce_lift(tau)
                 for tau in range(0, int(fall_ms) + 200, 10)]
        assert all(b <= a + 1e-9 for a, b in zip(lifts, lifts[1:]))
        assert lifts[-1] == 0.0


def test_the_render_peak_constants_are_gone():
    """The per-shape arc peak, in pixels, with no tie to the launch angle or
    the carry — and the three solves that existed only to reconcile it with
    the fence. `_flight_height_ft` is the one model now.

    `INTERCEPT_MAX_LIFT_PX` is in the list for a stronger reason than the
    others: the catch gate does not *convert* a ceiling any more, it reads
    feet, so there is nothing at that seam to keep.
    """
    for name in ("HR_PEAK_H", "FLY_HIT_PEAK_RANGE",
                 "LINER_PEAK_RANGE", "POPUP_PEAK_RANGE"):
        assert not hasattr(ha, name), name
    for name in ("_arc_phase", "_wall_impact_landing_phase",
                 "_home_run_peak_floor"):
        assert not hasattr(HitAnimation, name), name
    anim = _make("IN_PLAY", shape="FLY")
    assert not hasattr(anim, "_hit_peak")
    assert not hasattr(anim, "_arc_landing_phase")


def test_the_superseded_peak_bounds_are_gone():
    """The first two generations of a property nothing solves for any more.

    `WALL_HIT_FLY_PEAK_SCALE` was a guess at it, and `_wall_impact_peak_cap` /
    `WALL_IMPACT_MAX_HEIGHT_FRAC` were the first attempt to solve it — against
    the wrong edge of the fence, and by flattening the arc. The third,
    `_wall_impact_landing_phase`, is gone too (see
    `test_the_render_peak_constants_are_gone`): the drawn arc is the flight the
    verdict was computed from, so the height at the fence is the verdict's own
    number. Keeping any of them would be a second model of one thing."""
    assert not hasattr(ha, "WALL_HIT_FLY_PEAK_SCALE")
    assert not hasattr(ha, "WALL_IMPACT_MAX_HEIGHT_FRAC")
    assert not hasattr(HitAnimation, "_wall_impact_peak_cap")
