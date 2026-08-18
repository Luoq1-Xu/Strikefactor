"""Archiving and resetting all recorded play.

The module deletes a career record and 22k pitches in one call, so the
properties worth pinning are the ones that make that safe: the snapshot is
taken before anything is cleared, it is complete, a restore puts every store
back, and the reset leaves a database that is still current rather than one
stripped back to nothing.
"""

import json
import os
import sqlite3

import pytest

from strikefactor.data import reset_tracking as rt


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A populated set of tracking stores, rooted in a temp dir."""
    monkeypatch.setattr(rt, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(rt, 'ARCHIVE_ROOT', str(tmp_path / 'archives'))
    monkeypatch.setattr(rt, 'DB_PATH', str(tmp_path / 'strikefactor.db'))

    conn = sqlite3.connect(str(tmp_path / 'strikefactor.db'))
    conn.executescript("""
        CREATE TABLE pitches (pitch_id TEXT PRIMARY KEY, game_mode TEXT);
        CREATE TABLE pitch_trajectories (pitch_id TEXT, sample_idx INTEGER);
        CREATE TABLE at_bats (ab_id TEXT PRIMARY KEY);
        CREATE TABLE games (game_id TEXT PRIMARY KEY);
        CREATE TABLE batter_profiles (key TEXT PRIMARY KEY);
        PRAGMA user_version = 8;
    """)
    for i in range(30):
        mode = ('arcade', 'sandbox', 'gameday')[i % 3]
        conn.execute('INSERT INTO pitches VALUES (?,?)', (f'p{i}', mode))
        conn.execute('INSERT INTO pitch_trajectories VALUES (?,?)', (f'p{i}', 0))
    conn.execute('INSERT INTO at_bats VALUES ("ab1")')
    conn.execute('INSERT INTO games VALUES ("g1")')
    conn.execute('INSERT INTO batter_profiles VALUES ("arcade|amateur")')
    conn.commit()
    conn.close()

    payloads = {
        'gameday_history.json': {'version': 3, 'games': [{'id': 1}, {'id': 2}]},
        'gameday_sessions.json': {'version': 1, 'sessions': []},
        'lap_history.json': {'version': 2, 'laps': [{'lap': 1}]},
        'batting_stats.json': {'version': 4, 'buckets': {'arcade|amateur': {'x': 1}}},
    }
    for name, payload in payloads.items():
        (tmp_path / name).write_text(json.dumps(payload))
    return tmp_path


def _db_counts(path):
    conn = sqlite3.connect(str(path))
    try:
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                for t in rt.DB_TABLES}
    finally:
        conn.close()


# ---- Inventory --------------------------------------------------------------

def test_inventory_reports_every_store(store):
    counts = rt.inventory()
    assert counts['pitches'] == 30
    assert counts['pitch_trajectories'] == 30
    assert counts['batter_profiles'] == 1
    assert counts['gameday_history.json'] == 2
    assert counts['batting_stats.json'] == 1
    assert counts['_by_mode'] == {'arcade': 10, 'sandbox': 10, 'gameday': 10}


def test_a_dry_run_changes_nothing(store):
    before = _db_counts(store / 'strikefactor.db')
    rt.inventory()
    assert _db_counts(store / 'strikefactor.db') == before
    assert rt.list_archives() == []


# ---- Archive ----------------------------------------------------------------

def test_the_archive_is_complete(store):
    archive_dir = rt.archive(reason='test')
    names = set(os.listdir(archive_dir))
    assert rt.DB_ARCHIVE_NAME in names
    assert rt.MANIFEST_NAME in names
    assert set(rt.JSON_STORES) <= names


def test_the_archived_database_is_a_standalone_queryable_copy(store):
    """Not an extracted slice — the whole file, so it opens with no
    reassembly. A WAL checkpoint runs first; without it a plain file copy can
    miss committed rows still sitting in the sidecar."""
    archive_dir = rt.archive()
    assert _db_counts(os.path.join(archive_dir, rt.DB_ARCHIVE_NAME))['pitches'] == 30


def test_the_manifest_records_what_was_there(store):
    archive_dir = rt.archive(reason='collision_angled sign fix')
    manifest = json.loads(
        (open(os.path.join(archive_dir, rt.MANIFEST_NAME))).read())
    assert manifest['reason'] == 'collision_angled sign fix'
    assert manifest['counts']['pitches'] == 30
    assert set(manifest['json_files']) == set(rt.JSON_STORES)


def test_the_snapshot_is_taken_before_anything_is_cleared(store):
    """The ordering the whole module rests on."""
    archive_dir, _ = rt.archive_and_reset()
    assert _db_counts(os.path.join(archive_dir, rt.DB_ARCHIVE_NAME))['pitches'] == 30
    assert _db_counts(store / 'strikefactor.db')['pitches'] == 0


# ---- Reset ------------------------------------------------------------------

def test_reset_empties_every_table(store):
    rt.reset()
    assert all(n == 0 for n in _db_counts(store / 'strikefactor.db').values())


def test_reset_deletes_rows_not_tables(store):
    """The next launch has to open a database that is current, not one that
    needs migrating from scratch."""
    rt.reset()
    conn = sqlite3.connect(str(store / 'strikefactor.db'))
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert set(rt.DB_TABLES) <= tables
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 8
    finally:
        conn.close()


def test_reset_keeps_each_json_files_shape_and_version(store):
    """Emptied, not deleted, so `version` survives and the next load reads a
    current file rather than recreating a default one a schema behind."""
    rt.reset()
    payload = json.loads((store / 'gameday_history.json').read_text())
    assert payload['version'] == 3
    assert payload['games'] == []
    assert 'last_updated' in payload
    buckets = json.loads((store / 'batting_stats.json').read_text())
    assert buckets['version'] == 4
    assert buckets['buckets'] == {}, "a dict store must stay a dict"


def test_reset_reports_what_it_cleared(store):
    cleared = rt.reset()
    assert cleared['pitches'] == 30
    assert cleared['gameday_history.json'] == 2


# ---- Restore ----------------------------------------------------------------

def test_restore_puts_everything_back(store):
    archive_dir, _ = rt.archive_and_reset()
    rt.restore(os.path.basename(archive_dir))
    assert _db_counts(store / 'strikefactor.db')['pitches'] == 30
    assert json.loads((store / 'gameday_history.json').read_text())['games']
    assert json.loads((store / 'batting_stats.json').read_text())['buckets']


def test_restore_snapshots_the_current_state_first(store):
    """Restoring is itself destructive. Finding that out afterwards is the
    situation this module exists to prevent."""
    first, _ = rt.archive_and_reset()
    before = len(rt.list_archives())
    rt.restore(os.path.basename(first))
    assert len(rt.list_archives()) == before + 1


def test_restoring_a_missing_archive_raises(store):
    with pytest.raises(FileNotFoundError):
        rt.restore('20000101_000000')


def test_two_snapshots_in_the_same_second_do_not_collide(store):
    """Names are second-resolution timestamps. Before this, a second snapshot
    landed in the first one's directory — and because `restore` snapshots the
    live state first, restoring within a second of archiving overwrote the
    snapshot being restored *from* with the emptied stores, then read that
    back. Losing data on the recovery path is the one failure this module
    cannot have."""
    first = rt.archive()
    second = rt.archive()
    assert first != second
    assert len(rt.list_archives()) == 2
    assert _db_counts(os.path.join(first, rt.DB_ARCHIVE_NAME))['pitches'] == 30
