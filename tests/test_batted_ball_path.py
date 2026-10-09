import math

import pytest

from strikefactor.gameplay import batted_ball_path as path_model
from strikefactor.gameplay import hit_animation as ha


class _StubBatter:
    def __init__(self, hand="R"):
        self.hand = hand

    def get_handedness(self):
        return self.hand


class _StubSettings:
    def get_difficulty_multipliers(self):
        return {"out_probability_modifier": 1.0}


class _StubGame:
    def __init__(self, hand="R"):
        self.batter = _StubBatter(hand)
        self.settings_manager = _StubSettings()


def test_zero_curve_is_the_old_straight_path():
    path = path_model.BattedBallPath(math.radians(90), 240.0, 0.0)
    assert path.point_ft(0.0) == pytest.approx((0.0, 0.0))
    assert path.point_ft(0.25) == pytest.approx((0.0, 60.0))
    assert path.endpoint_ft == pytest.approx((0.0, 240.0))


def test_curve_builds_gradually_and_moves_the_landing():
    path = path_model.BattedBallPath(0.0, 200.0, 16.0)
    assert path.point_ft(0.5) == pytest.approx((100.0, 4.0))
    assert path.endpoint_ft == pytest.approx((200.0, 16.0))
    # Quadratic growth preserves the original departure tangent instead of
    # making the ball jump sideways immediately at contact.
    assert path.point_ft(0.01)[1] == pytest.approx(0.0016)
    assert path.tangent_ft(0.0) == pytest.approx((200.0, 0.0))
    assert path.tangent_ft(1.0) == pytest.approx((200.0, 32.0))


def test_handedness_mirrors_the_same_contact_turn():
    right = path_model.curve_distance_ft("LINER", 8.0, handedness_sign=1.0)
    left = path_model.curve_distance_ft("LINER", 8.0, handedness_sign=-1.0)
    assert right > 0.0
    assert left == pytest.approx(-right)


def test_live_animation_uses_one_curved_path_for_shadow_and_landing(monkeypatch):
    nominal = ha._to_screen(0.0, 220.0)
    monkeypatch.setattr(ha, "_pick_hit_landing", lambda *a, **k: nominal)
    anim = ha.HitAnimation(
        _StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
        quality=0.8, batted_ball_type="LINER", spray_deg=0.0,
        timing_turn_deg=12.0,
    )

    assert anim.curve_ft > 0.0
    assert anim._hit_end == pytest.approx(
        ha._to_screen(*anim.flight_path.endpoint_ft))
    midpoint = anim._flight_ground_point(0.5)
    straight_midpoint = ha._lerp(ha.HOME, anim._hit_end, 0.5)
    assert midpoint != pytest.approx(straight_midpoint)


def test_curve_cannot_turn_a_fair_ball_foul(monkeypatch):
    # One degree inside the left-field line, where an unrestricted positive
    # bend would move the landing foul.
    nominal = ha._polar_point_ft(math.radians(134.0), 250.0)
    monkeypatch.setattr(ha, "_pick_hit_landing", lambda *a, **k: nominal)
    anim = ha.HitAnimation(
        _StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
        quality=0.8, batted_ball_type="LINER", spray_deg=44.0,
        timing_turn_deg=20.0,
    )
    end_x, end_y = anim.flight_path.endpoint_ft
    end_angle = math.atan2(end_y, end_x)
    assert end_angle <= ha.FOUL_LINE_FIELD_LEFT_RAD - ha.FAIR_DRAW_MARGIN_RAD
