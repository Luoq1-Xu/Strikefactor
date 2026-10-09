"""What gets recorded about a pitch after its row is written.

The pitch's DB row is written 0.7 s after the call, while the 1.8 s ABS
challenge window is still open, and the challenge key is only read once the
pitch loop has returned. So a verdict can only ever arrive *after* the row
exists. It used to be read at write time, off flags nothing could have set yet:
every one of 3,916 recorded rows said "not challenged", and an overturned call
left the umpire's call in `outcome` and a walk or strikeout it had reversed
still closing its at-bat. The verdict now amends the row, and the at-bat with
it, in one transaction.

Rolling the game back for an overturn had the same ordering problem in memory:
the snapshot is taken at the call, so restoring it also undid what the
finished pitch had recorded about itself — its place in the pitch history, the
pitch count, and the AI's state.
"""

import copy
import random
from types import SimpleNamespace

import pytest

from strikefactor.data.pitch_database import PitchDatabaseService, PitchDB
from strikefactor.helpers import Play, ScoreKeeper
from strikefactor.utils.pitch_physics import PitchTrajectory

# ---- A database service on a scratch file ---------------------------------

@pytest.fixture
def service(tmp_path):
    svc = object.__new__(PitchDatabaseService)
    svc.db = PitchDB(str(tmp_path / "abs.db"))
    svc.session_id = "s1"
    svc.current_game_id = "g1"
    svc.current_ab_id = None
    svc._ab_pitch_count = 0
    svc._ab_pitcher = None
    svc._ab_hand = None
    svc._last_pitch = None
    yield svc
    svc.db.close()


def _sim(outcome, *, is_strike=False, runs=0, **extra):
    """The smallest object `record_pitch` can read a row off."""
    game = SimpleNamespace(
        in_gameday_mode=False, menu_state="arcade", gameday_manager=None,
        pitch_chosen="FF",
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
        new_data_entry={"Handedness": "R"},
        swing_type=0, on_time=0, outcome=outcome,
        is_strike=is_strike, is_hit=False, runs_scored_on_pitch=runs,
        **extra,
    )


def _row(svc, pitch_id):
    return svc.db.conn.execute(
        "SELECT outcome, is_strike, runs_scored_on_pitch, abs_challenged, "
        "abs_overturned, ab_id FROM pitches WHERE pitch_id = ?", (pitch_id,)
    ).fetchone()


def _at_bats(svc):
    return [tuple(r) for r in svc.db.conn.execute(
        "SELECT ab_id, final_outcome, pitch_count FROM at_bats ORDER BY created_at")]


# ---- The row takes the verdict ---------------------------------------------

def test_the_row_is_written_unchallenged(service):
    pitch_id = service.record_pitch(_sim("ball"))
    assert pitch_id is not None
    row = _row(service, pitch_id)
    assert (row["abs_challenged"], row["abs_overturned"]) == (0, 0)


# ---- The row's context -------------------------------------------------------

def test_the_row_records_the_hand_the_pitcher_throws_with(service):
    """pitcher_hand comes off the pitcher, not a lookup by `pitchername`.

    The lookup was keyed by roster name ('sale') while the pitch methods pass
    'chrissale', so four of the five pitchers recorded NULL.
    """
    pitch_id = service.record_pitch(_sim("ball", pitcher_hand="L"))
    hand = service.db.conn.execute(
        "SELECT pitcher_hand FROM pitches WHERE pitch_id = ?", (pitch_id,)).fetchone()[0]
    assert hand == "L"


def test_the_row_is_filed_under_the_session_mode_not_the_screen(service):
    """A Sandbox session whose screen state says otherwise is still Sandbox."""
    sim = _sim("ball")
    sim.game.game_mode = "sandbox"
    sim.game.menu_state = "visualise"
    pitch_id = service.record_pitch(sim)
    mode = service.db.conn.execute(
        "SELECT game_mode FROM pitches WHERE pitch_id = ?", (pitch_id,)).fetchone()[0]
    assert mode == "sandbox"


def test_an_upheld_challenge_is_recorded_and_changes_nothing_else(service):
    pitch_id = service.record_pitch(_sim("strike", is_strike=True))
    assert service.amend_abs_challenge(pitch_id, overturned=False)
    row = _row(service, pitch_id)
    assert (row["abs_challenged"], row["abs_overturned"]) == (1, 0)
    assert (row["outcome"], row["is_strike"]) == ("strike", 1)
    assert _at_bats(service) == []


