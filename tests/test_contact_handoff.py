"""The handoff from a resolved contact to the animation that flies it.

`PitchSimulation._evaluate_contact` is where one `Contact` becomes everything
downstream reads: the exit velocity, the launch angle, the bearing, the shape,
and then a `HitAnimation` built from them. Nothing drove that path end to end,
which is how it could have gone on handing the animation a vertical offset to
work a second launch angle out of.

What is pinned here is that the animation is handed the contact's own numbers
— the two readings of the one exit direction the collision stamped — on all
three roads out of a contact: a ball in play, a home run and a foul.
"""

from types import SimpleNamespace

import pytest

from strikefactor.gameplay import ball_flight, spray
from strikefactor.gameplay import bat_contact as bc
from strikefactor.gameplay import bat_path as bp
from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager
from strikefactor.gameplay.pitch_simulation import PitchSimulation
from strikefactor.helpers import ScoreKeeper
from tools import calibrate_contact as harness

HANDS = ("R", "L")


def _contact(hand, bat_over_in=0.0, timing_ms=0.0, x=0.0, z=2.5, **kw):
    """A real contact, with the cursor `bat_over_in` above the ball."""
    tr = harness._pitch(hand, x, z, 93.0)
    cx, cz = harness._cursor_on_ball(tr)
    swing = bp.swing(bc.aim_at_pitch((cx, cz + bat_over_in / 12.0), tr, hand),
                     hand)
    start = (tr.time_at_depth(swing.contact_depth_ft) - bp.SWING_DURATION_S
             + timing_ms / 1000.0)
    got = bc.resolve_contact(swing, tr, start, **kw)
    assert got is not None
    return got


def _sim(hand, contact, on_time):
    """A `PitchSimulation` at the frame the contact becomes visible, on a game
    that is just enough game to build the animation."""
    shown = []
    score_keeper = ScoreKeeper()
    game = SimpleNamespace(
        hit_outcome_manager=HitOutcomeManager(score_keeper, None),
        scoreKeeper=score_keeper,
        gameday_manager=None, in_gameday_mode=False,
        batter=SimpleNamespace(get_handedness=lambda: hand),
        settings_manager=SimpleNamespace(
            get_setting=lambda name: True,
            get_defense_level=lambda: "league",
            get_difficulty_multipliers=lambda: {"out_probability_modifier": 1.0}),
        field_renderer=SimpleNamespace(record_at_bat=lambda: None,
                                       record_hit=lambda *a, **k: None),
        ui_manager=SimpleNamespace(show_banner=shown.append),
        _display_pitch_results=lambda *a: shown.append(a[0]),
        ball=[630.0, 480.0], fourseamballsize=9, last_pitch_information=[],
        strikes=0, pitchnumber=0, currentstrikes=0, currentballs=0,
        currentouts=0, hits=0, homeruns_allowed=0,
    )
    sim = object.__new__(PitchSimulation)
    sim.game = game
    sim.contact = contact
    sim.on_time = on_time
    sim.swing_type = 1
    sim.new_entry = {}
    sim.pitchtype, sim.speed_mph = "FOUR-SEAM", 93.0
    sim.is_strike = sim.is_hit = False
    sim.made_contact = "no_swing"
    sim.pitch_results_done = False
    # What `__init__` leaves unset until a ball in play fills it in.
    sim.hit_animation = None
    sim.batted_ball_type = None
    sim._evaluate_contact()
    return sim, shown


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("bat_over_in,timing_ms", [(0.0, 0.0), (0.6, 0.0),
                                                  (-0.5, 0.0), (0.0, 12.0)])
def test_a_ball_in_play_is_flown_on_the_contacts_own_direction(hand, bat_over_in,
                                                              timing_ms):
    contact = _contact(hand, bat_over_in, timing_ms, timing_window_mult=0.2)
    assert not contact.is_foul(0.05)
    sim, _ = _sim(hand, contact, on_time=2)
    anim = sim.hit_animation

    assert sim.launch_angle_deg == contact.launch_deg
    assert sim.spray_angle_deg == contact.spray_deg
    assert sim.departure_deg == contact.spray_deg, "a fair ball is not deflected"
    assert sim.batted_ball_type == ball_flight.shape_for_launch_angle(
        contact.launch_deg)

    assert anim is not None, "the contact never reached an animation"
    assert anim.launch_deg == contact.launch_deg
    assert anim.exit_velocity_mph == sim.exit_velocity_mph
    if anim.outcome != "HOME RUN":
        assert anim.shape == sim.batted_ball_type
    assert anim.spray_deg == contact.spray_deg
    assert anim.spray_field_rad == pytest.approx(
        spray.field_angle_rad(contact.spray_deg, spray.spin_for(hand)))
    # The DB still records the offset in screen pixels; nothing reads it back.
    assert sim.vertical_offset_in == pytest.approx(
        HitOutcomeManager.contact_metrics(contact)[1])


@pytest.mark.parametrize("hand", HANDS)
def test_the_fence_is_asked_about_the_same_flight_the_animation_draws(hand):
    """A ball struck for a line drive at a home-run exit velocity. The verdict
    is `park.fence_verdict` of this launch angle, this exit velocity and this
    bearing, and the animation is then built from the same three."""
    from strikefactor.engine import contact_audio
    from strikefactor.gameplay import park

    contact = _contact(hand, bat_over_in=-0.2)
    field_rad = spray.field_angle_rad(contact.spray_deg, spray.spin_for(hand))
    assert park.fence_verdict(contact.launch_deg, contact_audio.EV_CEIL_MPH,
                              field_rad) == park.OUT_OF_PARK, (
        "the fixture has to be a ball that leaves the park when crushed")

    score_keeper = ScoreKeeper()
    manager = HitOutcomeManager(score_keeper, None)
    assert manager.hit_outcome(contact, contact.launch_deg,
                               contact_audio.EV_CEIL_MPH, hand) == "HOME RUN"
    assert manager.hit_outcome(contact, contact.launch_deg, 70.0,
                               hand) == "IN_PLAY"


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("bat_over_in", [2.6, -2.2])
def test_a_foul_is_flown_where_the_deflection_sent_it(hand, bat_over_in):
    """A ball the bat only tipped. The shape is the band its own launch angle
    falls in and the bearing is `spray.foul_departure_deg` of the collision's,
    both settled once and handed over."""
    contact = _contact(hand, bat_over_in)
    assert contact.is_foul()
    sim, _ = _sim(hand, contact, on_time=1)
    anim = sim.hit_animation

    shape = ball_flight.shape_for_launch_angle(contact.launch_deg)
    assert sim._foul_shape == shape
    assert sim.batted_ball_type is None, "a foul must not widen the DB column"
    assert sim.spray_angle_deg == contact.spray_deg
    assert sim.departure_deg == spray.foul_departure_deg(
        contact.spray_deg, contact.quality, shape)
    assert spray.is_foul(sim.departure_deg)

    assert anim is not None and anim.outcome == "FOUL"
    assert anim.shape == shape
    assert anim.spray_deg == sim.departure_deg
    assert anim.launch_deg == contact.launch_deg
    assert anim.exit_velocity_mph == sim.exit_velocity_mph
    assert sim.outcome == "foul"
