"""Where the player's data lives: one directory outside the package.

Two kinds of file, never mixed:

* **Resources** ship inside the package and are only ever read — sprites,
  sounds, fonts, the umpire model, the seed pitch-selection AIs, the pitch
  location and bullpen tables. `config.get_path` resolves those.
* **Player data** is everything the game writes — settings, key bindings, the
  trained AIs, the pitch database and its backups, the batting, lap and
  GameDay stores, and the maintenance tools' archives. It lives in
  `data_dir()`, here.

They used to share `strikefactor/`, which meant every session of play modified
tracked files, an installed copy would have written into site-packages, and a
wheel could not ship the resources without shipping someone's database.

`data_dir()` is `$STRIKEFACTOR_DATA_DIR` if set (the test suite points it at a
temporary directory, and it is how to keep data somewhere specific), otherwise
the platform's per-user application data directory. This module imports
nothing from the game, so the offline analysis can use it without pygame.
"""

import os
import pathlib
import sys

APP_NAME = "StrikeFactor"
ENV_VAR = "STRIKEFACTOR_DATA_DIR"

# File and directory names inside the data directory, named once so the game,
# the maintenance tools and the analysis cannot disagree about them.
DB_FILE = "strikefactor.db"
SETTINGS_FILE = "settings.json"
KEY_BINDINGS_FILE = "key_bindings.json"
BATTING_STATS_FILE = "batting_stats.json"
BATTING_STATS_LEGACY_FILE = "batting_stats_legacy_v1.json"
LAP_HISTORY_FILE = "lap_history.json"
GAMEDAY_HISTORY_FILE = "gameday_history.json"
GAMEDAY_SESSIONS_FILE = "gameday_sessions.json"
AI_DIR = "ai"
ARCHIVES_DIR = "archives"
GAMEDAY_ARCHIVES_DIR = "gameday_archives"


def default_data_dir():
    """The platform's per-user application data directory for the game."""
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", APP_NAME)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        return os.path.join(base, APP_NAME)
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, APP_NAME.lower())


def data_dir():
    """The directory player data is read from and written to.

    Resolved on each call rather than once at import, so a test or tool that
    sets `STRIKEFACTOR_DATA_DIR` sees it take effect. Not created here: every
    writer creates what it needs.
    """
    return os.environ.get(ENV_VAR) or default_data_dir()


def data_path(*parts):
    """A path inside `data_dir()`."""
    return os.path.join(data_dir(), *parts)


def db_path():
    """The pitch database."""
    return data_path(DB_FILE)


def sqlite_readonly_uri(path):
    """A `sqlite3.connect(..., uri=True)` URI opening `path` read-only.

    Read-only so that looking at a database that isn't there fails instead of
    creating an empty one. Percent-encoded, because the default macOS data
    directory has a space in it ("Application Support") and a raw `?` or `#`
    in a path would end the URI's path early.
    """
    return pathlib.Path(path).absolute().as_uri() + "?mode=ro"


def ai_path(pitcher_key):
    """A pitcher's trained pitch-selection AI, as the game last saved it."""
    return data_path(AI_DIR, f"{pitcher_key}_ai.pkl")
