"""A short line drive picked up on the grass can still be thrown to first."""

import random

from strikefactor.gameplay import hit_animation as ha


class _Batter:
    def get_handedness(self):
        return "R"


class _Game:
    batter = _Batter()


def _fielded_liner(role="SS", fielded_ms=800.0):
    random.seed(13)
    anim = ha.HitAnimation(_Game(), "IN_PLAY", lambda: None, quality=0.8,
                           batted_ball_type="LINER", spray_deg=0.0,
                           ev_mph=90.0, launch_deg=12.0)
    fielder = anim.fielders[role]
    anim._primary_role = role
    anim._ball = anim._ball_shadow = tuple(fielder.pos)
    anim._secured = True
    anim._secured_at_ms = anim._elapsed = fielded_ms
    return anim


def test_infielder_picking_up_a_short_liner_runs_the_throw_to_first_race():
    anim = _fielded_liner()
    anim._resolve_extra_bases()

    assert anim.play_timing is not None
    assert anim.play_timing.p_out > 0.99
    assert anim.classified_outcome == "GROUNDOUT"
    assert anim._post_fielding
    assert anim._go_first_base_pos == ha.FIRST_BASE_BAG_POS
    assert anim.extra_base_margin_s is None


def test_liner_fielded_in_the_outfield_uses_the_base_advance_race():
    anim = _fielded_liner(role="CF", fielded_ms=4000.0)
    anim._resolve_extra_bases()

    assert anim.play_timing is None
    assert anim.classified_outcome in {"SINGLE", "DOUBLE", "TRIPLE"}
    assert anim.extra_base_margin_s is not None