def test_ball_to_strike_rewrites_the_call_and_nothing_else(service):
    pitch_id = service.record_pitch(_sim("ball"))
    ab_id = service.current_ab_id
    assert service.amend_abs_challenge(pitch_id, overturned=True, outcome="strike",
                                       is_strike=True, runs_scored_on_pitch=0)
    row = _row(service, pitch_id)
    assert (row["outcome"], row["is_strike"], row["abs_overturned"]) == ("strike", 1, 1)
    assert _at_bats(service) == []
    assert service.current_ab_id == ab_id, "the at-bat is still open"


def test_ball_four_overturned_to_strike_three_rewrites_the_closed_at_bat(service):
    service.record_pitch(_sim("ball"))
    pitch_id = service.record_pitch(_sim("walk"))
    [(ab_id, final, count)] = _at_bats(service)
    assert (final, count) == ("walk", 2)

    assert service.amend_abs_challenge(pitch_id, overturned=True, outcome="strikeout",
                                       is_strike=True, runs_scored_on_pitch=0)
    assert _at_bats(service) == [(ab_id, "strikeout", 2)]
    assert _row(service, pitch_id)["outcome"] == "strikeout"
    assert service.current_ab_id is None, "the at-bat is still over"


def test_a_walk_taken_away_reopens_the_at_bat_it_closed(service):
    """A bases-loaded ball four overturned: the run comes off, the at-bat is
    not over, and the next pitch belongs to it."""
    service.record_pitch(_sim("ball"))
    pitch_id = service.record_pitch(_sim("walk", runs=1))
    [(ab_id, _, _)] = _at_bats(service)

    assert service.amend_abs_challenge(pitch_id, overturned=True, outcome="strike",
                                       is_strike=True, runs_scored_on_pitch=0)
    row = _row(service, pitch_id)
    assert (row["outcome"], row["runs_scored_on_pitch"]) == ("strike", 0)
    assert _at_bats(service) == []
    assert service.current_ab_id == ab_id

    nxt = service.record_pitch(_sim("strikeout", is_strike=True))
    assert _row(service, nxt)["ab_id"] == ab_id
    assert _at_bats(service) == [(ab_id, "strikeout", 3)]


def test_a_strike_three_given_by_review_closes_the_at_bat_there(service):
    service.record_pitch(_sim("strike", is_strike=True))
    pitch_id = service.record_pitch(_sim("ball"))
    ab_id = service.current_ab_id
    assert _at_bats(service) == []

    assert service.amend_abs_challenge(pitch_id, overturned=True, outcome="strikeout",
                                       is_strike=True, runs_scored_on_pitch=0)
    assert _at_bats(service) == [(ab_id, "strikeout", 2)]
    assert service.current_ab_id is None
    assert _row(service, service.record_pitch(_sim("ball")))["ab_id"] != ab_id


def test_only_the_latest_pitch_can_be_amended(service):
    """Reopening an at-bat is only safe while nothing has been recorded into
    it since — and in play the next pitch closes the window anyway."""
    old = service.record_pitch(_sim("walk"))
    service.record_pitch(_sim("ball"))
    assert not service.amend_abs_challenge(old, overturned=True, outcome="ball",
                                           is_strike=False)
    assert _row(service, old)["abs_challenged"] == 0
    assert _row(service, old)["outcome"] == "walk"


def test_a_verdict_cannot_reach_back_into_a_finished_game(service):
    pitch_id = service.record_pitch(_sim("walk"))
    service.end_game()
    assert not service.amend_abs_challenge(pitch_id, overturned=True,
                                           outcome="ball", is_strike=False)
    assert service.current_ab_id is None


def test_the_row_records_the_base_race(service):
    pitch_id = service.record_pitch(_sim("DOUBLE", extra_base_margin_s=-0.25,
                                         play_margin_s=None))
    row = service.db.conn.execute(
        "SELECT extra_base_margin_s, play_margin_s FROM pitches WHERE pitch_id = ?",
        (pitch_id,)).fetchone()
    assert tuple(row) == (-0.25, None)


# ---- The game hands the verdict to the row ---------------------------------

class _Recorder:
    def __init__(self, pitch_id="pid-1"):
        self.pitch_id = pitch_id
        self.amended = []

    def record_pitch(self, sim):
        return self.pitch_id

    def amend_abs_challenge(self, pitch_id, **kw):
        self.amended.append((pitch_id, kw))
        return True


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(PitchDatabaseService, "get_instance", classmethod(lambda cls: rec))
    return rec


