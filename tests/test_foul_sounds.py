"""What a foul sounds like, and how big a ball is drawn the higher it goes.

A fielding play has no speaker: `HitAnimation` says what happened and how
loud (`take_sound_cues`), and only the play on screen turns that into sound
(`PitchSimulation._play_animation_sounds` -> `SoundManager.play_cue`). So a
foul played out of sight, a replay, and every calibration sweep are silent by
construction.
"""

import os
import random
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from strikefactor.config import get_path
from strikefactor.engine.sound_manager import SoundManager
from strikefactor.gameplay import defense as defense_model
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.fielding_record import FieldingFrame
from strikefactor.gameplay.pitch_simulation import PitchSimulation
from strikefactor.ui.fielding_renderer import draw_frame
from tools import make_net_thud

HANDS = ("R", "L")


def _anim(outcome, shape, dep, launch, ev, *, hand="R", seed=1):
    random.seed(seed)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: hand),
                           currentouts=0, game_mode="arcade")
    return ha.HitAnimation(game, outcome, lambda: None, quality=0.6,
                           batted_ball_type=shape, spray_deg=dep, ev_mph=ev,
                           launch_deg=launch, initial_bases=())


def _cues(anim, step=16):
    """Every cue the play made, collected a frame at a time as the game does."""
    heard = []
    t = 0
    while not anim.finished and t < 30000:
        anim.update(t)
        heard.extend(anim.take_sound_cues())
        t += step
    return heard


@pytest.fixture
def sure_hands(monkeypatch):
    monkeypatch.setattr(defense_model, "roll_misplay", lambda *a, **k: None)


# ---- The cues -----------------------------------------------------------------

def test_every_cue_a_play_can_make_has_a_sound():
    cues = {v for k, v in vars(ha).items() if k.startswith("CUE_")}
    assert cues == set(SoundManager.CUES)
    assert os.path.exists(get_path(os.path.join(
        "assets/sounds", SoundManager.SOUND_FILES["net_thud"])))


@pytest.mark.parametrize("hand", HANDS)
def test_a_caught_foul_is_heard_once_and_louder_near_the_plate(hand, sure_hands):
    near = _cues(_anim("FOUL", "POP_UP", 175.0, 85.0, 65.0, hand=hand))   # the catcher's
    far = _cues(_anim("FOUL", "POP_UP", 55.0, 66.0, 72.0, hand=hand))     # by the dugout
    assert [c for c, _ in near] == [ha.CUE_CATCH]
    assert [c for c, _ in far] == [ha.CUE_CATCH]
    assert 0.0 < far[0][1] < near[0][1] <= 1.0


@pytest.mark.parametrize("hand", HANDS)
def test_a_ball_into_the_net_is_heard_once(hand):
    liner = _cues(_anim("FOUL", "LINER", 172.0, 15.0, 78.0, hand=hand))
    chopper = _cues(_anim("FOUL", "GROUNDER", 150.0, -10.0, 75.0, hand=hand))
    assert [c for c, _ in liner] == [ha.CUE_NET]
    assert [c for c, _ in chopper] == [ha.CUE_NET]
    assert all(0.0 < gain <= 1.0 for _, gain in liner + chopper)


def test_the_net_is_louder_the_harder_the_ball_was_hit():
    soft = _cues(_anim("FOUL", "LINER", 172.0, 15.0, 60.0))
    hard = _cues(_anim("FOUL", "LINER", 172.0, 15.0, 90.0))
    assert soft[0][1] < hard[0][1]


@pytest.mark.parametrize("shape,dep,launch,ev", [
    ("POP_UP", 165.0, 60.0, 75.0),       # over the net, into the seats behind
    ("GROUNDER", 179.0, -20.0, 66.0),    # off the catcher's gear
    ("FLY", -70.0, 35.0, 80.0),          # into the seats down the line
])
def test_a_foul_that_never_reaches_the_net_or_a_glove_is_silent(shape, dep, launch, ev):
    assert _cues(_anim("FOUL", shape, dep, launch, ev)) == []


def test_a_fair_ball_makes_no_new_sound(sure_hands):
    assert _cues(_anim("IN_PLAY", "POP_UP", 10.0, 60.0, 80.0)) == []
    assert _cues(_anim("IN_PLAY", "FLY", 5.0, 30.0, 90.0)) == []


def test_collecting_the_cues_empties_them(sure_hands):
    anim = _anim("FOUL", "LINER", 172.0, 15.0, 78.0)
    _cues(anim)
    assert anim.take_sound_cues() == []


