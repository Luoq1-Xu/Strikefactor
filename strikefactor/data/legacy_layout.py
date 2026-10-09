"""One-time copy of player data from its old home inside the package.

Before `strikefactor.paths` existed, everything the game wrote lived in the
source tree: `strikefactor/settings.json`, `strikefactor/key_bindings.json`,
and the database, stores and archives under `strikefactor/data/`. This copies
them into the player's data directory the first time the game starts with the
new layout, so an existing player keeps their settings, history and pitch log.

**It copies; it never moves or deletes**, and it never overwrites anything
already in the data directory. The old files are left where they were, for the
player to remove once they are happy. A marker file records that the copy ran,
so it runs once per data directory.

**Quit any copy of an older version first.** One started before the upgrade
keeps writing to the old locations for as long as it runs, and anything it
writes after the copy stays behind: the marker stops a second copy. That is why
the game runs this at launch, which is the moment the old version has stopped.

Not copied:

* `data/backups/` — the database's automatic snapshots. The next launch takes
  a fresh one in the new location; the old ones stay where they are.
* `ai/*_ai.pkl` — the package's own copies are still read as seeds whenever
  the data directory has none (`PitcherManager._ai_file`), so the training in
  them carries over without a copy.

Run by `strikefactor.main.main` before the game starts. Also runnable by hand::

    python -m strikefactor.data.legacy_layout --dry-run
    python -m strikefactor.data.legacy_layout     # only with no older copy running
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime

from strikefactor import paths

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKER_FILE = ".legacy-layout-migrated.json"

# Old location (relative to the package) -> name in the data directory.
_FILES = {
    paths.SETTINGS_FILE: paths.SETTINGS_FILE,
    paths.KEY_BINDINGS_FILE: paths.KEY_BINDINGS_FILE,
    os.path.join("data", paths.BATTING_STATS_FILE): paths.BATTING_STATS_FILE,
    os.path.join("data", paths.BATTING_STATS_LEGACY_FILE): paths.BATTING_STATS_LEGACY_FILE,
    os.path.join("data", paths.LAP_HISTORY_FILE): paths.LAP_HISTORY_FILE,
    os.path.join("data", paths.GAMEDAY_HISTORY_FILE): paths.GAMEDAY_HISTORY_FILE,
    os.path.join("data", paths.GAMEDAY_SESSIONS_FILE): paths.GAMEDAY_SESSIONS_FILE,
}
_DB = (os.path.join("data", paths.DB_FILE), paths.DB_FILE)
_ARCHIVE_DIRS = {
    os.path.join("data", paths.ARCHIVES_DIR): paths.ARCHIVES_DIR,
    os.path.join("data", paths.GAMEDAY_ARCHIVES_DIR): paths.GAMEDAY_ARCHIVES_DIR,
}


def plan(package_dir: str = PACKAGE_DIR, data_dir: str = None) -> list:
    """`(kind, source, destination)` for everything a migration would copy.

    Empty once the marker exists, and for anything whose destination is
    already present — the data directory always wins.
    """
    data_dir = data_dir or paths.data_dir()
    if os.path.exists(os.path.join(data_dir, MARKER_FILE)):
        return []
    steps = []
    for old, new in _FILES.items():
        src, dst = os.path.join(package_dir, old), os.path.join(data_dir, new)
        if os.path.isfile(src) and not os.path.exists(dst):
            steps.append(("file", src, dst))
    src, dst = os.path.join(package_dir, _DB[0]), os.path.join(data_dir, _DB[1])
    if os.path.isfile(src) and os.path.getsize(src) > 0 and not os.path.exists(dst):
        steps.append(("database", src, dst))
    for old, new in _ARCHIVE_DIRS.items():
        root = os.path.join(package_dir, old)
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            src, dst = os.path.join(root, name), os.path.join(data_dir, new, name)
            if os.path.isdir(src) and not os.path.exists(dst):
                steps.append(("archive", src, dst))
    return steps


def _copy_database(src: str, dst: str) -> None:
    """Copy through SQLite's backup API, which reads through the WAL — a plain
    file copy of a WAL-mode database can miss its most recent writes."""
    source = sqlite3.connect(paths.sqlite_readonly_uri(src), uri=True)
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def migrate(package_dir: str = PACKAGE_DIR, data_dir: str = None) -> list:
    """Copy old-layout player data into the data directory, once.

    Returns the steps taken. Writes the marker even when there was nothing to
    copy (a fresh install), so later launches skip the scan.
    """
    data_dir = data_dir or paths.data_dir()
    marker = os.path.join(data_dir, MARKER_FILE)
    if os.path.exists(marker):
        return []
    steps = plan(package_dir, data_dir)
    os.makedirs(data_dir, exist_ok=True)
    for kind, src, dst in steps:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if kind == "database":
            _copy_database(src, dst)
        elif kind == "archive":
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    with open(marker, "w") as f:
        json.dump({"migrated_at": datetime.now().isoformat(),
                   "from": package_dir,
                   "copied": [[kind, src, dst] for kind, src, dst in steps]},
                  f, indent=2)
    return steps


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be copied, and copy nothing")
    args = parser.parse_args(argv)
    steps = plan() if args.dry_run else migrate()
    verb = "Would copy" if args.dry_run else "Copied"
    print(f"Data directory: {paths.data_dir()}")
    if args.dry_run and steps:
        print("Quit any running copy of the game before copying: an older "
              "version keeps writing to the old locations.")
    if not steps:
        print("Nothing to copy.")
    for kind, src, dst in steps:
        print(f"  {verb} {kind}: {os.path.relpath(src, PACKAGE_DIR)} -> {dst}")


if __name__ == "__main__":
    main()
