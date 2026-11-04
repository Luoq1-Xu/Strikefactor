"""Fouls that go somewhere: into the net, into the seats, or into a glove.

A foul used to be a scripted flight — a random distance, a fixed time, and a
clamp that pulled every ball fouled back onto the 40 px of apron the camera
shows below home, where a catcher who had been sent to stop short of it
watched it land. Now a foul flies its own flight, `park.foul_ground_verdict`
says where that flight ends, and a foul fly that comes down where a fielder
can reach it is live: caught, it is an out and the runners tag; dropped or
untouched, it is a strike.
"""

import random
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from strikefactor import outcomes
from strikefactor.data.pitch_database import SCHEMA_VERSION, PitchDB
from strikefactor.gameplay import defense as defense_model
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay import park
from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager
from strikefactor.gameplay.pitch_simulation import PitchSimulation
from strikefactor.helpers import Runner, ScoreKeeper

HANDS = ("R", "L")
# Who is on which side of the field for a ball the batter pulled.
PULL_SIDE = {"R": {"3B", "SS", "LF", "C"}, "L": {"1B", "2B", "RF", "C"}}


def _foul(shape, dep, launch, ev, *, hand="R", bases=(), outs=0, mode="auto", seed=1):
    random.seed(seed)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: hand),
                           currentouts=outs, game_mode="arcade")
    return ha.HitAnimation(game, "FOUL", lambda: None, quality=0.6,
                           batted_ball_type=shape, spray_deg=dep, ev_mph=ev,
                           launch_deg=launch, initial_bases=bases,
                           baserunning_mode=mode)


def _play(anim, step=16, limit_ms=30000):
    """Run the play to its end; every presentation frame along the way."""
    frames = []
    t = 0
    while not anim.finished and t < limit_ms:
        anim.update(t)
        frames.append(anim.presentation_frame())
        t += step
    assert anim.finished, "the foul never finished"
    return frames


@pytest.fixture
def sure_hands(monkeypatch):
    """No misplays, so whether a ball is caught is only whether it was reached."""
    monkeypatch.setattr(defense_model, "roll_misplay", lambda *a, **k: None)


# ---- The park ---------------------------------------------------------------

def test_the_backstop_is_the_bottom_edge_of_the_screen():
    """So a ball that leaves through the bottom of the picture went into the
    net, and every catchable foul — catcher included — stays on screen."""
    _, y = ha._to_screen(0.0, -park.BACKSTOP_FT)
    assert ha.VIEW_SIZE_PX[1] - 1.0 <= y <= ha.VIEW_SIZE_PX[1]


@pytest.mark.parametrize("side", [+1, -1])
def test_foul_ground_is_fair_playable_net_or_seats(side):
    assert park.foul_ground_verdict(0.0, 100.0) == park.FAIR
    assert park.foul_ground_verdict(side * 60.0, 60.0) == park.FAIR   # on the line
    assert park.foul_ground_verdict(0.0, -30.0) == park.PLAYABLE
    assert park.foul_ground_verdict(0.0, -50.0) == park.BACKSTOP
    assert park.foul_ground_verdict(side * 80.0, 50.0) == park.PLAYABLE
    assert park.foul_ground_verdict(side * 130.0, 30.0) == park.STANDS
    # The rail closes in toward the pole.
    assert park.foul_ground_width_ft(300.0) < park.foul_ground_width_ft(50.0)


@pytest.mark.parametrize("side", [+1, -1])
def test_the_drawn_rail_is_the_boundary_a_ball_is_judged_against(side):
    for x, y in park.foul_rail_ft(side)[1:]:
        assert park.foul_ground_verdict(0.98 * x, 0.98 * y) in (park.PLAYABLE, park.FAIR)
        assert park.foul_ground_verdict(1.03 * x, 1.03 * y) in (park.BACKSTOP, park.STANDS)


def test_a_fielder_is_never_put_past_the_rail():
    for x in range(-400, 401, 20):
        for y in range(-80, 400, 20):
            cx, cy = park.clamp_to_foul_ground_ft(float(x), float(y), 2.0)
            assert park.foul_ground_verdict(cx, cy) in (park.FAIR, park.PLAYABLE)


