"""Persistent store for in-progress (resumable) GameDay sessions.

Mirrors the gameday_history.json pattern: a single JSON file written
atomically. Unlike history (which holds completed games), this holds games the
player can resume. Each entry pairs denormalized metadata (so the resume list
renders without deserializing every game) with a ``state`` blob produced by
``GameDayManager.to_dict()``.

The list is maintained most-recent-first and capped to ``MAX_SESSIONS``.
"""

import json
import os
from datetime import datetime

from strikefactor.utils.io import atomic_write_json

SESSIONS_FILE = os.path.join(os.path.dirname(__file__), 'gameday_sessions.json')

# Cap the number of resumable sessions kept on disk. Once exceeded, the
# oldest-saved entries drop off the tail (the list is most-recent-first).
MAX_SESSIONS = 10


def _empty() -> dict:
    return {'version': '1.0', 'sessions': [], 'last_updated': None}


def _load() -> dict:
    """Load the sessions file, tolerating a missing or corrupt file."""
    try:
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE, 'r') as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get('sessions'), list):
                return data
    except (json.JSONDecodeError, OSError) as e:
        if isinstance(e, json.JSONDecodeError):
            print(f"Warning: GameDay sessions file {SESSIONS_FILE} is corrupt "
                  f"({e}); starting from an empty record.")
    return _empty()


def load_sessions() -> list:
    """Return resumable sessions, most-recent-first."""
    return list(_load().get('sessions', []))


def get_session(session_id: str):
    """Return a single session record by id, or None."""
    for s in _load().get('sessions', []):
        if s.get('session_id') == session_id:
            return s
    return None


def build_record(manager, phase: str, db_game_id: str = None) -> dict:
    """Build a session record from a live GameDayManager + transition phase.

    Metadata fields are denormalized copies of manager state so the resume list
    can render without rebuilding a manager; ``state`` is the full snapshot used
    on resume.

    ``db_game_id`` carries the open ``games.game_id`` so a resume can reattach
    its pitches to the same row. Without it a resumed game logs under a second
    game_id, splitting one logical game in two — the first half then has no
    final score, so its runs go unattributable in the pitching line.
    """
    return {
        'session_id': manager.session_uuid,
        'saved_at': datetime.now().isoformat(),
        'opponent_starter': manager.opponent_pitcher_preset.get('starter'),
        'difficulty': manager.difficulty,
        'inning': manager.current_inning,
        'half': 'Top' if manager.is_top_inning else 'Bot',
        'player_score': manager.player_score,
        'opponent_score': manager.opponent_score,
        'phase': phase,
        'db_game_id': db_game_id,
        'state': manager.to_dict(),
    }


def upsert_session(record: dict) -> None:
    """Insert or update a session (keyed by ``session_id``), most-recent-first.

    Any existing entry for the same game is replaced and the record is moved to
    the front so the list stays ordered by most-recent save. The list is then
    capped to MAX_SESSIONS (oldest dropped).
    """
    data = _load()
    sid = record.get('session_id')
    sessions = [s for s in data.get('sessions', []) if s.get('session_id') != sid]
    sessions.insert(0, record)
    data['sessions'] = sessions[:MAX_SESSIONS]
    data['last_updated'] = datetime.now().isoformat()
    atomic_write_json(SESSIONS_FILE, data)


def remove_session(session_id: str) -> None:
    """Remove a session by id. No-op if absent (avoids a needless rewrite)."""
    data = _load()
    before = data.get('sessions', [])
    sessions = [s for s in before if s.get('session_id') != session_id]
    if len(sessions) == len(before):
        return
    data['sessions'] = sessions
    data['last_updated'] = datetime.now().isoformat()
    atomic_write_json(SESSIONS_FILE, data)
