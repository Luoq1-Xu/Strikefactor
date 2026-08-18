"""Archive and reset *all* recorded play, across every mode and every store.

The wider sibling of [gameday_maintenance.py](gameday_maintenance.py), which
snapshots only the GameDay slice. This one covers everything the game records
about how it has been played: the whole pitch log for arcade, sandbox and
gameday alike, the at-bat and game rows around it, the batter tendency
profiles the pitch-selection AI reads, the batting heatmap, the Sandbox lap
log, and the GameDay career record.

It exists because a change to the contact geometry makes previously recorded
play describe a *different game*. The `collision_angled` sign fix is the case
it was written for: the bat the engine swung before it was mirrored across the
horizontal from the one the player was pointing, and because the contact
rectangle is long and thin that changed the bat's effective reach as a
function of aim height — contact ran 67% on low pitches against 93% in the
middle of the zone. Aggregates spanning the fix average two different bats
together, and no amount of filtering fixes a heatmap bucket that already
summed both.

**Archive everything or archive nothing.** The trap `gameday_maintenance`
documents applies with more force here: clearing the JSON stores while leaving
the pitch log makes the history say one thing and the analysis another. The
snapshot is a full copy of the database file rather than an extracted slice —
at this scope there is nothing to slice, and a whole file is directly
queryable with no reassembly.

Resetting preserves schema and `user_version`; it deletes rows, never tables,
so the next launch writes into a database that is current rather than one that
has to be migrated from scratch.

Run from the repository root as a module::

    python -m strikefactor.data.reset_tracking --list
    python -m strikefactor.data.reset_tracking --dry-run
    python -m strikefactor.data.reset_tracking --reason "collision_angled sign fix"
    python -m strikefactor.data.reset_tracking --restore 20260817_120000
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime

from strikefactor.utils.io import atomic_write_json

DATA_DIR = os.path.dirname(__file__)
ARCHIVE_ROOT = os.path.join(DATA_DIR, 'archives')
DB_PATH = os.path.join(DATA_DIR, 'strikefactor.db')
DB_ARCHIVE_NAME = 'strikefactor.db'
MANIFEST_NAME = 'MANIFEST.json'

# Child tables first. `pitch_trajectories` cascades from `pitches` anyway, but
# ordering it explicitly keeps the reset correct if foreign keys are ever off.
DB_TABLES = ('pitch_trajectories', 'pitches', 'at_bats', 'games', 'batter_profiles')

# Archived basename -> (live path, payload key, empty payload).
#
# Each store is rewritten to an empty *shape* rather than deleted, so the
# `version` field survives and the next load reads a current file instead of
# recreating a default one that may be a schema behind.
JSON_STORES = {
    'gameday_history.json': ('gameday_history.json', 'games', []),
    'gameday_sessions.json': ('gameday_sessions.json', 'sessions', []),
    'lap_history.json': ('lap_history.json', 'laps', []),
    'batting_stats.json': ('batting_stats.json', 'buckets', {}),
}


def _timestamp() -> str:
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def _new_archive_dir() -> str:
    """A snapshot directory that is guaranteed not to already exist.

    Names are second-resolution timestamps, so two snapshots in the same
    second would otherwise land in the same directory — and since `restore`
    takes a safety snapshot before overwriting the live stores, restoring
    within a second of archiving would clobber the very snapshot being
    restored *from* and then read the emptied copy back. Losing data on the
    recovery path is the one failure this module cannot have.
    """
    base = os.path.join(ARCHIVE_ROOT, _timestamp())
    candidate, suffix = base, 2
    while os.path.exists(candidate):
        candidate = f'{base}_{suffix}'
        suffix += 1
    os.makedirs(candidate)
    return candidate


def _live_path(name: str) -> str:
    return os.path.join(DATA_DIR, JSON_STORES[name][0])


def _connect(path: str = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# --- Inventory ---------------------------------------------------------------

def inventory() -> dict:
    """What is currently recorded, per store. The dry run and the manifest
    both read this, so what gets reported is what gets archived."""
    counts = {}
    if os.path.exists(DB_PATH):
        conn = _connect()
        try:
            for table in DB_TABLES:
                try:
                    counts[table] = conn.execute(
                        f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                except sqlite3.OperationalError:
                    counts[table] = 0          # table not created yet
            counts['_by_mode'] = {
                row['game_mode']: row['n'] for row in conn.execute(
                    'SELECT game_mode, COUNT(*) AS n FROM pitches GROUP BY 1')
            } if counts.get('pitches') else {}
        finally:
            conn.close()

    for name, (_rel, key, _empty) in JSON_STORES.items():
        path = _live_path(name)
        if not os.path.exists(path):
            counts[name] = 0
            continue
        try:
            with open(path) as handle:
                counts[name] = len(json.load(handle).get(key) or ())
        except (json.JSONDecodeError, OSError):
            counts[name] = -1                  # present but unreadable
    return counts


def list_archives() -> list:
    if not os.path.isdir(ARCHIVE_ROOT):
        return []
    return sorted(name for name in os.listdir(ARCHIVE_ROOT)
                  if os.path.isdir(os.path.join(ARCHIVE_ROOT, name)))


# --- Archive -----------------------------------------------------------------

def archive(reason: str = '') -> str:
    """Snapshot every tracking store into a new timestamped directory.

    The database is copied whole, with its WAL checkpointed first — a plain
    file copy of a database in WAL mode can otherwise miss committed rows that
    are still only in the sidecar.
    """
    os.makedirs(ARCHIVE_ROOT, exist_ok=True)
    archive_dir = _new_archive_dir()

    counts = inventory()

    if os.path.exists(DB_PATH):
        conn = _connect()
        try:
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            conn.close()
        shutil.copy2(DB_PATH, os.path.join(archive_dir, DB_ARCHIVE_NAME))

    archived_json = []
    for name in JSON_STORES:
        path = _live_path(name)
        if os.path.exists(path):
            shutil.copy2(path, os.path.join(archive_dir, name))
            archived_json.append(name)

    atomic_write_json(os.path.join(archive_dir, MANIFEST_NAME), {
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'reason': reason,
        'scope': 'all modes, all tracking stores',
        'database': DB_ARCHIVE_NAME if os.path.exists(DB_PATH) else None,
        'json_files': archived_json,
        'counts': counts,
    })
    return archive_dir


# --- Reset -------------------------------------------------------------------

def reset() -> dict:
    """Clear every tracking store, preserving schema and file shape."""
    cleared = {}

    if os.path.exists(DB_PATH):
        conn = _connect()
        try:
            with conn:
                for table in DB_TABLES:
                    try:
                        cleared[table] = conn.execute(
                            f'DELETE FROM "{table}"').rowcount
                    except sqlite3.OperationalError:
                        cleared[table] = 0
            conn.execute('VACUUM')
        finally:
            conn.close()

    for name, (_rel, key, empty) in JSON_STORES.items():
        path = _live_path(name)
        if not os.path.exists(path):
            cleared[name] = 0
            continue
        try:
            with open(path) as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            payload = {}
        cleared[name] = len(payload.get(key) or ())
        # A fresh container each time — the entry in JSON_STORES is a shape,
        # not an object to hand out and let a caller mutate.
        payload[key] = type(empty)()
        payload['last_updated'] = datetime.now().isoformat(timespec='seconds')
        atomic_write_json(path, payload)

    return cleared


def archive_and_reset(reason: str = '') -> tuple:
    archive_dir = archive(reason)
    return archive_dir, reset()


# --- Restore -----------------------------------------------------------------

def restore(archive_name: str) -> str:
    """Put a snapshot back, replacing everything currently recorded.

    The live state is archived first. Restoring is itself destructive, and
    finding that out afterwards is exactly the situation this module exists to
    prevent.
    """
    archive_dir = os.path.join(ARCHIVE_ROOT, archive_name)
    if not os.path.isdir(archive_dir):
        raise FileNotFoundError(f'no such archive: {archive_name}')

    archive(reason=f'pre-restore safety snapshot ({archive_name})')

    db_snapshot = os.path.join(archive_dir, DB_ARCHIVE_NAME)
    if os.path.exists(db_snapshot):
        for sidecar in ('-wal', '-shm'):
            stale = DB_PATH + sidecar
            if os.path.exists(stale):
                os.remove(stale)
        shutil.copy2(db_snapshot, DB_PATH)

    for name in JSON_STORES:
        snapshot = os.path.join(archive_dir, name)
        if os.path.exists(snapshot):
            shutil.copy2(snapshot, _live_path(name))
    return archive_dir


# --- CLI ---------------------------------------------------------------------

def _format_counts(counts: dict) -> str:
    lines = []
    for key, value in counts.items():
        if key == '_by_mode':
            if value:
                modes = '  '.join(f'{k}={v}' for k, v in sorted(value.items()))
                lines.append(f'    pitches by mode: {modes}')
            continue
        lines.append(f'    {key:<22} {value:>8}')
    return '\n'.join(lines)


def _main() -> None:
    parser = argparse.ArgumentParser(
        description='Archive and reset all recorded play, across every mode.')
    parser.add_argument('--list', action='store_true',
                        help='list existing snapshots and exit')
    parser.add_argument('--dry-run', action='store_true',
                        help='report what would be archived and cleared')
    parser.add_argument('--restore', metavar='NAME',
                        help='restore a snapshot (archives current state first)')
    parser.add_argument('--reason', default='',
                        help='recorded in the snapshot manifest')
    args = parser.parse_args()

    if args.list:
        names = list_archives()
        if not names:
            print('No snapshots.')
            return
        print(f'{len(names)} snapshot(s) in {ARCHIVE_ROOT}:')
        for name in names:
            manifest = os.path.join(ARCHIVE_ROOT, name, MANIFEST_NAME)
            reason = ''
            if os.path.exists(manifest):
                with open(manifest) as handle:
                    reason = json.load(handle).get('reason', '')
            print(f'  {name}  {reason}')
        return

    if args.restore:
        print(f'Restored from {restore(args.restore)}')
        return

    if args.dry_run:
        print('Would archive and clear:')
        print(_format_counts(inventory()))
        return

    archive_dir, cleared = archive_and_reset(args.reason)
    print(f'Archived to {archive_dir}')
    print('Cleared:')
    print(_format_counts(cleared))


if __name__ == '__main__':
    _main()
