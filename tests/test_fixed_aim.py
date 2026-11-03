"""Sandbox's FIXED AIM: every pitch crosses the plate on the player's spot.

The override lives on the pitcher only inside `Pitcher.aimed_at`, which wraps
the one blocking `pitch()` call, because the pitchers are shared with Arcade
and GameDay. Inside it the location model is skipped entirely: no intent, no
sequence bias, no command error. The intent it records says so, the database
row says so (`aimed_by`, v15), and the pitch-choice AI doesn't learn from it.
"""

import random
import sqlite3
from types import SimpleNamespace

import pygame
import pytest

from strikefactor.data.pitch_database import SCHEMA_VERSION, PitchDatabaseService, PitchDB
from strikefactor.gameplay.field_renderer import FieldRenderer
from strikefactor.gameplay.game_states import SandboxGameplayState
from strikefactor.gameplay.pitch_simulation import PitchSimulation
from strikefactor.pitchers.Degrom import Degrom
from strikefactor.pitchers.Mcclanahan import Mcclanahan
from strikefactor.pitchers.pitch_locations import INTENTS
from strikefactor.pitchers.pitcher import PitchIntent
from strikefactor.pitchers.Sale import Sale
from strikefactor.pitchers.Sasaki import Sasaki
from strikefactor.pitchers.Yamamoto import Yamamoto
from strikefactor.utils.pitch_physics import DEFAULT_CAMERA, PitchTrajectory

COUNTS = [(0, 0), (1, 1), (0, 2), (3, 0), (3, 2)]

_LIMIT_X = SandboxGameplayState.AIM_X_LIMIT_FT
_Z_LO, _Z_HI = SandboxGameplayState.AIM_Z_RANGE_FT
# The aim area's corners, the zone's corners and the middle, in feet.
SPOTS_FT = [(-_LIMIT_X, _Z_LO), (_LIMIT_X, _Z_LO), (-_LIMIT_X, _Z_HI), (_LIMIT_X, _Z_HI),
            (-0.708, 1.5), (0.708, 3.5), SandboxGameplayState.AIM_DEFAULT_FT]


class _Game:
    def __init__(self, balls=0, strikes=0, pitchnumber=1):
        self.currentballs = balls
        self.currentstrikes = strikes
        self.pitchnumber = pitchnumber
        self.batter = None
        self.last_pitch_type_thrown = None


def _roster():
    screen = pygame.Surface((1280, 720))
    no_sprites = lambda name, frames: []  # noqa: E731
    return [cls(screen, no_sprites) for cls in (Sale, Degrom, Yamamoto, Sasaki, Mcclanahan)]


def _px(spot_ft):
    x, y, _depth = DEFAULT_CAMERA.project(spot_ft[0], 0.0, spot_ft[1])
    return x, y


class _Thrown:
    """Stands in for the simulation: keeps what the pitch method passed."""

    def __call__(self, release_point, name, speed_mph, pfx_x, pfx_z,
                 target_x, target_y, pitch_type):
        self.speed_mph, self.pfx_x, self.pfx_z = speed_mph, pfx_x, pfx_z
        self.target = (target_x, target_y)


# ---- The pitcher ------------------------------------------------------------

def test_every_pitch_of_every_pitcher_is_thrown_at_the_spot():
    random.seed(7)
    for pitcher in _roster():
        for balls, strikes in COUNTS:
            pitcher.set_game_ref(_Game(balls, strikes))
            for name in pitcher.get_pitch_names():
                for spot in SPOTS_FT:
                    thrown = _Thrown()
                    with pitcher.aimed_at(_px(spot)):
                        pitcher.pitch(thrown, name)
                    assert thrown.target == _px(spot), (pitcher.name, name, spot)

                    intent = pitcher.last_intent
                    assert intent.aimed_by == 'player'
                    assert (intent.intent_x, intent.intent_y) == thrown.target
                    assert (intent.exec_x, intent.exec_y) == thrown.target
                    assert intent.intent_kind is None
                    assert intent.miss_kind is None
                    assert intent.command_sigma_in is None
                    assert intent.break_mult == 1.0
                    assert intent.archetype == '' and intent.plan == ''


