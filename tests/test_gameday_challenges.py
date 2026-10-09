"""A resumed GameDay game keeps each side's remaining ABS challenges."""

from types import SimpleNamespace

from strikefactor.data import gameday_sessions
from strikefactor.data.pitch_database import PitchDatabaseService
from strikefactor.gameplay.challenge_manager import ChallengeManager
from strikefactor.gameplay.gameday_manager import GameDayManager
from strikefactor.main import Game


def _resume_stub():
    pitcher = SimpleNamespace(set_fatigue_stats=lambda stats: None)
    transitions = []
    game = SimpleNamespace(
        challenge_manager=ChallengeManager(),
        settings_manager=SimpleNamespace(set_difficulty=lambda value: None),
        pitcher_manager=SimpleNamespace(
            set_current_pitcher=lambda name: None,
            get_current_pitcher=lambda: pitcher),
        game_stats=SimpleNamespace(reset_game_stats=lambda: None),
        scoreKeeper=SimpleNamespace(reset=lambda: None),
        state_manager=SimpleNamespace(change_state=transitions.append),
        ui_manager=SimpleNamespace(update_scouting_panel=lambda pitcher: None),
        _reset_review=lambda: None,
        _begin_session=lambda mode: None,
        _db_resume_game=lambda game_id: None,
    )
    return game, transitions


def test_gameday_autosave_and_resume_keep_both_challenge_balances(
        monkeypatch, tmp_path):
    monkeypatch.setattr(gameday_sessions, 'SESSIONS_FILE',
                        str(tmp_path / 'gameday_sessions.json'))
    monkeypatch.setattr(PitchDatabaseService, 'get_instance',
                        lambda: SimpleNamespace(current_game_id='game-1'))

    manager = GameDayManager(starter_name='sale')
    original = SimpleNamespace(in_gameday_mode=True, gameday_manager=manager,
                               challenge_manager=ChallengeManager())
    original.challenge_manager.consume('home', successful=False)
    original.challenge_manager.consume('home', successful=False)
    original.challenge_manager.consume('away', successful=False)
    original.challenge_manager.consume('away', successful=True)

    Game.autosave_gameday_session(original, 'SHOW_SCORE')
    record = gameday_sessions.get_session(manager.session_uuid)
    assert record['challenges_remaining'] == {'home': 0, 'away': 1}
    assert record['db_game_id'] == 'game-1'

    resumed, transitions = _resume_stub()
    Game.resume_gameday_session(resumed, manager.session_uuid)
    assert resumed.challenge_manager.remaining('home') == 0
    assert resumed.challenge_manager.remaining('away') == 1
    assert not resumed.challenge_manager.can_challenge('home')
    assert resumed._resuming_gameday_phase == 'SHOW_SCORE'
    assert transitions == ['gameday_transition']


def test_challenge_spent_mid_half_is_saved_without_moving_the_resume_boundary(
        monkeypatch, tmp_path):
    monkeypatch.setattr(gameday_sessions, 'SESSIONS_FILE',
                        str(tmp_path / 'gameday_sessions.json'))
    monkeypatch.setattr(PitchDatabaseService, 'get_instance',
                        lambda: SimpleNamespace(current_game_id='game-2'))

    manager = GameDayManager(starter_name='sale')
    game = SimpleNamespace(in_gameday_mode=True, gameday_manager=manager,
                           challenge_manager=ChallengeManager())
    Game.autosave_gameday_session(game, 'SHOW_SCORE')
    boundary_state = gameday_sessions.get_session(manager.session_uuid)['state']
    manager.player_score = 99  # Live play after the last resumable boundary.
    game.pending_challenge = {
        'side': 'home', 'original_call': 'strike', 'truth_strike': True,
        'ball_xy': (630, 480), 'trajectory': [], 'pitchtype': 'FF',
        'speed_mph': 96.0,
        'snapshot': {'game_stats': SimpleNamespace(currentballs=0,
                                                  currentstrikes=0)},
    }
    game._challenge_window_active = lambda: True
    game._count_after_call_label = Game._count_after_call_label
    game.abs_overlay = SimpleNamespace(trigger=lambda **kw: None)
    game._run_abs_overlay_loop = lambda: None
    game._record_abs_challenge = lambda pc, overturned, final: None
    game._persist_gameday_challenges = Game._persist_gameday_challenges.__get__(game)

    Game.request_abs_challenge(game)

    saved = gameday_sessions.get_session(manager.session_uuid)
    assert saved['challenges_remaining'] == {'home': 1, 'away': 2}
    assert saved['state'] == boundary_state
    resumed, _ = _resume_stub()
    Game.resume_gameday_session(resumed, manager.session_uuid)
    assert resumed.challenge_manager.remaining('home') == 1
    assert resumed.gameday_manager.player_score == boundary_state['player_score']


def test_older_gameday_session_without_challenge_counts_still_resumes(
        monkeypatch, tmp_path):
    monkeypatch.setattr(gameday_sessions, 'SESSIONS_FILE',
                        str(tmp_path / 'gameday_sessions.json'))
    manager = GameDayManager(starter_name='sale')
    record = gameday_sessions.build_record(manager, 'SIMULATING')
    record.pop('challenges_remaining')
    gameday_sessions.upsert_session(record)

    resumed, _ = _resume_stub()
    resumed.challenge_manager.consume('home', successful=False)
    Game.resume_gameday_session(resumed, manager.session_uuid)
    assert resumed.challenge_manager.remaining_by_side() == {
        'home': resumed.challenge_manager.per_side,
        'away': resumed.challenge_manager.per_side,
    }


def test_invalid_saved_challenge_counts_cannot_grant_extra_challenges():
    manager = ChallengeManager()
    manager.restore_remaining({'home': 999, 'away': 0, 'other': 999})
    assert manager.remaining('home') == manager.per_side
    assert manager.remaining('away') == 0
