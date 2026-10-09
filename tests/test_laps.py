"""Lap numbers keep counting once the history is trimmed.

The history keeps the newest 100 laps, and the number used to be the list's
length plus one — so from the 101st lap on, every lap was "Lap 101".
"""

import json

import pygame

from strikefactor.gameplay.field_renderer import FieldRenderer


def test_lap_numbers_keep_counting_past_the_history_cap(tmp_path):
    screen = pygame.display.get_surface() or pygame.display.set_mode((1280, 720))
    renderer = FieldRenderer(screen)
    renderer.data_file = str(tmp_path / "batting_stats.json")
    renderer.lap_history_file = str(tmp_path / "lap_history.json")
    (tmp_path / "lap_history.json").write_text(json.dumps({
        "version": "1.1",
        "laps": [{"lap_number": n} for n in range(1, 101)],
    }))

    assert renderer.create_lap()["lap_number"] == 101
    assert renderer.create_lap()["lap_number"] == 102
    laps = renderer.get_lap_history()
    assert len(laps) == 100
    assert laps[-1]["lap_number"] == 102
