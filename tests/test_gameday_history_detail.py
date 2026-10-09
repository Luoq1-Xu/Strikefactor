"""The GameDay history detail view reads the pitch database once, read-only.

Older history records carry no hit totals, so they are recovered from the pitch
database — and that lookup ran inside the draw, opening SQLite every frame, at
a path built by hand relative to the source tree.
"""

import os
from types import SimpleNamespace

import pygame

from strikefactor import paths
from strikefactor.gameplay.game_states import GameDayHistoryState

_LEGACY_GAME = {  # a record from before hit totals were stored
    'date': '2026-07-01T12:00:00', 'result': 'WIN', 'player_score': 3,
    'opponent_score': 2, 'game_id': 'g1', 'session_id': 's1',
    'player_inning_scores': [0, 3], 'opponent_inning_scores': [2, 0],
}


def _state():
    state = object.__new__(GameDayHistoryState)
    state.game = SimpleNamespace(
        ui_manager=SimpleNamespace(set_visibility_state=lambda name: None))
    state._fonts = None
    state._pbp = None
    state.selected = None
    state._detail_plays = []
    state._detail_hits = (0, 0)
    return state


def test_opening_a_game_queries_once_and_drawing_does_not(monkeypatch):
    queries = []

    def query(sql, params):
        queries.append(sql)
        return []

    monkeypatch.setattr(GameDayHistoryState, "_query_pitch_db", staticmethod(query))
    state = _state()
    state._on_activate(_LEGACY_GAME)
    opened = len(queries)
    assert opened == 2          # the play log and the hit totals, once each

    screen = pygame.Surface((1280, 720))
    for _ in range(5):
        state._render_detail(screen, state.selected)
    assert len(queries) == opened


def test_a_missing_database_is_not_created_by_looking_at_history(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    assert not os.path.exists(paths.db_path())
    assert GameDayHistoryState._query_pitch_db("SELECT 1", ()) == []
    assert not os.path.exists(paths.db_path())
