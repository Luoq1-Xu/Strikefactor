"""Foul-ball animation guards.

The FOUL outcome is purely cosmetic — the count/DB/AI effects are already
settled by pitch_simulation before the animation starts — but the animation
must (a) not be coerced into a live in-play ball (which would wait forever
for a fielder to secure it), (b) land in foul territory on the side implied
by the signed swing timing, and (c) never show a distance readout — that
overlay belongs to home runs, including on the barreled-but-barely-late
"foul home run", which keeps the deep flight but not the number.
"""

import math

import pytest

from strikefactor.gameplay.hit_animation import (
    FT_TO_PX_X,
    FT_TO_PX_Y,
    HOME,
    HitAnimation,
    _wall_r_at,
)


class _StubBatter:
    def __init__(self, hand):
        self._hand = hand

    def get_handedness(self):
        return self._hand


class _StubGame:
    def __init__(self, hand="R"):
        self.batter = _StubBatter(hand)


def _make(hand="R", timing=0.5, voff=0.0, quality=0.3):
    """A foul, mistimed by `timing` in [-1, 1] — negative early, positive late.

    `timing` used to be `foul_timing_norm`, which the animation read directly
    and turned into a side of the field. The animation reads a *bearing* now
    (`spray_deg`), so this converts: an early swing turns the bat further
    round and hooks the ball toward the pull-side pole, a late one leaves it
    open and slices it the other way. Same physical claim the old constant
    encoded, one model earlier — see `spray`.
    """
    spray_deg = -timing * 70.0
    return HitAnimation(
        _StubGame(hand),
        outcome="FOUL",
        on_complete=lambda: None,
        vertical_offset=voff,
        quality=quality,
        batted_ball_type=None,
        spray_deg=spray_deg,
    )


def _real_field_angle_deg(anim):
    """Landing bearing in *real-field* coordinates, by inverting the
    anisotropic screen projection. 90° = CF; the actual foul lines are at
    exactly 45° (1B/RF) and 135° (3B/LF) in this space, for landings picked
    in either coordinate space (the projection is linear, so it maps the
    foul half-planes onto each other exactly).

    This inversion matters: asserting on the raw screen-space bearing with
    50°/130° thresholds is what let the original foul-HR bug through — a
    ball can sit past 130° on screen yet still be well inside the rendered
    fair territory, whose foul lines project to ~30.7°/149.3°.
    """
    x_ft = (anim._hit_end[0] - HOME[0]) / FT_TO_PX_X
    y_ft = (HOME[1] - anim._hit_end[1]) / FT_TO_PX_Y
    return math.degrees(math.atan2(y_ft, x_ft))


def test_foul_outcome_is_not_coerced_to_in_play():
    anim = _make()
    assert anim.outcome == "FOUL"
    assert anim._needs_secure is False
    assert anim.classified_outcome == "FOUL"


def test_foul_finishes_on_timeout_without_securing():
    anim = _make()
    anim.update(1000)
    assert not anim.finished
    anim.update(1000 + anim.duration_ms + 1)
    assert anim.finished


@pytest.mark.parametrize("hand,timing,side", [
    ("R", -0.6, "left"),   # early RHB pulls foul past the 3B/LF line
    ("R", +0.6, "right"),  # late RHB glances oppo past the 1B/RF line
    ("L", -0.6, "right"),  # early LHB pulls toward RF
    ("L", +0.6, "left"),   # late LHB goes oppo toward LF
])
def test_foul_direction_follows_signed_timing(hand, timing, side):
    # voff=0 -> LINER shape; severity 0.6 > FOUL_HR_MAX_SEVERITY so the
    # HR gate can't reroute the landing regardless of the quality roll.
    anim = _make(hand=hand, timing=timing, voff=0.0, quality=0.5)
    angle = _real_field_angle_deg(anim)
    if side == "left":
        assert angle > 135.0, f"expected LF-side foul, got {angle:.1f} deg (real field)"
    else:
        assert angle < 45.0, f"expected RF-side foul, got {angle:.1f} deg (real field)"


def test_severe_undercut_pops_straight_back():
    anim = _make(voff=40.0, quality=0.3)
    assert anim.shape == "POP_UP"
    # Behind the plate, still on the visible apron.
    assert anim._hit_end[1] > HOME[1]
    assert anim._hit_end[1] <= 712.0
    assert 0 <= anim._hit_end[0] <= 1280


def test_severe_overcut_is_a_short_foul_grounder():
    anim = _make(voff=-40.0, quality=0.3)
    assert anim.shape == "GROUNDER"
    dist = math.hypot(anim._hit_end[0] - HOME[0], anim._hit_end[1] - HOME[1])
    assert dist < 250.0
    assert anim.hr_distance_ft is None


def test_barreled_near_miss_is_a_foul_home_run():
    anim = _make(timing=0.3, voff=3.0, quality=0.95)
    assert anim.shape == "FLY"
    assert anim.is_foul_hr
    # Wall clearance is a screen-space question (the wall is a screen ellipse).
    screen_angle = math.atan2(HOME[1] - anim._hit_end[1],
                              anim._hit_end[0] - HOME[0])
    dist = math.hypot(anim._hit_end[0] - HOME[0], anim._hit_end[1] - HOME[1])
    assert dist > _wall_r_at(screen_angle), "foul HR must carry past the wall"
    # Foul/fair is a real-field question — this is the assertion that would
    # have caught the fair-looking "foul HR" bug.
    angle = _real_field_angle_deg(anim)
    assert angle < 45.0 or angle > 135.0, (
        f"foul HR landed at {angle:.1f} deg real-field — inside fair territory")


@pytest.mark.parametrize("hand,timing", [
    ("R", -0.3), ("R", +0.3), ("L", -0.3), ("L", +0.3),
])
def test_foul_hr_lands_foul_on_the_correct_side(hand, timing):
    anim = _make(hand=hand, timing=timing, voff=3.0, quality=0.95)
    assert anim.is_foul_hr
    pull_left = (hand == "R") == (timing < 0)   # early=pull; RHB pulls to LF
    angle = _real_field_angle_deg(anim)
    if pull_left:
        assert angle > 135.0, f"expected LF-side foul HR, got {angle:.1f} deg"
    else:
        assert angle < 45.0, f"expected RF-side foul HR, got {angle:.1f} deg"


@pytest.mark.parametrize("timing,voff,quality", [
    (0.9, 0.0, 0.4),     # modest foul
    (0.3, 3.0, 0.95),    # foul "home run" — deep flight, still no number
    (0.5, -40.0, 0.3),   # severe overcut, foul grounder
    (0.5, 40.0, 0.3),    # severe undercut, pop straight back
])
def test_no_foul_ever_shows_a_distance(timing, voff, quality):
    anim = _make(timing=timing, voff=voff, quality=quality)
    assert anim.hr_distance_ft is None


def test_actual_home_run_still_shows_a_distance():
    """The counterpart guard: suppressing fouls must not suppress home runs."""
    anim = HitAnimation(
        _StubGame("R"),
        outcome="HOME RUN",
        on_complete=lambda: None,
        vertical_offset=3.0,
        quality=0.95,
        batted_ball_type=None,
        spray_deg=8.0,
    )
    assert anim.hr_distance_ft is not None
    assert 300 < anim.hr_distance_ft < 550


def test_settings_default_enables_foul_animation():
    from strikefactor.settings_manager import SettingsManager

    sm = SettingsManager()
    assert sm.default_settings["foul_animation_enabled"] is True
    assert sm.get_setting("foul_animation_enabled") in (True, False)