# ---- Dead fouls -------------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
def test_a_liner_fouled_straight_back_goes_into_the_net(hand):
    anim = _foul("LINER", 172.0, 15.0, 78.0, hand=hand)
    assert anim.foul_destination == park.BACKSTOP
    assert anim.foul_result == outcomes.FOUL_BACKSTOP
    assert not anim.live_foul and anim.classified_outcome == "FOUL"
    _play(anim)
    assert anim._elapsed < 2500, "a liner into the net is over in a moment"
    assert anim._ball[1] >= ha.VIEW_SIZE_PX[1] - 6.0, "it ends at the bottom edge"


@pytest.mark.parametrize("hand", HANDS)
def test_a_pop_over_the_net_leaves_through_the_bottom_and_the_play_ends(hand):
    """It comes down 100-200 ft behind the plate. Once it is out of the
    picture there is nothing to show, so the play does not wait for it."""
    anim = _foul("POP_UP", 165.0, 60.0, 75.0, hand=hand)
    assert anim.foul_destination == park.BACKSTOP
    assert anim._foul_net_stop is None, "too high for the net: it goes over"
    _play(anim)
    assert anim._foul_out_of_view
    assert anim._elapsed < anim._anim_ms(anim.flight_time_s)


@pytest.mark.parametrize("hand", HANDS)
def test_a_ball_topped_straight_back_comes_off_the_catcher(hand):
    anim = _foul("GROUNDER", 179.0, -20.0, 66.0, hand=hand)
    assert anim.foul_result == outcomes.FOUL_GROUND
    assert anim._foul_off_catcher
    cx, cy = ha._to_field_ft(anim.fielders["C"].home_pos)
    ex, ey = ha._to_field_ft(anim._hit_end)
    assert abs(ey - cy) < 1.0 and abs(ex - cx) <= ha.CATCHER_GEAR_REACH_FT


@pytest.mark.parametrize("hand", HANDS)
def test_a_fly_into_the_seats_is_never_caught_and_drops_out_of_sight(hand):
    anim = _foul("FLY", -70.0, 35.0, 80.0, hand=hand)
    assert anim.foul_destination == park.STANDS and not anim.live_foul
    frames = _play(anim)
    assert anim.foul_result == outcomes.FOUL_STANDS
    assert not frames[-1].ball_visible, "it landed in the seats"
    for frame in frames:
        for f in frame.fielders:
            assert park.foul_ground_verdict(*ha._to_field_ft(f.pos)) in (
                park.FAIR, park.PLAYABLE), f"{f.role} went into the stands"


@pytest.mark.parametrize("shape,dep,launch,ev", [
    ("LINER", 172.0, 15.0, 78.0), ("POP_UP", 165.0, 60.0, 75.0),
    ("GROUNDER", 150.0, -10.0, 75.0), ("FLY", -70.0, 35.0, 80.0),
])
def test_a_dead_foul_is_the_same_play_every_time(shape, dep, launch, ev):
    """The flight comes off the contact, so a foul's picture does not depend on
    the random state — only the fielders' own jitter does."""
    a = _foul(shape, dep, launch, ev, seed=1)
    b = _foul(shape, dep, launch, ev, seed=99)
    assert a._hit_end == b._hit_end
    assert a.flight_time_s == b.flight_time_s
    assert a.foul_destination == b.foul_destination
    assert a._foul_flight_ms == b._foul_flight_ms


def test_a_dead_foul_can_be_skipped_but_a_live_one_waits():
    dead = _foul("LINER", 172.0, 15.0, 78.0)
    dead.update(0)
    assert dead.can_continue_early
    live = _foul("POP_UP", 55.0, 66.0, 72.0)
    live.update(0)
    assert live.live_foul and not live.can_continue_early


# ---- Live fouls -------------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
def test_a_pop_drifting_past_the_line_is_caught_on_its_side(hand, sure_hands):
    anim = _foul("POP_UP", 55.0, 66.0, 72.0, hand=hand)
    assert anim.live_foul and anim.foul_destination == park.PLAYABLE
    assert anim.classified_outcome is None and anim.foul_result is None
    _play(anim)
    assert anim.foul_result == outcomes.FOUL_CAUGHT
    assert anim.classified_outcome == outcomes.POP_UP
    assert anim.fielder_role in PULL_SIDE[hand] - {"C"}


