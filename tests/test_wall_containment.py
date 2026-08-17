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
    fence for the several seconds the HR animation runs on for."""
    for _ in range(20):
        anim = _make("HOME RUN")
        landed = False
        for t in _play(anim):
            if t > anim.duration_ms:
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
        for t in _play(anim):
            if t > anim.duration_ms:
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
        for t in _play(anim):
            if t <= anim.duration_ms:
                continue        # in flight; a wall candidate is aimed past it
            assert not anim._ball_behind_wall(), (
                "a ball on the ground in the park was hidden")