def test_the_spot_is_where_the_pitch_crosses_the_plate():
    """px -> ft is the conversion PitchSimulation makes; the trajectory is
    solved through the result, whatever the pitch's speed and break."""
    random.seed(11)
    for pitcher in _roster():
        pitcher.set_game_ref(_Game())
        for name in pitcher.get_pitch_names():
            for spot in SPOTS_FT:
                thrown = _Thrown()
                with pitcher.aimed_at(_px(spot)):
                    pitcher.pitch(thrown, name)
                x_ft, z_ft = DEFAULT_CAMERA.screen_to_world_at_plate(*thrown.target)
                assert (x_ft, z_ft) == pytest.approx(spot, abs=1e-9)

                trajectory = PitchTrajectory.from_pitch_params(
                    pitcher.release_pos_3d, thrown.speed_mph, thrown.pfx_x, thrown.pfx_z,
                    x_ft, z_ft)
                x, y, z = trajectory.position_at(trajectory.travel_time)
                assert (x, y, z) == pytest.approx((spot[0], 0.0, spot[1]), abs=1e-9)


def test_the_override_ends_with_the_block():
    pitcher = _roster()[0]
    pitcher.set_game_ref(_Game())
    with pitcher.aimed_at(_px((0.5, 3.0))):
        pitcher.pitch(_Thrown(), 'FF')
    pitcher.pitch(_Thrown(), 'FF')
    assert pitcher.last_intent.aimed_by == 'pitcher'
    assert pitcher.last_intent.intent_kind in INTENTS

    with pytest.raises(RuntimeError), pitcher.aimed_at(_px((0.5, 3.0))):
        raise RuntimeError("the pitch blew up")
    pitcher.pitch(_Thrown(), 'FF')
    assert pitcher.last_intent.aimed_by == 'pitcher'


# ---- Sandbox ------------------------------------------------------------------

@pytest.fixture
def display():
    """`_initiate_pitch` clears queued clicks, which needs the display up,
    as it always is in the game."""
    was_up = pygame.display.get_init()
    pygame.display.init()
    yield
    if not was_up:
        pygame.display.quit()


def _sandbox(pitcher, aim_on, aim_ft=(0.5, 1.8)):
    game = SimpleNamespace(current_pitcher=pitcher, first_pitch_thrown=False,
                           pitch_chosen=None, build_ai_state=lambda: 'state',
                           field_renderer=SimpleNamespace(aim_marker=None),
                           key_binding_manager=SimpleNamespace(is_ui_visible=lambda: True))
    pitcher.set_game_ref(_Game())
    state = object.__new__(SandboxGameplayState)
    state.game = game
    state.active_pitches = {'FF'}
    state.aim_on = aim_on
    state.aim_ft = aim_ft
    state.thrown = _Thrown()
    state._create_pitch_simulation = state.thrown
    return state


def test_a_sandbox_pitch_with_the_aim_on_goes_to_the_spot(display):
    pitcher = _roster()[0]
    state = _sandbox(pitcher, aim_on=True)
    state._initiate_pitch()
    assert state.thrown.target == state._aim_px()
    assert pitcher.last_intent.aimed_by == 'player'
    assert pitcher._aim_override is None, "the override outlived the pitch"
    # Set as the pitch starts, not only by the last frame drawn before it.
    assert state.game.field_renderer.aim_marker == state._aim_px()


def test_a_sandbox_pitch_with_the_aim_off_is_the_pitchers_own(display):
    pitcher = _roster()[0]
    state = _sandbox(pitcher, aim_on=False)
    state.game.field_renderer.aim_marker = (630.0, 485.0)   # left by a frame with it on
    state._initiate_pitch()
    assert pitcher.last_intent.aimed_by == 'pitcher'
    assert state.game.field_renderer.aim_marker is None


# ---- The simulation -------------------------------------------------------------

def _intent(aimed_by):
    return PitchIntent('FF', None, 630.0, 485.0, 630.0, 485.0, None, 1.0, None,
                       '', 'R', 'same', aimed_by=aimed_by)


@pytest.mark.parametrize('intent, aimed', [
    (_intent('player'), True), (_intent('pitcher'), False), (None, False)])
def test_only_a_player_aimed_pitch_skips_the_drift_and_the_ai_update(intent, aimed):
    sim = object.__new__(PitchSimulation)
    sim.pitch_intent = intent
    assert sim._player_aimed() is aimed


# ---- The crosshair -------------------------------------------------------------

