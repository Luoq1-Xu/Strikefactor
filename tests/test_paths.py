"""Player data lives in one directory outside the package.

Resources (sprites, sounds, seed AIs, pitch tables) ship in the package and
are only read; everything the game writes goes to `paths.data_dir()`. These
pin the resolution, the seed-AI fallback, and the one-time copy of data from
the old in-package layout.
"""

import json
import os
import sqlite3

import pytest

from strikefactor import paths
from strikefactor.config import get_path
from strikefactor.data import legacy_layout


def test_the_environment_variable_names_the_data_directory(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    assert paths.data_dir() == str(tmp_path)
    assert paths.db_path() == os.path.join(str(tmp_path), paths.DB_FILE)
    assert paths.ai_path("sale") == os.path.join(str(tmp_path), "ai", "sale_ai.pkl")


@pytest.mark.parametrize("platform,osname,expected_tail", [
    ("darwin", "posix", os.path.join("Library", "Application Support", "StrikeFactor")),
    ("linux", "posix", os.path.join(".local", "share", "strikefactor")),
])
def test_without_it_the_platform_default_is_used(monkeypatch, platform, osname, expected_tail):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(paths.sys, "platform", platform)
    monkeypatch.setattr(paths.os, "name", osname)
    assert paths.data_dir().endswith(expected_tail)


def test_nothing_the_game_writes_resolves_inside_the_package():
    """The whole point: a session of play must not modify the source tree."""
    from strikefactor.data import gameday_maintenance, gameday_sessions, reset_tracking
    from strikefactor.gameplay.gameday_manager import GameDayManager

    package = os.path.dirname(get_path("config.py"))
    written = [
        paths.db_path(), paths.ai_path("sale"),
        GameDayManager.HISTORY_FILE, gameday_sessions.SESSIONS_FILE,
        reset_tracking.DB_PATH, reset_tracking.ARCHIVE_ROOT,
        gameday_maintenance.DB_PATH, gameday_maintenance.ARCHIVE_ROOT,
    ]
    for path in written:
        assert not os.path.abspath(path).startswith(package + os.sep), path


def test_a_trained_ai_is_preferred_to_the_shipped_seed(monkeypatch, tmp_path):
    from strikefactor.main import PitcherManager

    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    assert PitcherManager._ai_file("sale") == get_path("ai/sale_ai.pkl")
    os.makedirs(tmp_path / "ai")
    (tmp_path / "ai" / "sale_ai.pkl").write_bytes(b"trained")
    assert PitcherManager._ai_file("sale") == str(tmp_path / "ai" / "sale_ai.pkl")


# ---- The one-time copy from the old layout ----------------------------------

def _old_layout(root):
    (root / "data" / "archives" / "20260101_000000").mkdir(parents=True)
    (root / "data" / "archives" / "20260101_000000" / "MANIFEST.json").write_text("{}")
    (root / "settings.json").write_text(json.dumps({"difficulty": "rookie"}))
    (root / "data" / "gameday_history.json").write_text(json.dumps({"games": [1]}))
    conn = sqlite3.connect(root / "data" / "strikefactor.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE pitches (pitch_id TEXT)")
    conn.execute("INSERT INTO pitches VALUES ('p1')")
    conn.commit()           # left in the WAL: a plain file copy would miss it
    return conn


def test_old_layout_data_is_copied_once_and_left_in_place(tmp_path):
    old, new = tmp_path / "package", tmp_path / "data"
    conn = _old_layout(old)
    try:
        steps = legacy_layout.migrate(str(old), str(new))
    finally:
        conn.close()

    assert {kind for kind, _, _ in steps} == {"file", "database", "archive"}
    assert json.loads((new / "settings.json").read_text()) == {"difficulty": "rookie"}
    assert (new / "archives" / "20260101_000000" / "MANIFEST.json").exists()
    copied = sqlite3.connect(new / "strikefactor.db")
    assert copied.execute("SELECT pitch_id FROM pitches").fetchall() == [("p1",)]
    copied.close()
    assert (old / "settings.json").exists()          # copied, not moved

    # Once only: a second run copies nothing, even if old data reappears.
    (new / "settings.json").unlink()
    assert legacy_layout.migrate(str(old), str(new)) == []
    assert not (new / "settings.json").exists()


def test_the_data_directory_always_wins(tmp_path):
    old, new = tmp_path / "package", tmp_path / "data"
    _old_layout(old).close()
    new.mkdir()
    (new / "settings.json").write_text(json.dumps({"difficulty": "hall_of_fame"}))
    legacy_layout.migrate(str(old), str(new))
    assert json.loads((new / "settings.json").read_text()) == {"difficulty": "hall_of_fame"}


def test_a_fresh_install_has_nothing_to_copy(tmp_path):
    new = tmp_path / "data"
    assert legacy_layout.migrate(str(tmp_path / "no-package-data"), str(new)) == []
    assert (new / legacy_layout.MARKER_FILE).exists()


def test_read_only_uris_survive_awkward_paths(tmp_path):
    """The default macOS data directory has a space in it; `?` and `#` would
    end a hand-built URI's path early."""
    folder = tmp_path / "Application Support" / "odd?#name"
    folder.mkdir(parents=True)
    db = folder / paths.DB_FILE
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()
    ro = sqlite3.connect(paths.sqlite_readonly_uri(str(db)), uri=True)
    try:
        assert ro.execute("SELECT COUNT(*) FROM t").fetchone() == (0,)
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("INSERT INTO t VALUES (1)")
    finally:
        ro.close()
