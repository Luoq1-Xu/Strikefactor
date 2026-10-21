"""Dump one PNG per screen, for looking at the UI without playing to it.

    uv run python -m tools.ui_snapshots OUT_DIR [--only NAME ...]

Builds the real `Game` on SDL's dummy drivers, walks it through every screen
by calling the same methods the buttons and keys call, and saves the frame the
main loop would have drawn (`Game._render_frame`). Two runs into two
directories are a before/after of any UI change.

Player data goes to a scratch directory that is deleted on exit: launching the
game writes settings, sessions and pitch rows, and reaching the GameDay final
and history screens means actually finishing a game.

A scene's function leaves the game *on* the screen to capture. Scenes run in
order and build on each other (the history list needs the game the final
screen saved), so `--only` still runs every scene and only filters what is
written.

The run is seeded, so the simulated opponent half-inning is the same every
time and two runs differ only where the UI does. Saved-at times on the resume
and history screens are the wall clock and will differ by a few pixels.
"""

import argparse
import os
import random
import shutil
import sys
import tempfile
import time

SEED = 20261014


def _settle(game, seconds):
    """Run the update half of the main loop for ``seconds`` of real time.

    Real time rather than a frame count because what animates (a scheduled
    banner, the walk-off celebration) paces itself on `pygame.time.get_ticks`.
    """
    end = time.monotonic() + seconds
    while True:
        game.state_manager.update(1 / 60)
        game.banner.update(1 / 60)
        if time.monotonic() >= end:
            return
        time.sleep(0.002)


def _state(game):
    return game.state_manager.get_current_state()


def _end_half_inning(game):
    game.currentouts = 3
    game.check_inning_end()


# ---- Scenes ----------------------------------------------------------------
# (name, setup, seconds to settle). Order matters; see the module docstring.

def _banner(text, letters):
    def setup(game):
        game.banner.hide_banner()
        game.banner.show_banner(text)
        # One letter per update at most, however long the update: the banner
        # types through a stall rather than jumping to the end of the word.
        for _ in range(min(letters, len(text))):
            game.banner.update(0.11)
    return setup


def _hud(mode):
    def setup(game):
        game.banner.hide_banner()
        while game.settings_manager.get_hud_mode() != mode:
            game.toggle_hud_mode()
    return setup


def _gameday_between_innings(game):
    _state(game)._close_game_log()
    _state(game)._start_player_batting()
    _end_half_inning(game)
    game.continue_to_summary()


def _gameday_resume_list(game):
    game.enter_gameday_resume()


def _gameday_final(game):
    state = _state(game)
    state._on_activate(state.items[0])      # resume the saved game
    game.gameday_manager.game_over = True
    game.state_manager.change_state('gameday_transition')


def _gameday_history_list(game):
    _state(game)._return_to_menu()
    game.enter_gameday_mode()
    game.enter_gameday_history()


def _gameday_history_detail(game):
    state = _state(game)
    state._on_activate(state.items[0])


def _sandbox_fixed_aim(game):
    """FIXED AIM on, the crosshair low and away from a right-handed batter."""
    _hud('legacy')(game)
    state = _state(game)
    state.toggle_aim()
    state.aim_ft = (-0.6, 1.7)


def _sandbox_hidden(game):
    game.toggle_ui_visibility()


def _sandbox_shown_again(game):
    game.toggle_ui_visibility()
    game.return_to_mode_select()
    game.enter_gameday_mode()


SCENES = [
    ('mode_select', lambda g: None, 0),
    ('settings', lambda g: g.enter_settings_menu(), 0),
    ('key_bindings', lambda g: g.enter_key_bindings_menu(), 0),
    ('arcade_menu',
     lambda g: (g.exit_key_bindings_menu(), g.exit_settings_menu(),
                g.enter_arcade_mode()), 0),
    ('arcade_gameplay_legacy',
     lambda g: (g.enter_gamemode('Sale', 'sale'), _hud('legacy')(g)), 0),
    ('banner_partial', _banner("STRIKEOUT", 3), 0),
    ('banner_full', _banner("STRIKEOUT", 99), 0),
    ('banner_long',
     _banner("DOUBLE · TO HOME ON THROW · OUT ADVANCING", 99), 0),
    ('arcade_gameplay_broadcast', _hud('broadcast'), 0),
    ('arcade_gameplay_minimal', _hud('minimal'), 0),
    ('track_view', lambda g: (_hud('legacy')(g), g.toggle_track()), 0),
    ('inning_end', lambda g: (g.toggle_track(), _end_half_inning(g)), 0),
    ('summary', lambda g: g.continue_to_summary(), 0),
    ('sandbox_menu',
     lambda g: (g.set_menu_state(0), g.return_to_mode_select(),
                g.enter_sandbox_mode()), 0),
    ('sandbox_gameplay_legacy', lambda g: g._enter_sandbox_gameplay('sale'), 0),
    ('sandbox_gameplay_broadcast', _hud('broadcast'), 0),
    ('sandbox_gameplay_minimal', _hud('minimal'), 0),
    ('sandbox_fixed_aim', _sandbox_fixed_aim, 0),
    ('sandbox_ui_hidden', lambda g: (_hud('legacy')(g), _sandbox_hidden(g)), 0),
    ('gameday_setup', _sandbox_shown_again, 0),
    ('gameday_opponent_half',
     lambda g: g.start_gameday_with_starter('yamamoto'), 0),
    ('gameday_log_plays', lambda g: _state(g)._show_game_log(), 0),
    ('gameday_log_pitching', lambda g: _state(g)._set_log_tab(1), 0),
    ('gameday_between_innings', _gameday_between_innings, 0),
    ('gameday_setup_with_resume',
     lambda g: (g.set_menu_state(0), g.enter_gameday_mode()), 0),
    ('gameday_resume_list', _gameday_resume_list, 0),
    ('gameday_final', _gameday_final, 0),
    ('gameday_history_list', _gameday_history_list, 0),
    ('gameday_history_detail', _gameday_history_detail, 0),
]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('out_dir')
    parser.add_argument('--only', nargs='*', default=None,
                        help="write only these scenes (all still run)")
    args = parser.parse_args(argv)

    known = [name for name, _setup, _settle_s in SCENES]
    unknown = sorted(set(args.only or []) - set(known))
    if unknown:
        parser.error(f"unknown scene(s) {unknown}; choose from {known}")

    # Before anything imports pygame or the game: the driver choice is cached
    # on first init, and the stores resolve their paths from the data dir.
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    data_dir = tempfile.mkdtemp(prefix="strikefactor-snapshots-")
    os.environ["STRIKEFACTOR_DATA_DIR"] = data_dir

    import numpy
    import pygame

    from strikefactor.main import Game

    os.makedirs(args.out_dir, exist_ok=True)
    try:
        game = Game()
        random.seed(SEED)
        numpy.random.seed(SEED)
        for name, setup, settle_s in SCENES:
            setup(game)
            _settle(game, settle_s)
            if args.only is None or name in args.only:
                game._render_frame()
                pygame.image.save(game.screen,
                                  os.path.join(args.out_dir, f"{name}.png"))
                print(name)
    finally:
        pygame.quit()
        shutil.rmtree(data_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
