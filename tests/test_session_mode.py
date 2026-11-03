"""The batter profile is loaded from, and saved to, the session's own bucket.

The mode used to be inferred from `menu_state`, which names the *screen*: it is
'sandbox_menu' while a Sandbox session is being set up and 'visualise' while the
T view is open. So a Sandbox session loaded the Arcade profile, and escaping
from the T view saved the Sandbox profile over the Arcade one. `Game` can't be
constructed headlessly, so the real methods are bound to a stub that carries
only what they touch.
"""

from types import SimpleNamespace

import pytest

from strikefactor.helpers import Runner, ScoreKeeper
from strikefactor.main import Game


def _game(menu_state='sandbox_menu'):
    calls = []
    game = SimpleNamespace(
        game_mode=None, menu_state=menu_state, in_gameday_mode=False,
        current_gamemode=0, inning_ended=False, gameday_manager=None,
        settings_manager=SimpleNamespace(
            get_difficulty=lambda: SimpleNamespace(value='amateur'),
            set_session_difficulty=lambda value: calls.append(('session_difficulty', value))),
        pitcher_manager=SimpleNamespace(set_current_pitcher=lambda name: None,
                                        save_all_ai=lambda: None),
        game_stats=SimpleNamespace(reset_game_stats=lambda: None),
        scoreKeeper=ScoreKeeper(),
        challenge_manager=SimpleNamespace(reset_all=lambda: None,
                                          set_unlimited=lambda flag: None),
        state_manager=SimpleNamespace(
            change_state=lambda name: None,
            states={'sandbox_gameplay': SimpleNamespace(reset_aim=lambda: None)}),
        current_pitcher=SimpleNamespace(clear_fatigue_stats=lambda: None),
        _reset_review=lambda: None,
        _db_start_game=lambda mode, pitcher_name=None: calls.append(('db_start', mode)),
        _db_end_game_if_open=lambda **kw: calls.append(('db_end',)),
    )
    for name in ('_current_bucket_key', '_begin_session', '_enter_sandbox_gameplay',
                 '_teardown_active_session', 'cleanup'):
        setattr(game, name, getattr(Game, name).__get__(game))
    game._load_batter_profile_for_current_bucket = (
        lambda: calls.append(('load', game._current_bucket_key()[0])))
    game._save_batter_profile_for_current_bucket = (
        lambda: calls.append(('save', game._current_bucket_key()[0])))
    return game, calls


def test_a_sandbox_session_loads_the_sandbox_profile():
    game, calls = _game(menu_state='sandbox_menu')
    game._enter_sandbox_gameplay('sale')
    assert ('load', 'sandbox') in calls
    assert game.game_mode == 'sandbox'


@pytest.mark.parametrize("next_mode", ["arcade", "gameday"])
def test_endless_scoring_rules_follow_the_session_across_resets_and_mode_changes(next_mode):
    game, _ = _game()
    game._enter_sandbox_gameplay('sale')
    for mode in ("sandbox", next_mode, "sandbox"):
        game._begin_session(mode)
        game.scoreKeeper.reset()
        game.scoreKeeper.runners = [Runner(3)]
        game.scoreKeeper.update_hit_event("FLYOUT", outs=2)
        assert game.scoreKeeper.get_score() == int(mode == "sandbox")


def test_leaving_from_the_t_view_saves_into_the_session_bucket():
    game, calls = _game()
    game._enter_sandbox_gameplay('sale')
    game.menu_state = 'visualise'          # T view open when Esc is pressed
    calls.clear()
    game._teardown_active_session()
    assert ('save', 'sandbox') in calls
    assert game.game_mode is None


def test_closing_the_window_mid_session_saves_the_profile_and_closes_the_game():
    game, calls = _game()
    game._enter_sandbox_gameplay('sale')
    calls.clear()
    game.cleanup()
    assert calls == [('save', 'sandbox'), ('db_end',)]


def test_closing_the_window_between_sessions_writes_no_profile():
    """Between sessions the in-memory profile belongs to the session just left
    and was saved on the way out; saving it again would file it under
    whichever bucket the default names."""
    game, calls = _game()
    game.cleanup()
    assert calls == [('db_end',)]


# ---- An ABS challenge belongs to the session (and half) it was opened in ----

def test_a_challenge_left_open_does_not_follow_the_player_into_a_new_session():
    """A challenge holds a snapshot of the game at its pitch. Pressing C in a
    new session within the window used to restore the old one over it."""
    game, _ = _game()
    game.pending_challenge = {'snapshot': 'the last session at its last pitch'}
    game._teardown_active_session()
    assert game.pending_challenge is None

    game.pending_challenge = {'snapshot': 'still open somehow'}
    game._begin_session('arcade')
    assert game.pending_challenge is None


def test_a_challenge_left_open_does_not_follow_the_player_into_the_next_half():
    from strikefactor.gameplay.game_states import GameDayTransitionState

    state = object.__new__(GameDayTransitionState)
    state._buttons = SimpleNamespace(clear_focus=lambda: None)
    state.game = SimpleNamespace(
        banner=SimpleNamespace(hide_banner=lambda: None),
        pending_challenge={'snapshot': 'the third out of the half just ended'},
        _resuming_gameday_phase=None,
        autosave_gameday_session=lambda phase: None,
        gameday_manager=SimpleNamespace(
            game_over=False, is_walkoff=False, is_top_inning=False,
            current_inning=3, player_inning_scores=[0, 0], player_score=0,
            opponent_score=0, session_uuid='s',
            should_consider_relief_pitcher=lambda: False),
    )
    state.enter()
    assert state.phase == "SHOW_SCORE"
    assert state.game.pending_challenge is None


def test_leaving_ends_a_session_difficulty_after_saving_under_it():
    """A resumed GameDay game plays at its own difficulty; its profile is filed
    under that one, and the player's own setting is back once they leave."""
    game, calls = _game()
    game._enter_sandbox_gameplay('sale')
    calls.clear()
    game._teardown_active_session()
    assert calls.index(('save', 'sandbox')) < calls.index(('session_difficulty', None))
