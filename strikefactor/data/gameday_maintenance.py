"""Utilities for archiving, resetting, and restoring GameDay persistence.

GameDay progress lives in three places: ``gameday_history.json`` (completed
games / career record), ``gameday_sessions.json`` (resumable in-progress
games), and the ``game_mode = 'gameday'`` rows of ``strikefactor.db`` (the
per-pitch log the offline analysis reads). This module snapshots all three into
a timestamped directory under ``gameday_archives/`` before clearing them, and
can put a snapshot back.

Archiving the JSON without the database is what lets the two drift: history can
say one game while the analysis still aggregates every pitch ever thrown, which
is how a five-game career line appears for a career the history says never
happened. Keep the two halves together.

Run from the repository root as a module::

    python -m strikefactor.data.gameday_maintenance                  # archive + wipe
    python -m strikefactor.data.gameday_maintenance --keep-latest    # wipe all but newest
    python -m strikefactor.data.gameday_maintenance --list           # list snapshots
    python -m strikefactor.data.gameday_maintenance --restore 20260725_210000
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime

from strikefactor.data import gameday_sessions
from strikefactor.gameplay.gameday_manager import GameDayManager
from strikefactor.utils.io import atomic_write_json

ARCHIVE_ROOT = os.path.join(os.path.dirname(__file__), 'gameday_archives')
DB_PATH = os.path.join(os.path.dirname(__file__), 'strikefactor.db')

# Name of the extracted GameDay slice inside an archive directory. It is a
# standalone SQLite file with the same table shapes as the live DB, so it can
# be queried directly or copied back row-for-row.
DB_SLICE_NAME = 'gameday_pitches.sqlite3'

# Archived filename -> live path. Keyed by basename so a snapshot directory is
# self-describing and restore doesn't depend on argument order.
_ARCHIVED_FILES = {
    'gameday_history.json': GameDayManager.HISTORY_FILE,
    'gameday_sessions.json': gameday_sessions.SESSIONS_FILE,
}


def _timestamp() -> str:
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def _connect(path: str = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _count(path: str, key: str) -> int:
    """Best-effort record count, for the manifest and console output."""
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        return len(data.get(key, []))
    except (OSError, json.JSONDecodeError, AttributeError):
        return 0


def latest_game_id(conn: sqlite3.Connection = None) -> str:
    """game_id of the most recently started GameDay game, or None."""
    own = conn is None
    conn = conn or _connect()
    try:
        row = conn.execute(
            "SELECT game_id FROM games WHERE game_mode = 'gameday' "
            "ORDER BY started_at DESC LIMIT 1").fetchone()
        return row['game_id'] if row else None
    finally:
        if own:
            conn.close()


def merge_game_fragments(target_game_id: str, source_game_ids) -> int:
    """Re-point another game_id's pitches and at-bats at ``target_game_id``.

    Repairs games split by the pre-fix resume path, which opened a second
    ``games`` row on resume. The source rows are deleted once their pitches
    move, so the merged game reads as the single game it always was. Returns
    the number of pitches moved.
    """
    source_game_ids = [g for g in source_game_ids if g and g != target_game_id]
    if not source_game_ids:
        return 0

    conn = _connect()
    try:
        if conn.execute("SELECT 1 FROM games WHERE game_id = ?",
                        (target_game_id,)).fetchone() is None:
            raise ValueError(f'No such game_id to merge into: {target_game_id}')

        placeholders = ','.join('?' * len(source_game_ids))
        moved = conn.execute(
            f"SELECT COUNT(*) FROM pitches WHERE game_id IN ({placeholders})",
            source_game_ids).fetchone()[0]
        with conn:
            conn.execute(
                f"UPDATE pitches SET game_id = ? WHERE game_id IN ({placeholders})",
                [target_game_id] + source_game_ids)
            conn.execute(
                f"UPDATE at_bats SET game_id = ? WHERE game_id IN ({placeholders})",
                [target_game_id] + source_game_ids)
            conn.execute(f"DELETE FROM games WHERE game_id IN ({placeholders})",
                         source_game_ids)
        return int(moved)
    finally:
        conn.close()


def export_gameday_db_slice(archive_dir: str) -> dict:
    """Copy every GameDay row into a standalone SQLite file in ``archive_dir``.

    Pulls the four related tables: games, the pitches belonging to them, those
    pitches' trajectory samples, and the at-bats. Returns per-table row counts.
    """
    out_path = os.path.join(archive_dir, DB_SLICE_NAME)
    if os.path.exists(out_path):
        os.remove(out_path)

    src = _connect()
    try:
        gd_games = [r['game_id'] for r in src.execute(
            "SELECT game_id FROM games WHERE game_mode = 'gameday'")]

        dst = sqlite3.connect(out_path)
        try:
            # Mirror the live table definitions so the slice stays queryable
            # with the same SQL, without importing the schema constant.
            for tbl in ('games', 'pitches', 'pitch_trajectories', 'at_bats'):
                ddl = src.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (tbl,)).fetchone()
                if ddl and ddl['sql']:
                    dst.execute(ddl['sql'])

            counts = {}
            queries = {
                'games': ("SELECT * FROM games WHERE game_mode = 'gameday'", ()),
                'pitches': ("SELECT * FROM pitches WHERE game_mode = 'gameday'", ()),
                'pitch_trajectories': (
                    "SELECT t.* FROM pitch_trajectories t JOIN pitches p "
                    "ON p.pitch_id = t.pitch_id WHERE p.game_mode = 'gameday'", ()),
                'at_bats': (
                    "SELECT * FROM at_bats WHERE game_id IN (%s)"
                    % (','.join('?' * len(gd_games)) or 'NULL'), tuple(gd_games)),
            }
            for tbl, (sql, params) in queries.items():
                rows = src.execute(sql, params).fetchall()
                if rows:
                    cols = rows[0].keys()
                    dst.executemany(
                        f"INSERT INTO {tbl} ({','.join(cols)}) VALUES "
                        f"({','.join('?' * len(cols))})",
                        [tuple(r) for r in rows])
                counts[tbl] = len(rows)
            dst.commit()
            return counts
        finally:
            dst.close()
    finally:
        src.close()


def purge_gameday_db_rows(keep_game_ids=()) -> dict:
    """Delete GameDay rows from the live DB, optionally keeping some games.

    Arcade and Sandbox rows are never touched. Returns per-table delete counts.
    Run ``export_gameday_db_slice`` first — this is not reversible in place.
    """
    keep = [g for g in keep_game_ids if g]
    conn = _connect()
    try:
        keep_clause = ''
        params: list = []
        if keep:
            # `NULL NOT IN (...)` is NULL, not true, so a bare NOT IN silently
            # spares every pre-v2 row that has no game_id — the exact rows most
            # in need of clearing. Spell the NULL case out.
            keep_clause = (f" AND (game_id IS NULL OR game_id NOT IN "
                           f"({','.join('?' * len(keep))}))")
            params = keep

        doomed_rows = conn.execute(
            f"SELECT pitch_id, ab_id FROM pitches WHERE game_mode = 'gameday'"
            f"{keep_clause}", params).fetchall()
        doomed = [r['pitch_id'] for r in doomed_rows]
        # at_bats carries no game_mode, and its game_id is NULL on pre-v2 rows,
        # so the only reliable way to find the GameDay at-bats is through the
        # pitches that belong to them — gathered before those pitches are gone.
        doomed_abs = {r['ab_id'] for r in doomed_rows if r['ab_id']}

        def _delete_in_batches(sql, keys):
            removed = 0
            keys = list(keys)
            for i in range(0, len(keys), 500):
                batch = keys[i:i + 500]
                removed += conn.execute(
                    sql % ','.join('?' * len(batch)), batch).rowcount
            return removed

        counts = {}
        with conn:
            # Trajectories first — they key off the pitches about to vanish.
            counts['pitch_trajectories'] = _delete_in_batches(
                "DELETE FROM pitch_trajectories WHERE pitch_id IN (%s)", doomed)
            counts['pitches'] = conn.execute(
                f"DELETE FROM pitches WHERE game_mode = 'gameday'{keep_clause}",
                params).rowcount
            counts['at_bats'] = _delete_in_batches(
                "DELETE FROM at_bats WHERE ab_id IN (%s)", doomed_abs)
            counts['games'] = conn.execute(
                f"DELETE FROM games WHERE game_mode = 'gameday'{keep_clause}",
                params).rowcount
        return counts
    finally:
        conn.close()


def list_archives() -> list:
    """Return archive directory names, newest-first (names are timestamps)."""
    if not os.path.isdir(ARCHIVE_ROOT):
        return []
    names = [n for n in os.listdir(ARCHIVE_ROOT)
             if os.path.isdir(os.path.join(ARCHIVE_ROOT, n))]
    return sorted(names, reverse=True)


def archive_gameday_data() -> str:
    """Snapshot the live GameDay JSON stores. Returns the archive directory.

    A missing live file is noted in the manifest rather than aborting the
    snapshot — a fresh install legitimately has no sessions file yet.
    """
    archive_dir = os.path.join(ARCHIVE_ROOT, _timestamp())
    os.makedirs(archive_dir, exist_ok=True)

    manifest = {
        'created_at': datetime.now().isoformat(),
        'sources': {},
        'counts': {},
    }

    for name, live_path in _ARCHIVED_FILES.items():
        manifest['sources'][name] = os.path.abspath(live_path)
        if os.path.exists(live_path):
            shutil.copy2(live_path, os.path.join(archive_dir, name))
        else:
            manifest['sources'][name] += ' (missing at archive time)'

    manifest['counts']['games'] = _count(
        os.path.join(archive_dir, 'gameday_history.json'), 'games')
    manifest['counts']['sessions'] = _count(
        os.path.join(archive_dir, 'gameday_sessions.json'), 'sessions')

    manifest['sources'][DB_SLICE_NAME] = os.path.abspath(DB_PATH)
    if os.path.exists(DB_PATH):
        manifest['counts']['db'] = export_gameday_db_slice(archive_dir)
    else:
        manifest['sources'][DB_SLICE_NAME] += ' (missing at archive time)'

    with open(os.path.join(archive_dir, 'manifest.json'), 'w') as f:
        json.dump(manifest, f, indent=2)

    return archive_dir


def reset_gameday_data(keep_game_ids=()) -> dict:
    """Clear the live GameDay stores back to their empty shape.

    The empty shapes come from the modules that own each file so a schema
    change there can't drift away from what a reset writes. GameDay rows are
    dropped from the pitch DB in the same pass, keeping the two in step;
    ``keep_game_ids`` survives both the history file and the DB.
    """
    keep = {g for g in keep_game_ids if g}

    history = GameDayManager._empty_history()
    if keep:
        try:
            with open(GameDayManager.HISTORY_FILE, 'r') as f:
                live = json.load(f)
            history['games'] = [g for g in live.get('games', [])
                                if g.get('game_id') in keep]
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    atomic_write_json(GameDayManager.HISTORY_FILE, history)

    # Sessions are always cleared: a resumable session pointing at a purged
    # game would rebuild into a game whose pitches no longer exist.
    atomic_write_json(gameday_sessions.SESSIONS_FILE, gameday_sessions._empty())

    return purge_gameday_db_rows(keep) if os.path.exists(DB_PATH) else {}


def archive_and_reset_gameday_data(keep_game_ids=()) -> tuple:
    """Archive current GameDay data, then clear the live stores.

    Returns ``(archive_dir, db_delete_counts)``.
    """
    archive_dir = archive_gameday_data()
    deleted = reset_gameday_data(keep_game_ids)
    return archive_dir, deleted


def restore_gameday_data(archive_name: str) -> str:
    """Restore a snapshot over the live stores.

    The current live files are snapshotted first, so a restore is itself
    reversible. Returns the directory that was restored from.
    """
    archive_dir = os.path.join(ARCHIVE_ROOT, archive_name)
    if not os.path.isdir(archive_dir):
        raise FileNotFoundError(f'No such GameDay archive: {archive_dir}')

    present = [n for n in _ARCHIVED_FILES
               if os.path.exists(os.path.join(archive_dir, n))]
    slice_path = os.path.join(archive_dir, DB_SLICE_NAME)
    has_slice = os.path.exists(slice_path)
    if not present and not has_slice:
        raise FileNotFoundError(
            f'Archive {archive_name} contains none of '
            f'{sorted(list(_ARCHIVED_FILES) + [DB_SLICE_NAME])}')

    safety_dir = archive_gameday_data()
    print(f'Pre-restore snapshot of live data: {safety_dir}')

    for name in present:
        with open(os.path.join(archive_dir, name), 'r') as f:
            payload = json.load(f)
        atomic_write_json(_ARCHIVED_FILES[name], payload)

    if has_slice:
        _restore_db_slice(slice_path)

    return archive_dir


def _restore_db_slice(slice_path: str) -> dict:
    """Replace the live GameDay pitch rows with those from an archived slice.

    Existing GameDay rows are dropped first so a restore reproduces the
    snapshot exactly rather than unioning with whatever is live. Archives
    predating the DB slice leave the pitch DB untouched (handled by the caller).
    """
    purge_gameday_db_rows()

    dst = _connect()
    try:
        dst.execute("ATTACH DATABASE ? AS snap", (slice_path,))
        snap_tables = {r['name'] for r in dst.execute(
            "SELECT name FROM snap.sqlite_master WHERE type='table'")}
        counts = {}
        try:
            with dst:
                for tbl in ('games', 'pitches', 'pitch_trajectories', 'at_bats'):
                    if tbl not in snap_tables:
                        continue
                    cols = [r[1] for r in dst.execute(f"PRAGMA snap.table_info({tbl})")]
                    live = {r[1] for r in dst.execute(f"PRAGMA table_info({tbl})")}
                    # Only carry columns the live schema still has, so a slice
                    # taken before a migration still restores.
                    cols = [c for c in cols if c in live]
                    joined = ','.join(cols)
                    cur = dst.execute(
                        f"INSERT OR REPLACE INTO {tbl} ({joined}) "
                        f"SELECT {joined} FROM snap.{tbl}")
                    counts[tbl] = cur.rowcount
        finally:
            dst.execute("DETACH DATABASE snap")
        return counts
    finally:
        dst.close()


def _print_archive_list() -> None:
    names = list_archives()
    if not names:
        print('No GameDay archives yet.')
        return
    for name in names:
        counts = {}
        try:
            with open(os.path.join(ARCHIVE_ROOT, name, 'manifest.json')) as f:
                counts = json.load(f).get('counts', {})
        except (OSError, json.JSONDecodeError):
            pass
        games = counts.get('games', _count(
            os.path.join(ARCHIVE_ROOT, name, 'gameday_history.json'), 'games'))
        sessions = counts.get('sessions', _count(
            os.path.join(ARCHIVE_ROOT, name, 'gameday_sessions.json'), 'sessions'))
        pitches = (counts.get('db') or {}).get('pitches')
        db_note = f', {pitches} pitches' if pitches is not None else ', no db slice'
        print(f'{name}  {games} games, {sessions} sessions{db_note}')


def _main() -> None:
    parser = argparse.ArgumentParser(
        description='Archive, reset, or restore GameDay progress files.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--list', action='store_true',
                       help='list available archives and exit')
    group.add_argument('--restore', metavar='ARCHIVE',
                       help='restore the named archive over the live data')
    group.add_argument('--archive-only', action='store_true',
                       help='snapshot without clearing the live data')
    parser.add_argument('--keep-latest', action='store_true',
                        help='keep the most recently started GameDay game')
    parser.add_argument('--keep-game', action='append', metavar='GAME_ID',
                        default=[], help='keep this game_id (repeatable)')
    args = parser.parse_args()

    if args.list:
        _print_archive_list()
    elif args.restore:
        print(f'Restored GameDay data from {restore_gameday_data(args.restore)}')
    elif args.archive_only:
        print(f'Archived GameDay data to {archive_gameday_data()}')
    else:
        keep = list(args.keep_game)
        if args.keep_latest:
            newest = latest_game_id()
            if newest:
                keep.append(newest)
        archive_dir, deleted = archive_and_reset_gameday_data(keep)
        print(f'Archived GameDay data to {archive_dir}')
        if deleted:
            print('Purged from pitch DB: ' + ', '.join(
                f'{n} {t}' for t, n in deleted.items()))
        if keep:
            print(f'Kept game_id(s): {", ".join(keep)}')
        else:
            print('Live GameDay history, sessions, and pitch rows are now empty.')


if __name__ == '__main__':
    _main()
