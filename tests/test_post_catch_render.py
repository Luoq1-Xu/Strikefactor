"""What the ball does once a fielder has it is decided by what happened.

`_render_post_fielding` owns the ball for two different sub-animations: the
catch hold for a ball taken out of the air, and the throw (or carry) to first
for a grounder an infielder came up with. It used to tell them apart by the
outcome's *name* — `classified_outcome == "FLYOUT"` — so a LINEOUT or a POP UP
fell into the throw-to-first code, and was drawn correctly only because no
throw had been scheduled for it. The throw exists exactly when
`_begin_infield_play` ran, so that is what the renderer asks now.
"""

import random

import pytest

from strikefactor.gameplay.hit_animation import FIRST_BASE_BAG_POS, HitAnimation


class _StubBatter:
    def get_handedness(self):
        return "R"


class _StubGame:
    def __init__(self):
        self.batter = _StubBatter()


def _anim(shape, launch_deg, ev_mph):
    random.seed(11)
    anim = HitAnimation(_StubGame(), "IN_PLAY", lambda: None, quality=0.85,
                        batted_ball_type=shape, spray_deg=0.0,
                        ev_mph=ev_mph, launch_deg=launch_deg)
    anim.update(1000)
    anim.update(1016)
    return anim


@pytest.mark.parametrize("shape,launch,ev,expected", [
    ("LINER", 15.0, 85.0, "LINEOUT"),
    ("FLY", 32.0, 90.0, "FLYOUT"),
    ("POP_UP", 60.0, 80.0, "POP UP"),
])
def test_every_ball_caught_in_the_air_stays_in_the_glove(shape, launch, ev, expected):
    anim = _anim(shape, launch, ev)
    catcher = "SS"
    anim._trigger_in_flight_intercept(catcher, tuple(anim.fielders[catcher].pos))
    assert anim.classified_outcome == expected
    assert anim._go_first_base_pos is None, "a catch never begins an infield play"

    fielder = anim.fielders[catcher]
    t = 1016
    while not anim.finished:
        t += 16
        # Nudge the catcher, so a ball merely left where the catch fired
        # would be caught out.
        fielder.pos[0] += 0.5
        anim.update(t)
        assert anim._ball == (fielder.pos[0], fielder.pos[1])
        assert anim._ball_shadow == anim._ball
        assert t < 20_000


def test_a_fielded_grounder_still_gets_its_throw_to_first():
    anim = _anim("GROUNDER", 3.0, 90.0)
    anim._trigger_in_flight_intercept("SS", tuple(anim.fielders["SS"].pos))
    assert anim._go_first_base_pos == FIRST_BASE_BAG_POS
    assert anim._go_throw_start_ms is not None, "the SS is far from the bag: it throws"

    t = 1016
    while not anim.finished:
        t += 16
        anim.update(t)
        assert t < 20_000
    assert anim._ball == FIRST_BASE_BAG_POS
