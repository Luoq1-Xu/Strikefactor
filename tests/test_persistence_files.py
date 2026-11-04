"""Files the game reads at startup never cost the player their data or the launch."""

import json
import os

import pygame
import pytest

from strikefactor import paths
from strikefactor.gameplay.field_renderer import FieldRenderer
from strikefactor.key_binding_manager import KeyBindingManager
from strikefactor.settings_manager import DifficultyLevel, SettingsManager


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    return tmp_path


# ---- Batting stats ------------------------------------------------------------

@pytest.fixture
def renderer(data_dir):
    renderer = FieldRenderer(pygame.Surface((1280, 720)))
    renderer.data_file = str(data_dir / "batting_stats.json")
    return renderer


@pytest.mark.parametrize("contents", [
    '{"version": "2.0", "buckets": {"arcade|amateur": {"total_hits": "lots"}}}',
    "[]",
    "{not json",
])
def test_an_unreadable_stats_file_is_kept_rather_than_overwritten(renderer, data_dir, contents):
    """The game falls back to fresh stats and saves every 10 pitches. That
    save used to write straight over the only copy of the player's history."""
    with open(renderer.data_file, "w") as f:
        f.write(contents)
    renderer.load_data()
    renderer.save_data()

    kept = [name for name in os.listdir(data_dir) if ".corrupt-" in name]
    assert len(kept) == 1
    assert (data_dir / kept[0]).read_text() == contents


def test_a_good_stats_file_loads_where_it_is(renderer, data_dir):
    with open(renderer.data_file, "w") as f:
        json.dump({"version": "2.0", "buckets": {"arcade|amateur": {"total_hits": 7}}}, f)
    renderer.load_data()
    assert renderer._buckets["arcade|amateur"]["total_hits"] == 7
    assert not [name for name in os.listdir(data_dir) if ".corrupt-" in name]


# ---- Settings and key bindings ---------------------------------------------

@pytest.mark.parametrize("contents", ["[]", "null", "3"])
def test_settings_that_are_not_an_object_fall_back_to_defaults(data_dir, contents):
    (data_dir / paths.SETTINGS_FILE).write_text(contents)
    manager = SettingsManager()
    assert manager.current_settings == manager.default_settings


@pytest.mark.parametrize("contents", ["[]", "null"])
def test_key_bindings_that_are_not_an_object_fall_back_to_defaults(data_dir, contents):
    (data_dir / paths.KEY_BINDINGS_FILE).write_text(contents)
    manager = KeyBindingManager(settings_manager=None)
    assert manager.current_bindings == manager.default_bindings


# ---- A session difficulty -------------------------------------------------------

def test_a_session_difficulty_is_played_but_not_saved(data_dir):
    manager = SettingsManager()
    manager.set_difficulty("hall_of_fame")

    manager.set_session_difficulty("rookie")
    assert manager.get_difficulty() is DifficultyLevel.ROOKIE
    with open(manager.settings_file) as f:
        assert json.load(f)["difficulty"] == "hall_of_fame"

    manager.set_session_difficulty(None)
    assert manager.get_difficulty() is DifficultyLevel.HALL_OF_FAME


def test_choosing_a_difficulty_ends_the_session_one(data_dir):
    manager = SettingsManager()
    manager.set_session_difficulty("rookie")
    manager.set_difficulty("all_star")
    assert manager.get_difficulty() is DifficultyLevel.ALL_STAR