def test_writing_the_row_hands_its_id_to_the_open_challenge(recorder):
    from strikefactor.gameplay.pitch_simulation import PitchSimulation

    sim = object.__new__(PitchSimulation)
    sim.game = SimpleNamespace(pending_challenge={"review_id": (1, 4)})
    assert sim._record_to_database() == "pid-1"
    assert sim.game.pending_challenge["pitch_id"] == "pid-1"

    sim.game = SimpleNamespace(pending_challenge=None)   # a swung-at pitch
    assert sim._record_to_database() == "pid-1"


def test_an_overturn_amends_the_row_with_the_call_and_the_runs(recorder):
    """A bases-loaded ball given by review: ball four, and a run in."""
    from strikefactor.main import Game

    before = ScoreKeeper()
    game = SimpleNamespace(scoreKeeper=ScoreKeeper())
    game.scoreKeeper.score = 1
    pc = {"pitch_id": "pid-1", "truth_strike": False,
          "snapshot": {"scoreKeeper": before}}
    Game._record_abs_challenge(game, pc, True, "walk")
    assert recorder.amended == [("pid-1", dict(overturned=True, outcome="walk",
                                                 is_strike=False,
                                                 runs_scored_on_pitch=1,
                                                 earned_runs_on_pitch=0))]


def test_an_upheld_challenge_still_reaches_the_row(recorder):
    from strikefactor.main import Game

    pc = {"pitch_id": "pid-1", "truth_strike": True,
          "snapshot": {"scoreKeeper": ScoreKeeper()}}
    Game._record_abs_challenge(SimpleNamespace(), pc, False, None)
    [(pitch_id, kw)] = recorder.amended
    assert pitch_id == "pid-1"
    assert kw["overturned"] is False and kw["outcome"] is None


def test_no_row_no_amend(recorder):
    from strikefactor.main import Game

    Game._record_abs_challenge(SimpleNamespace(), {"pitch_id": None}, True, "walk")
    assert recorder.amended == []


# ---- An overturn undoes the call, not the pitch -----------------------------

def test_an_overturn_keeps_what_the_finished_pitch_recorded_about_itself():
    """The snapshot is taken at the call; by the time a challenge can be made
    the pitch has finished and recorded itself. Restoring must roll back what
    the call decided and nothing the pitch did."""
    from strikefactor.main import Game

    at_call = SimpleNamespace(
        strikes=3, balls=5, currentballs=1, currentstrikes=1, currentouts=0,
        currentstrikeouts=0, currentwalks=0, homeruns_allowed=0, hits=0,
        pitchnumber=2, first_pitch_thrown=True, pitch_chosen="SL",
        last_pitch_type_thrown="FF", pitch_history=["FF"],
        current_pitches=4, current_state="state before this pitch")
    after_cleanup = copy.copy(at_call)
    after_cleanup.__dict__.update(
        balls=6, currentballs=2, pitchnumber=3,
        last_pitch_type_thrown="SL", pitch_history=["FF", "SL"],
        current_pitches=5, current_state="state this pitch left")
    game = SimpleNamespace(
        game_stats=after_cleanup, scoreKeeper=ScoreKeeper(), inning_ended=False,
        last_pitch_information=[], menu_state="gameplay",
        state_manager=SimpleNamespace(current_state_name="gameplay"),
        gameday_manager=None,
        field_renderer=SimpleNamespace(total_pitches=41, total_at_bats=9,
                                       total_walks=1, hit_records=[]),
        ui_manager=SimpleNamespace(hide_banner=lambda: None),
        sound_manager=SimpleNamespace(pending_sounds=["ball"]),
    )
    snap = {"game_stats": copy.deepcopy(at_call), "scoreKeeper": ScoreKeeper(),
            "inning_ended": False, "last_pitch_information": [],
            "menu_state": "gameplay", "state_name": "gameplay",
            "field_renderer": {"total_at_bats": 9, "total_walks": 1,
                               "hit_records_len": 0}}

    Game.restore_for_abs(game, snap)
    stats = game.game_stats
    # What the call decided goes back...
    assert (stats.balls, stats.currentballs, stats.pitchnumber) == (5, 1, 2)
    # ...and what the pitch recorded about itself stays.
    assert stats.last_pitch_type_thrown == "SL"
    assert stats.pitch_history == ["FF", "SL"]
    assert stats.current_pitches == 5
    assert stats.current_state == "state this pitch left"
    assert game.field_renderer.total_pitches == 41


