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

from strikefactor.gameplay import ball_flight
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

FENCE_TOP_PX = ha.WALL_HEIGHT_FT * ha.FT_TO_PX_Y


def _wall_ball(seed):
    """A ball that will strike the fence on the fly.

    `_is_wall_candidate` asks `ball_flight` whether the carry reaches
    WALL_REACH_FT, so a max-quality FLY qualifies every time.

    The spray is spread across the outfield on purpose. Built without one,
    every ball goes to *exactly* dead centre — the one bearing at which the
    ellipse's radius equals the semi-axis BALL_WALL_LIMIT_NORM is
    normalized against, so the two ways of expressing the containment line
    coincide and the defect they disagree about is invisible.
    """
    import random
    random.seed(seed)
    anim = HitAnimation(_StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
                        quality=1.0, batted_ball_type="FLY",
                        spray_deg=-28.0 + (seed % 15) * 4.0)
    assert anim._is_wall_candidate, "expected a ball aimed past the fence"
    return anim


def _wall_frames(anim, after=10):
    """Frames around the carom: (lift_px, ellipse_d, hidden, wall_hit)."""
    frames = []
    struck = None
    for _t in _play(anim):
        dx = anim._ball_shadow[0] - ha.HOME[0]
        dy = ha.HOME[1] - anim._ball_shadow[1]
        frames.append((
            anim._ball_shadow[1] - anim._ball[1],
            math.hypot(dx / ha.WALL_SEMI_X, dy / ha.WALL_SEMI_Y),
            anim._ball_behind_wall(),
            anim._wall_hit,
        ))
        if anim._wall_hit:
            if struck is None:
                struck = len(frames) - 1
            elif len(frames) > struck + after:
                break
    assert struck is not None, "never reached the wall"
    return frames, struck


def test_a_ball_off_the_wall_strikes_the_face_and_not_the_sky():
    """The ball has to be *below the top of the fence* when it gets there.

    Nothing asked before: the arc is aimed 5–35 ft past the fence and the
    height at the fence was whatever fell out of it. Measured over 162 wall
    balls, 54% were drawn above the fence top at the moment of impact —
    median 12 px against an 11 px fence, out to 27.8 px — which is a ball
    that visibly cleared the wall and was then planted on the grass.
    `WALL_HIT_FLY_PEAK_SCALE = 0.60` was supposed to prevent this and could
    not; `_wall_impact_peak_cap` solves for it instead.
    """
    for seed in range(40):
        anim = _wall_ball(seed)
        frames, struck = _wall_frames(anim)
        # Both the frame it strikes the fence and the last one before it.
        # The impact frame alone would be a tautology: the old code planted
        # the ball on the grass there, so it read 0 px up — the ball the
        # player saw over the wall was the frame before, still on its arc.
        assert frames[struck][0] <= ha.WALL_IMPACT_MAX_HEIGHT_FRAC * FENCE_TOP_PX + 0.5
        for lift, _d, _hidden, _wall in frames[struck - 1:struck + 1]:
            assert lift <= FENCE_TOP_PX, (
                f"reached the fence {lift:.1f} px up, over a "
                f"{FENCE_TOP_PX:.1f} px fence")


def test_the_ball_never_teleports_at_the_wall():
    """The visible artifact, measured directly: how far the drawn ball can
    move *downward* in a single frame.

    It used to drop the whole way from wherever the arc had it to the grass
    in one frame — 19 to 31 px on the balls sampled. It now falls down the
    face under gravity, so the largest step is a fraction of a pixel."""
    worst = 0.0
    for seed in range(40):
        anim = _wall_ball(seed)
        frames, _struck = _wall_frames(anim, after=40)
        lifts = [f[0] for f in frames]
        worst = max(worst, max(lifts[k] - lifts[k + 1] for k in range(len(lifts) - 1)))
    assert worst < 4.0, f"the ball dropped {worst:.1f} px in one frame"


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
        for k, (lift, ellipse_d, hidden, _wall) in enumerate(frames):
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


def test_the_superseded_peak_scale_is_gone():
    """`WALL_HIT_FLY_PEAK_SCALE` was a guess at the property
    `_wall_impact_peak_cap` now solves for. Keeping both would be two models
    of one thing — and the guess is the one that was wrong on 54% of
    caroms."""
    assert not hasattr(ha, "WALL_HIT_FLY_PEAK_SCALE")
