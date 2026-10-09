"""The batter profile is loaded from, and saved to, the session's own bucket.

The mode used to be inferred from `menu_state`, which names the *screen*: it is
'sandbox_menu' while a Sandbox session is being set up and 'visualise' while the
T view is open. So a Sandbox session loaded the Arcade profile, and escaping
from the T view saved the Sandbox profile over the Arcade one. `Game` can't be
constructed headlessly, so the real methods are bound to a stub that carries
only what they touch.
"""

from types import SimpleNamespace

from strikefactor.main import Game


def _game(menu_state='sandbox_menu'):
    calls = []
    game = SimpleNamespace(
        game_mode=None, menu_state=menu_state, in_gameday_mode=False,
        current_gamemode=0, inning_ended=False, gameday_manager=None,
        settings_manager=SimpleNamespace(
            get_difficulty=lambda: SimpleNamespace(value='amateur')),
        pitcher_manager=SimpleNamespace(set_current_pitcher=lambda name: None,
                                        save_all_ai=lambda: None),
        game_stats=SimpleNamespace(reset_game_stats=lambda: None),
        scoreKeeper=SimpleNamespace(reset=lambda: None),
        challenge_manager=SimpleNamespace(reset_all=lambda: None,
                                          set_unlimited=lambda flag: None),
        state_manager=SimpleNamespace(change_state=lambda name: None),
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