# ---- The base race reaches the sim that writes the row --------------------

def test_finalizing_a_ball_that_got_through_carries_its_base_race():
    from strikefactor import outcomes
    from strikefactor.gameplay.hit_animation import HitAnimation
    from strikefactor.gameplay.pitch_simulation import PitchSimulation

    class _Game:
        batter = SimpleNamespace(get_handedness=lambda: "R")
        settings_manager = SimpleNamespace(
            get_difficulty_multipliers=lambda: {"out_probability_modifier": 1.0})

    for seed in range(40):
        random.seed(seed)
        anim = HitAnimation(_Game(), "IN_PLAY", lambda: None, quality=0.9,
                            batted_ball_type="LINER", spray_deg=-25.0 + seed,
                            ev_mph=98.0, launch_deg=16.0)
        t = 0
        while not anim.finished and t < 25000:
            t += 16
            anim.update(t)
        if (anim.play_timing is None
                and anim.classified_outcome in outcomes.HIT_OUTCOMES):
            break
    else:
        pytest.fail("no ball got through the infield in the sample")

    game = SimpleNamespace(
        currentouts=0, hits=0, last_pitch_information=[], ball=(640, 400),
        in_gameday_mode=False,
        hit_outcome_manager=SimpleNamespace(apply_classified_outcome=lambda *a, **k: Play()),
        field_renderer=SimpleNamespace(record_hit=lambda *a, **k: None,
                                       record_at_bat=lambda: None),
        ui_manager=SimpleNamespace(show_banner=lambda text: None),
    )
    sim = object.__new__(PitchSimulation)
    sim.game, sim.hit_animation, sim.new_entry = game, anim, {}
    sim._finalize_batted_ball()
    assert sim.play_margin_s is None
    assert sim.extra_base_margin_s == anim.extra_base_margin_s
    assert isinstance(sim.extra_base_margin_s, float)


# ---- The analysis reads NULL as unknown -------------------------------------

def test_challenges_are_counted_over_the_rows_that_could_record_one():
    import pandas as pd

    from analysis import metrics

    df = pd.DataFrame({
        "ai_umpire_strike": [1, 0, 1, 0],
        "truth_strike":     [0, 0, 1, 1],
        # Two rows from before v11 (unknown), two that could record a verdict.
        "abs_challenged":   [None, None, 1, 0],
        "abs_overturned":   [None, None, 1, 0],
    })
    summary, _ = metrics.umpire_accuracy(SimpleNamespace(pitches=df))
    assert summary["challenge_tracked"] == 2
    assert (summary["challenged"], summary["overturned"]) == (1, 1)


# ---- The banner shows the count the call leaves ------------------------------

@pytest.mark.parametrize("call,balls,strikes,label", [
    ("strike", 1, 2, "K"),
    ("ball", 3, 1, "BB"),
    ("strike", 0, 0, "0-1"),
    ("ball", 2, 2, "3-2"),
])
def test_the_count_label_is_the_call_applied_to_the_count_it_was_made_on(
        call, balls, strikes, label):
    from strikefactor.main import Game

    assert Game._count_after_call_label(call, balls, strikes) == label


def test_an_upheld_strike_three_shows_k_not_the_reset_count():
    """An upheld call used to read the *live* count, which a called strike
    three had already reset — so CALL CONFIRMED said "0-0"."""
    from strikefactor.main import Game

    shown = {}
    game = SimpleNamespace(
        pending_challenge={
            'side': 'home', 'original_call': 'strike', 'truth_strike': True,
            'ball_xy': (630, 480), 'trajectory': [], 'pitchtype': 'FF',
            'speed_mph': 96.0,
            'snapshot': {'game_stats': SimpleNamespace(currentballs=1,
                                                       currentstrikes=2)},
        },
        currentballs=0, currentstrikes=0,          # already reset by the strikeout
        challenge_manager=SimpleNamespace(can_challenge=lambda side: True,
                                          consume=lambda side, successful: None),
        abs_overlay=SimpleNamespace(trigger=lambda **kw: shown.update(kw)),
        _challenge_window_active=lambda: True,
        _run_abs_overlay_loop=lambda: None,
        _record_abs_challenge=lambda pc, overturned, final: None,
    )
    game._count_after_call_label = Game._count_after_call_label
    Game.request_abs_challenge(game)
    assert shown['post_count_label'] == "K"
