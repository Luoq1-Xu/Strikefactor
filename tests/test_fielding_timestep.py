"""A host-frame stutter must not skip an airborne catch opportunity."""

import math
import random
from types import SimpleNamespace

import pytest

from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.fielding_record import FieldingRecorder


def _grazing_liner(monkeypatch):
    random.seed(76)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: "R"), currentouts=0)
    anim = ha.HitAnimation(game, "IN_PLAY", lambda: None, quality=0.8,
        batted_ball_type="LINER", ev_mph=95, launch_deg=14, spray_deg=18)

    def ground(time_ms):
        return anim._flight_ground_point(anim._flight_path_fraction(time_ms/anim.duration_ms))

    # A stationary glove grazes the descending liner around 2160 ms. Its
    # roughly 18 ms window lies wholly between the 2150 and 2200 ms poses.
    point = ground(2160)
    delta = tuple(b-a for a, b in zip(ground(2159), ground(2161)))
    speed = math.hypot(*delta)/2
    offset = math.sqrt(ha.INTERCEPT_REACH_PX**2 - (speed*9)**2)
    fielder = anim.fielders["CF"]
    fielder.pos[:] = (point[0]-delta[1]*offset/(2*speed), point[1]+delta[0]*offset/(2*speed))
    fielder.home_pos = tuple(fielder.pos)
    fielder.reaction_delay_ms = 0
    anim._primary_role = "CF"
    monkeypatch.setattr(anim, "_eligible_intercept_pool", lambda: ("CF",))
    monkeypatch.setattr(anim, "_step_fielder", lambda *args: None)
    rolls = []

    def clean(*args, **kwargs):
        rolls.append(1)

    monkeypatch.setattr(anim, "_roll_misplay", clean)
    return anim, rolls


@pytest.mark.parametrize("frames", [(8,), (16,), (50,), (250,), (8, 16, 50, 250)])
def test_stutters_preserve_a_short_liner_catch_and_its_replay_pose(monkeypatch, frames):
    anim, rolls = _grazing_liner(monkeypatch)
    anim.update(0)
    recorder = FieldingRecorder(anim, "grazing liner")
    time_ms, i = 0, 0
    while time_ms < 2500:
        time_ms = min(2500, time_ms+frames[i % len(frames)])
        anim.update(time_ms)
        recorder.capture(anim)
        i += 1
    assert anim._secured_in_flight
    assert anim.classified_outcome == "LINEOUT"
    assert 2150 < anim._secured_at_ms < 2200
    assert rolls == [1]
    caught = next(f for f in recorder.frames if f.time_ms == anim._secured_at_ms)
    assert caught.shadow == pytest.approx(tuple(anim.fielders["CF"].pos))


def test_fixture_exposes_the_original_unsplit_frame_failure(monkeypatch):
    monkeypatch.setattr(ha, "MAX_UPDATE_STEP_MS", float("inf"))
    anim, rolls = _grazing_liner(monkeypatch)
    anim.update(0)
    for time_ms in range(50, 2201, 50):
        anim.update(time_ms)
    assert not anim._secured_in_flight
    assert not rolls