def test_the_crosshair_is_drawn_by_the_field_only_when_set():
    """draw_field is what every frame of a pitch draws, so the crosshair is
    there in flight too. It shows even with the zone hidden."""
    surface = pygame.Surface((1280, 720))
    renderer = FieldRenderer(surface)
    renderer.show_bases = False
    assert renderer.strikezonedrawn == FieldRenderer.ZONE_HIDDEN

    renderer.draw_field([None, None, None])
    bare = pygame.surfarray.array3d(surface).copy()

    surface.fill((0, 0, 0))
    renderer.aim_marker = (700.0, 400.0)
    renderer.draw_field([None, None, None])
    marked = pygame.surfarray.array3d(surface)

    differs = (marked != bare).any(axis=2)
    xs, ys = differs.nonzero()
    assert xs.size, "nothing drawn"
    assert abs(xs.mean() - 700) < 1 and abs(ys.mean() - 400) < 1


# ---- The database ---------------------------------------------------------------

def test_a_fresh_database_has_aimed_by(tmp_path):
    db = PitchDB(str(tmp_path / "fresh.db"))
    try:
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(pitches)")}
        assert "aimed_by" in cols
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION >= 15
    finally:
        db.close()


def test_a_v14_database_gains_aimed_by_and_keeps_its_rows(tmp_path):
    path = str(tmp_path / "v14.db")
    conn = sqlite3.connect(path)
    conn.executescript(PitchDB.SCHEMA)
    conn.execute("ALTER TABLE pitches DROP COLUMN aimed_by")
    conn.execute(
        "INSERT INTO pitches (pitch_id, session_id, game_mode, difficulty, "
        "created_at, pitcher_name, pitch_type, outcome) VALUES (?,?,?,?,?,?,?,?)",
        ("p1", "s1", "sandbox", "AMATEUR", "2026-01-01T00:00:00", "Sale", "FF", "ball"))
    conn.execute("PRAGMA user_version = 14")
    conn.commit()
    conn.close()

    db = PitchDB(path)
    try:
        row = db.conn.execute(
            "SELECT outcome, aimed_by FROM pitches WHERE pitch_id='p1'").fetchone()
        assert row[0] == "ball"
        assert row[1] is None, "rows from before v15 must not be guessed at"
    finally:
        db.close()


@pytest.fixture
def service(tmp_path):
    svc = object.__new__(PitchDatabaseService)
    svc.db = PitchDB(str(tmp_path / "aim.db"))
    svc.session_id = "s1"
    svc.current_game_id = "g1"
    svc.current_ab_id = None
    svc._ab_pitch_count = 0
    svc._ab_pitcher = None
    svc._ab_hand = None
    svc._last_pitch = None
    yield svc
    svc.db.close()


def _sim(intent):
    game = SimpleNamespace(
        in_gameday_mode=False, game_mode="sandbox", menu_state="sandbox_gameplay",
        gameday_manager=None, pitch_chosen="FF",
        settings_manager=SimpleNamespace(
            get_difficulty=lambda: SimpleNamespace(value="amateur"),
            get_defense_level=lambda: "league"),
    )
    return SimpleNamespace(
        game=game,
        trajectory=PitchTrajectory.from_pitch_params(
            (1.5, 54.0, 6.0), 95.0, -6.0, 15.0, 0.0, 2.5),
        pitchername="Sale", pitchtype="FF", speed_mph=95.0,
        pfx_x=-6.0, pfx_z=15.0, target_x_ft=0.0, target_z_ft=2.5,
        intent_x_ft=0.0, intent_z_ft=2.5, pitch_intent=intent,
        new_data_entry={"Handedness": "R"},
        swing_type=0, on_time=0, outcome="ball",
        is_strike=False, is_hit=False, runs_scored_on_pitch=0,
    )


def test_a_player_aimed_row_says_so_and_rolls_no_intent(service):
    pitch_id = service.record_pitch(_sim(_intent('player')))
    row = service.db.conn.execute(
        "SELECT aimed_by, intent_kind, miss_kind, command_sigma_in, location_archetype, "
        "intent_x_ft, intent_z_ft FROM pitches WHERE pitch_id = ?", (pitch_id,)).fetchone()
    assert tuple(row) == ("player", None, None, None, None, 0.0, 2.5)


def test_a_pitcher_aimed_row_says_so(service):
    intent = PitchIntent('FF', 'zone', 630.0, 485.0, 632.0, 480.0, 'normal', 1.0, 3.8,
                         '', 'R', 'same')
    pitch_id = service.record_pitch(_sim(intent))
    row = service.db.conn.execute(
        "SELECT aimed_by, intent_kind FROM pitches WHERE pitch_id = ?", (pitch_id,)).fetchone()
    assert tuple(row) == ("pitcher", "zone")
