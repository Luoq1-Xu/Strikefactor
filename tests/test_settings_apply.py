"""Settings that are saved are the settings that are used.

Three settings were written and never read — the STRIKEZONE row, the batter's
side and the display mode — and the umpire sound had two copies that the
in-game button and the Settings row each flipped on their own.
"""

from types import SimpleNamespace

import pytest

from strikefactor.gameplay.batter import Batter
from strikefactor.gameplay.field_renderer import FieldRenderer
from strikefactor.main import Game
from strikefactor.settings_manager import SettingsManager


@pytest.fixture
def settings(tmp_path):
    manager = SettingsManager()
    manager.settings_file = str(tmp_path / "settings.json")
    manager.current_settings = dict(manager.default_settings)
    return manager


def _game(settings):
    import pygame

    screen = pygame.display.get_surface() or pygame.display.set_mode((1280, 720))
    game = SimpleNamespace(settings_manager=settings, batter=Batter(screen),
                           field_renderer=SimpleNamespace(strikezonedrawn=None))
    for name in ('toggle_ump_sound', 'toggle_umpire_sound_setting',
                 'toggle_batter_handedness', 'toggle_strikezone_setting',
                 '_apply_strikezone_setting'):
        setattr(game, name, getattr(Game, name).__get__(game))
    return game


def test_the_sound_button_and_the_settings_row_are_one_switch(settings):
    game = _game(settings)
    assert Game.umpsound.fget(game) is True
    game.toggle_ump_sound()
    assert settings.get_setting("umpire_sound") is False
    assert Game.umpsound.fget(game) is False


def test_switching_the_batter_is_remembered(settings):
    game = _game(settings)
    game.batter.set_handedness("R")
    game.toggle_batter_handedness()
    assert game.batter.get_handedness() == "L"
    assert settings.get_setting("batter_handedness") == "L"


def test_the_strikezone_setting_shows_and_hides_the_zone(settings):
    game = _game(settings)
    game._apply_strikezone_setting()
    assert game.field_renderer.strikezonedrawn == FieldRenderer.ZONE_OUTLINE
    game.toggle_strikezone_setting()
    assert settings.get_setting("show_strikezone") is False
    assert game.field_renderer.strikezonedrawn == FieldRenderer.ZONE_HIDDEN


def test_a_hand_edited_value_falls_back_rather_than_breaking(settings):
    settings.current_settings.update(batter_handedness="S", display_mode="huge")
    assert settings.get_batter_handedness() == "R"
    assert settings.get_display_mode() == "windowed"