@pytest.mark.parametrize("hand", HANDS)
def test_the_catcher_takes_a_pop_that_comes_down_short_of_the_net(hand, sure_hands):
    """Out of the crouch with his mask off: the 17 ft a crouched catcher can
    reach on a ball in play is not his range on a pop-up."""
    anim = _foul("POP_UP", 175.0, 85.0, 65.0, hand=hand)
    assert anim.live_foul
    _play(anim)
    assert anim.foul_result == outcomes.FOUL_CAUGHT
    assert anim.fielder_role == "C"


@pytest.mark.parametrize("hand", HANDS)
def test_the_batter_stays_in_the_box_and_runners_hold_while_it_is_up(hand, sure_hands):
    anim = _foul("POP_UP", 55.0, 66.0, 72.0, hand=hand, bases=(1, 2, 3))
    first = None
    for frame in _play(anim):
        if anim._secured_at_ms is not None and frame.time_ms >= anim._secured_at_ms:
            break
        first = first or frame
        assert frame.runner == first.runner, "the batter left the box"
        assert all(r.state == "holding" for r in frame.runners)
        assert frame.runners == first.runners
        assert not frame.send_control, "nobody runs on a foul in the air"


def test_a_foul_nobody_reaches_is_a_dead_strike(sure_hands):
    anim = _foul("LINER", 50.0, 15.0, 70.0, bases=(1, 2))
    assert anim.live_foul
    frames = _play(anim)
    assert anim.foul_result == outcomes.FOUL_LANDED
    assert anim.classified_outcome == "FOUL"
    assert anim.running_result is None
    assert all(r.state == "holding" for f in frames for r in f.runners)


def test_a_dropped_foul_fly_is_a_strike_with_the_error_marked(monkeypatch):
    monkeypatch.setattr(defense_model, "roll_misplay", lambda *a, **k: "MUFF")
    anim = _foul("POP_UP", 55.0, 66.0, 72.0)
    _play(anim)
    assert anim.foul_result == outcomes.FOUL_MUFFED
    assert anim.classified_outcome == "FOUL"
    assert not anim.is_error, "nobody reached base on it"
    assert anim._error_role is not None
    anim._elapsed = anim._foul_dead_at_ms
    assert anim._error_mark_alpha() > 0.0
    assert anim.running_result is None


def test_with_two_out_a_caught_foul_ends_the_inning_without_a_run(sure_hands):
    anim = _foul("POP_UP", 55.0, 66.0, 72.0, bases=(3,), outs=2)
    _play(anim)
    assert anim.foul_result == outcomes.FOUL_CAUGHT
    assert anim._inning_end_s is not None
    result = anim.running_result
    assert result.outcome == outcomes.POP_UP
    keeper = ScoreKeeper()
    keeper.runners = [Runner(3)]
    play = keeper.update_running_play(result, outs=2)
    assert play.runs == 0 and keeper.get_score() == 0


@pytest.mark.parametrize("hand", HANDS)
def test_after_a_foul_out_a_runner_may_tag_and_go_at_his_own_risk(hand, sure_hands):
    """Manual running: Send does nothing while the foul is up — a runner
    cannot advance on a foul — and is live from the catch, when he may tag
    and try for the next base. Here he is thrown out at the plate."""
    anim = _foul("POP_UP", 55.0, 66.0, 72.0, hand=hand, bases=(3,), mode="manual")
    t, refused, sent = 0, None, None
    while not anim.finished and t < 30000:
        anim.update(t)
        t += 16
        if refused is None and t > 500:
            refused = anim.send_runner()
        if anim._foul_caught and sent is None and anim._elapsed > anim._secured_at_ms + 400:
            sent = anim.send_runner()
    assert refused is False
    assert sent is True
    third = next(m for m in anim.running_result.movements if m.runner_id == "3")
    assert third.out_s is not None or third.scored_s is not None
    assert anim.running_result.outs_added == 2


# ---- The pitch ---------------------------------------------------------------