def test_the_play_on_screen_hands_its_cues_to_the_speaker():
    played = []
    sim = object.__new__(PitchSimulation)
    sim.game = SimpleNamespace(sound_manager=SimpleNamespace(
        play_cue=lambda cue, gain: played.append((cue, gain))))
    sim.hit_animation = SimpleNamespace(take_sound_cues=lambda: [(ha.CUE_NET, 0.7)])
    sim._play_animation_sounds()
    assert played == [(ha.CUE_NET, 0.7)]


class _Channel:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def set_volume(self, v):
        self.log.append((self.name, v))


class _Sound:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def play(self):
        return _Channel(self.log, self.name)


@pytest.mark.parametrize("cue,expect", [("catch", "mitt_pop_"), ("net", "net_thud")])
def test_each_cue_plays_its_sample_at_its_gain(cue, expect):
    log = []
    manager = SoundManager.__new__(SoundManager)
    manager.settings_manager = None
    manager.strike_sounds = manager.ball_sounds = []
    manager.sounds = {name: _Sound(log, name) for name in
                      ("mitt_pop_short", "mitt_pop_medium", "mitt_pop_long", "net_thud")}
    manager.play_cue(cue, 0.4)
    assert len(log) == 1
    name, volume = log[0]
    assert name.startswith(expect) and volume == pytest.approx(0.4)


# ---- The net thud itself --------------------------------------------------------

def test_the_net_thud_is_the_same_sound_every_time():
    a, b = make_net_thud.synthesize(), make_net_thud.synthesize()
    assert np.array_equal(a, b)
    assert np.max(np.abs(a)) == pytest.approx(10 ** (make_net_thud.PEAK_DBFS / 20.0))
    assert a.size == int(make_net_thud.SAMPLE_RATE * make_net_thud.DURATION_S)


def test_the_net_thud_is_mostly_where_a_small_speaker_can_play_it():
    x = make_net_thud.synthesize()
    power = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(x.size, 1.0 / make_net_thud.SAMPLE_RATE)
    assert power[freqs >= 150.0].sum() / power.sum() > 0.5


# ---- The ball's size --------------------------------------------------------------

def test_the_ball_keeps_its_size_up_to_a_little_over_the_fence():
    """Every guarantee about the drawn ball at the wall is stated at
    BALL_RADIUS_PX, so nothing near the fence may change size."""
    for height_ft in (0.0, 5.0, 12.0, ha.BALL_GROWTH_START_FT):
        assert ha.drawn_ball_radius_px(height_ft * ha.FT_TO_PX_Y) == ha.BALL_RADIUS_PX


def test_the_ball_grows_with_height_and_stops_growing():
    sizes = [ha.drawn_ball_radius_px(h * ha.FT_TO_PX_Y) for h in range(0, 300, 5)]
    assert sizes == sorted(sizes)
    assert sizes[-1] == ha.BALL_MAX_RADIUS_PX
    assert ha.drawn_ball_radius_px(-10.0) == ha.BALL_RADIUS_PX


def test_a_home_run_is_still_drawn_clear_of_the_rim_at_any_height():
    """Above BALL_GROWTH_START_FT the lift outgrows the radius, so a ball over
    the fence stays wholly over the drawn rim however big it is drawn."""
    for height_ft in np.arange(ha.BALL_GROWTH_START_FT, 200.0, 0.5):
        lift_px = height_ft * ha.FT_TO_PX_Y
        radius = ha.drawn_ball_radius_px(lift_px)
        assert lift_px - radius >= ha.WALL_FACE_HEIGHT_PX - 0.5, height_ft


def _drawn_ball_width(lift_px):
    screen = pygame.Surface((1280, 720))
    screen.fill((0, 0, 0))
    ball = (640.0, 300.0 - lift_px)
    frame = FieldingFrame(0, ball, (640.0, 300.0), True, False, (), None, None,
                          None, None, (), None, None, ())
    draw_frame(screen, frame)
    # Only the ball is pure white in a column above the shadow.
    column = [x for x in range(600, 681)
              if screen.get_at((x, int(ball[1]))) == pygame.Color(255, 255, 255)]
    return len(column)


def test_a_pop_up_is_drawn_bigger_than_a_grounder():
    assert _drawn_ball_width(100.0 * ha.FT_TO_PX_Y) > _drawn_ball_width(0.0)
