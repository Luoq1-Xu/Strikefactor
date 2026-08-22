"""Balls hit back through the box.

The comebacker is the one trajectory where pure geometry gives a wrong
answer: a ball hit straight up the middle *always* passes within the
pitcher's reach, so a positional fielding model converts every one of
them into a groundout. Real pitchers are compromised fielders — still
recovering from their follow-through — and hard contact through the box
is a base hit far more often than an out.

These guard the three pieces that produce that: the pitcher's
follow-through reaction bias, the per-play clean-fielding roll, and the
infielder ranging cap that stops the 2B/SS from simply inheriting every
ball the pitcher no longer catches.
"""

import collections

import pytest

from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.hit_animation import (
    PITCHER_CLEAN_FIELD_PROB,
    REACTION_DELAY_MAX_S,
    ROLE_REACTION_BIAS_S,
    HitAnimation,
)

OUT_OUTCOMES = ("GROUNDOUT", "LINEOUT", "FLYOUT", "POP UP")


class _StubBatter:
    def get_handedness(self):
        return "R"


class _StubGame:
    def __init__(self):
        self.batter = _StubBatter()


def _make(shape, quality):
    return HitAnimation(
        _StubGame(),
        outcome="IN_PLAY",
        on_complete=lambda: None,
        vertical_offset=0.0,
        quality=quality,
        batted_ball_type=shape,
        spray_deg=0.0,
    )


@pytest.fixture
def up_the_middle(monkeypatch):
    """Force every batted ball dead centre, at a chosen depth in feet."""
    def _aim(depth_ft):
        monkeypatch.setattr(
            ha, "_pick_hit_landing",
            lambda *a, **k: ha._to_screen(0.0, depth_ft),
        )
    return _aim


def _play_out(shape, quality):
    """Run one animation to completion; return (outcome, fielder)."""
    anim = _make(shape, quality)
    t = 0
    while not anim.finished and t < 40000:
        t += 16
        anim.update(t)
    return anim.classified_outcome, anim._primary_role


def _sample(shape, quality, n=200):
    results = [_play_out(shape, quality) for _ in range(n)]
    outs = sum(1 for outcome, _ in results if outcome in OUT_OUTCOMES)
    by_pitcher = sum(1 for _, role in results if role == "P")
    return outs / n, by_pitcher / n


def test_pitcher_reaction_covers_the_follow_through():
    """The bias has to dominate the base see-react window, or the
    pitcher is reacting to contact before they've recovered."""
    assert ROLE_REACTION_BIAS_S["P"] > REACTION_DELAY_MAX_S * 2


def test_hard_grounder_up_the_middle_is_usually_a_hit(up_the_middle):
    up_the_middle(150)
    out_rate, _ = _sample("GROUNDER", quality=0.9)
    assert out_rate < 0.45, f"hard comebacker converted {out_rate:.0%} of the time"


def test_hard_liner_up_the_middle_is_almost_always_a_hit(up_the_middle):
    up_the_middle(160)
    out_rate, _ = _sample("LINER", quality=0.9)
    assert out_rate < 0.20, f"liner through the box converted {out_rate:.0%} of the time"


def test_weak_roller_back_to_the_mound_is_still_an_out(up_the_middle):
    """The flip side: the pitcher must keep converting the dribbler
    they field in real life, or the fix has just deleted the play."""
    up_the_middle(80)
    out_rate, by_pitcher = _sample("GROUNDER", quality=0.05)
    assert out_rate > 0.70, f"weak comebacker only converted {out_rate:.0%} of the time"
    assert by_pitcher > 0.55, "the pitcher should be the one fielding weak rollers"


def test_clean_field_roll_scales_with_contact_quality(up_the_middle):
    up_the_middle(150)
    soft = collections.Counter(_make("GROUNDER", 0.05)._pitcher_fields_clean
                               for _ in range(400))
    hard = collections.Counter(_make("GROUNDER", 0.95)._pitcher_fields_clean
                               for _ in range(400))
    assert soft[True] / 400 > hard[True] / 400 + 0.4


def test_failed_roll_removes_the_pitcher_from_the_intercept_pool(up_the_middle):
    up_the_middle(150)
    anim = _make("GROUNDER", 0.9)
    anim._pitcher_fields_clean = False
    assert "P" not in anim._eligible_intercept_pool()
    anim._pitcher_fields_clean = True
    assert "P" in anim._eligible_intercept_pool()


def test_fly_balls_never_roll_for_clean_fielding(up_the_middle):
    """Lift and pool eligibility already handle these; a roll here would
    silently gate flies on a pitcher stat that shouldn't apply."""
    up_the_middle(250)
    for shape in ("FLY", "POP_UP"):
        assert shape not in PITCHER_CLEAN_FIELD_PROB
        assert _make(shape, 0.9)._pitcher_fields_clean is True


@pytest.mark.parametrize("shape", ["GROUNDER", "LINER", "FLY", "POP_UP"])
def test_middle_infielders_carry_no_range_cap_at_all(up_the_middle, shape):
    """The shape-dependent infield cap is gone on every shape, not relaxed.

    It existed because a correct MLB sprint spent against the animation's
    stretched flight time covered two to three times the honest ground, and
    the cap clawed that back by hand. Flight time is physical now, so the
    correction has nothing left to correct — and leaving it in would double-
    count. The bound that replaced it is time, enforced in
    `tests/test_fielder_pursuit.py`.
    """
    up_the_middle(200)
    anim = _make(shape, 0.9)
    assert anim._max_intercept_dist(anim.fielders["2B"]) == float("inf")


def test_middle_infielders_cannot_reach_a_ball_over_the_bag(up_the_middle):
    """Their homes sit ~50 ft off the centre line, and a hard ball up the
    middle is at the bag well before a fielder can cover that — which is
    what makes it a hit once the pitcher lets it through.

    Stated as time rather than as a clamp: the cap that used to enforce
    this geometrically is gone, so what has to hold is that the sprint
    genuinely does not get there.
    """
    up_the_middle(180)
    anim = _make("LINER", 0.9)
    for role in ("2B", "SS"):
        fielder = anim.fielders[role]
        hit = anim._path_intercept(fielder)
        assert not hit["can_make"], (
            f"{role} was able to cut off a hard liner up the middle")
