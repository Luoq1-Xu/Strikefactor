"""Ball carriers turn with momentum and tag physical runners between poses."""

import math
from types import SimpleNamespace

import pytest

from strikefactor.gameplay import rundown
from strikefactor.gameplay.base_geometry import BASE_FT
from strikefactor.gameplay.runner_motion import CircuitRun


def test_a_chasing_fielder_has_to_brake_before_reversing():
    path = rundown.Pursuit((0, 0), (27, 0), (-30, 0), 0, 27, 0.6)
    assert path.position_at(0.02)[0] > 0
    assert path.velocity_at(0.02)[0] > 0
    assert math.dist(path.velocity_at(0), path.velocity_at(0.02)) <= 27/0.6*0.02 + 1e-9
    assert path.velocity_at(1.2) == pytest.approx((-27, 0))


def test_swept_tag_finds_contact_when_both_endpoint_poses_are_outside_reach():
    path = rundown.Pursuit((20, 30), (1000, 0), (2020, 30), 0, 1000, 1)
    route = SimpleNamespace(position_at=lambda t: (30-1000*t, 30), contacts=lambda base: ())
    assert math.dist(path.position_at(0), route.position_at(0)) > rundown.TAG_REACH_FT
    assert math.dist(path.position_at(0.01), route.position_at(0.01)) > rundown.TAG_REACH_FT
    contact_s = rundown.tag_contact_s(path, route, 0, 0.01)
    assert contact_s == pytest.approx(0.0035)
    assert math.dist(path.position_at(contact_s), route.position_at(contact_s)) <= rundown.TAG_REACH_FT


def test_a_past_base_touch_does_not_protect_an_off_base_runner():
    route = CircuitRun(None, 27, start_base=1)
    assert rundown.on_base(route, 0)
    route.commit_next(1)
    assert not rundown.on_base(route, 2)
    assert route.base_at(2) == 1
    assert rundown.on_base(route, route.arrival_s)


def test_a_runner_holding_a_bag_cannot_be_tagged():
    route = CircuitRun(None, 27, start_base=1)
    path = rundown.Pursuit(BASE_FT[1], (0, 0), BASE_FT[1], 0, 27, 0.6)
    assert rundown.tag_contact_s(path, route, 0, 0.016) is None