def _sim(strikes=0, outs=0):
    """A `PitchSimulation` with just enough game around it to finalize a
    foul: a scorer, a banner, a count."""
    shown = []
    keeper = ScoreKeeper()
    game = SimpleNamespace(
        hit_outcome_manager=HitOutcomeManager(keeper, None),
        scoreKeeper=keeper, gameday_manager=None, in_gameday_mode=False,
        batter=SimpleNamespace(get_handedness=lambda: "R"),
        field_renderer=SimpleNamespace(record_at_bat=lambda: None,
                                       record_sacrifice_fly=lambda: None,
                                       record_hit=lambda *a, **k: None),
        banner=SimpleNamespace(show_banner=shown.append),
        _display_pitch_results=lambda *a: shown.append(a[0]),
        ball=[630.0, 480.0], fourseamballsize=9,
        last_pitch_information=[[630.0, 480.0, 9, (227, 75, 80), "strike"]],
        strikes=1, pitchnumber=3, currentstrikes=strikes, currentballs=1,
        currentouts=outs, hits=0, homeruns_allowed=0,
    )
    sim = object.__new__(PitchSimulation)
    sim.game = game
    sim.pitchtype, sim.speed_mph = "FOUR-SEAM", 93.0
    sim.new_entry = {}
    sim.is_strike = sim.is_hit = False
    sim.made_contact = "fouled"
    sim.outcome = "foul"
    sim._foul_shape = "POP_UP"
    sim.batted_ball_type = None
    sim.hit_animation = None
    sim._pending_hit_score_before = 0
    return sim, shown


def test_a_caught_foul_is_an_out_and_ends_the_at_bat(sure_hands):
    sim, shown = _sim(strikes=1)
    anim = _foul("POP_UP", 55.0, 66.0, 72.0)
    _play(anim)
    sim._finalize_foul(anim)
    assert sim.game.currentouts == 1
    assert (sim.game.currentstrikes, sim.game.currentballs, sim.game.pitchnumber) == (0, 0, 0)
    assert sim.outcome == outcomes.POP_UP
    assert sim.foul_result == outcomes.FOUL_CAUGHT
    assert not sim.is_strike
    assert sim.batted_ball_type == "POP_UP", "an out was made on it"
    assert outcomes.FOUL_OUT_DISPLAY in shown
    assert sim.game.last_pitch_information[-1][4] == "out"


@pytest.mark.parametrize("strikes,after", [(0, 1), (1, 2), (2, 2)])
def test_a_foul_that_falls_is_a_strike_but_never_strike_three(strikes, after, sure_hands):
    sim, shown = _sim(strikes=strikes)
    anim = _foul("LINER", 50.0, 15.0, 70.0)
    _play(anim)
    sim._finalize_foul(anim)
    assert sim.game.currentstrikes == after
    assert sim.game.currentouts == 0
    assert sim.outcome == "foul" and sim.is_strike and sim.new_entry["foul"]
    assert sim.foul_result == outcomes.FOUL_LANDED
    assert "FOUL BALL" in shown
    assert sim.batted_ball_type is None, "a foul that fell was not put in play"


def test_with_the_foul_animation_off_a_live_foul_is_still_played(sure_hands):
    """The setting hides the play; it does not decide it. The defense still
    has to get to the ball, out of sight, and only the result is shown."""
    sim, shown = _sim()
    anim = _foul("POP_UP", 55.0, 66.0, 72.0)
    sim._resolve_foul_out_of_sight(anim)
    assert anim.finished
    assert sim.game.currentouts == 1
    assert sim.outcome == outcomes.POP_UP
    assert sim.hit_animation is None, "nothing takes over the screen"
    assert outcomes.FOUL_OUT_DISPLAY in shown


# ---- The record ---------------------------------------------------------------

def test_the_foul_result_column_is_added_to_an_older_database():
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "test.db")
        conn = sqlite3.connect(path)
        conn.executescript(PitchDB.SCHEMA)
        conn.execute("ALTER TABLE pitches DROP COLUMN foul_result")
        conn.execute(
            "INSERT INTO pitches (pitch_id, session_id, game_mode, difficulty, "
            "created_at, pitcher_name, pitch_type, outcome) VALUES (?,?,?,?,?,?,?,?)",
            ("p1", "s1", "arcade", "ROOKIE", "2026-01-01T00:00:00", "Sale",
             "FASTBALL", "foul"))
        conn.execute("PRAGMA user_version = 15")
        conn.commit()
        conn.close()
        db = PitchDB(path)
        try:
            assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            row = db.conn.execute(
                "SELECT outcome, foul_result FROM pitches WHERE pitch_id='p1'").fetchone()
            assert tuple(row) == ("foul", None), "never back-filled"
        finally:
            db.close()
