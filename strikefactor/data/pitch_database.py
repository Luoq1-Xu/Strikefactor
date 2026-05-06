"""
SQLite pitch data collection system.

Captures every pitch with full 9-parameter kinematics, trajectory sampling,
at-bat context, and outcome data for analytics and pitch similarity analysis.
"""

import sqlite3
import uuid
import os
import glob
from datetime import datetime, timedelta


class PitchDB:
    """Raw SQLite layer — owns connection, schema, insert/query."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS pitches (
        pitch_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        game_mode TEXT,
        difficulty TEXT,
        created_at TEXT NOT NULL,

        -- Pitcher
        pitcher_name TEXT NOT NULL,
        pitch_type TEXT NOT NULL,
        ai_selection INTEGER,

        -- 9 kinematics
        x0 REAL, y0 REAL, z0 REAL,
        vx0 REAL, vy0 REAL, vz0 REAL,
        ax REAL, ay REAL, az REAL,
        travel_time_s REAL,

        -- Derived
        speed_mph REAL,
        pfx_x_inches REAL,
        pfx_z_inches REAL,
        target_x_ft REAL,
        target_z_ft REAL,
        plate_x_ft REAL,
        plate_z_ft REAL,

        -- Context
        strikes_before INTEGER,
        balls_before INTEGER,
        outs_before INTEGER,
        runner_1b INTEGER,
        runner_2b INTEGER,
        runner_3b INTEGER,
        batter_hand TEXT,
        prev_pitch_type TEXT,

        -- Outcome
        swing_type INTEGER,
        on_time INTEGER,
        outcome TEXT,
        is_strike INTEGER,
        is_hit INTEGER
    );

    CREATE TABLE IF NOT EXISTS pitch_trajectories (
        pitch_id TEXT NOT NULL,
        sample_idx INTEGER NOT NULL,
        t_sec REAL,
        x_ft REAL,
        y_ft REAL,
        z_ft REAL,
        PRIMARY KEY (pitch_id, sample_idx),
        FOREIGN KEY (pitch_id) REFERENCES pitches(pitch_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS at_bats (
        ab_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        pitcher_name TEXT,
        batter_hand TEXT,
        pitch_count INTEGER,
        final_outcome TEXT,
        created_at TEXT NOT NULL
    );
    """

    # Backup policy
    BACKUP_DIR_NAME = "backups"
    BACKUP_MIN_INTERVAL = timedelta(hours=1)  # don't backup more than once per hour
    BACKUP_KEEP = 30  # keep last N auto-backups

    def __init__(self, db_path):
        self.db_path = db_path
        self._auto_backup(db_path)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    @classmethod
    def _auto_backup(cls, db_path):
        """Create a timestamped snapshot of the db before opening it.

        Protects against accidental data loss (schema drops, file corruption,
        mistaken overwrites). Uses SQLite's online backup API so it is safe
        even if another process briefly held the db. Silently no-ops if the
        source db doesn't exist yet (first run) or anything goes wrong —
        backups must never prevent the game from starting.
        """
        try:
            if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
                return

            backup_dir = os.path.join(os.path.dirname(db_path), cls.BACKUP_DIR_NAME)
            os.makedirs(backup_dir, exist_ok=True)

            # Throttle: skip if a recent auto-backup already exists
            pattern = os.path.join(backup_dir, "strikefactor_auto_*.db")
            existing = sorted(glob.glob(pattern))
            if existing:
                newest_mtime = datetime.fromtimestamp(os.path.getmtime(existing[-1]))
                if datetime.now() - newest_mtime < cls.BACKUP_MIN_INTERVAL:
                    return

            # Online backup — works even with WAL / concurrent readers
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_path = os.path.join(backup_dir, f"strikefactor_auto_{timestamp}.db")
            src = sqlite3.connect(db_path)
            try:
                dst = sqlite3.connect(dest_path)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()

            # Prune old backups, keeping the most recent BACKUP_KEEP
            all_auto = sorted(glob.glob(pattern))
            for old in all_auto[:-cls.BACKUP_KEEP]:
                try:
                    os.remove(old)
                except OSError:
                    pass
        except Exception:
            # Never let backup failure stop the game from starting
            pass

    def insert_pitch(self, pitch_dict, trajectory_rows):
        """Insert a pitch and its trajectory samples in one transaction."""
        cols = ", ".join(pitch_dict.keys())
        placeholders = ", ".join("?" for _ in pitch_dict)
        with self.conn:
            self.conn.execute(
                f"INSERT INTO pitches ({cols}) VALUES ({placeholders})",
                list(pitch_dict.values()),
            )
            if trajectory_rows:
                self.conn.executemany(
                    "INSERT INTO pitch_trajectories (pitch_id, sample_idx, t_sec, x_ft, y_ft, z_ft) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    trajectory_rows,
                )

    def insert_at_bat(self, ab_dict):
        cols = ", ".join(ab_dict.keys())
        placeholders = ", ".join("?" for _ in ab_dict)
        with self.conn:
            self.conn.execute(
                f"INSERT INTO at_bats ({cols}) VALUES ({placeholders})",
                list(ab_dict.values()),
            )

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def close(self):
        self.conn.close()


class PitchDataExtractor:
    """Extract pitch records from a PitchSimulation instance."""

    # Compared against outcome.upper().replace(" ", "_") — keep keys in that form.
    TERMINAL_OUTCOMES = frozenset({
        "STRIKEOUT", "WALK", "SINGLE", "DOUBLE", "TRIPLE", "HOME_RUN",
        "FLYOUT", "GROUNDOUT", "LINEOUT",
    })

    @staticmethod
    def extract_pitch_record(sim, session_id):
        """Build a dict suitable for the pitches table."""
        traj = sim.trajectory
        pitch_id = str(uuid.uuid4())

        # Plate location from trajectory at travel_time
        plate_x, _, plate_z = traj.position_at(traj.travel_time)

        # Game mode
        if sim.game.in_gameday_mode:
            game_mode = "gameday"
        elif getattr(sim.game, 'menu_state', None) == 'sandbox_gameplay':
            game_mode = "sandbox"
        else:
            game_mode = "arcade"

        # Difficulty
        difficulty = str(sim.game.settings_manager.get_difficulty())

        # AI selection
        ai_selection = getattr(sim.game, "pitch_chosen", None)

        # Context from new_data_entry
        ctx = sim.new_data_entry

        return pitch_id, {
            "pitch_id": pitch_id,
            "session_id": session_id,
            "game_mode": game_mode,
            "difficulty": difficulty,
            "created_at": datetime.now().isoformat(),
            "pitcher_name": sim.pitchername,
            "pitch_type": sim.pitchtype,
            "ai_selection": ai_selection,
            "x0": traj.x0, "y0": traj.y0, "z0": traj.z0,
            "vx0": traj.vx0, "vy0": traj.vy0, "vz0": traj.vz0,
            "ax": traj.ax, "ay": traj.ay, "az": traj.az,
            "travel_time_s": traj.travel_time,
            "speed_mph": sim.speed_mph,
            "pfx_x_inches": sim.pfx_x,
            "pfx_z_inches": sim.pfx_z,
            "target_x_ft": sim.target_x_ft,
            "target_z_ft": sim.target_z_ft,
            "plate_x_ft": plate_x,
            "plate_z_ft": plate_z,
            "strikes_before": ctx.get("Strikes", 0),
            "balls_before": ctx.get("Balls", 0),
            "outs_before": ctx.get("Outs", 0),
            "runner_1b": int(ctx.get("RunnerFirst", False)),
            "runner_2b": int(ctx.get("RunnerSecond", False)),
            "runner_3b": int(ctx.get("RunnerThird", False)),
            "batter_hand": ctx.get("Handedness", ""),
            "prev_pitch_type": ctx.get("PrevPitch", ""),
            "swing_type": sim.swing_type,
            "on_time": sim.on_time,
            "outcome": getattr(sim, "outcome", ""),
            "is_strike": int(sim.is_strike),
            "is_hit": int(sim.is_hit),
        }

    @staticmethod
    def sample_trajectory(trajectory, n=20):
        """Sample n evenly-spaced 3D points along the trajectory."""
        t_total = trajectory.travel_time
        if t_total <= 0:
            return []
        samples = []
        for i in range(n):
            t = t_total * i / (n - 1)
            x, y, z = trajectory.position_at(t)
            samples.append((i, t, x, y, z))
        return samples


class PitchDatabaseService:
    """Singleton facade — coordinates extraction and insertion."""

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        db_path = os.path.join(os.path.dirname(__file__), "strikefactor.db")
        self.db = PitchDB(db_path)
        self.session_id = str(uuid.uuid4())
        self._ab_pitch_count = 0
        self._ab_pitcher = None
        self._ab_hand = None

    def record_pitch(self, sim):
        """Record a single pitch from a completed PitchSimulation."""
        try:
            pitch_id, record = PitchDataExtractor.extract_pitch_record(sim, self.session_id)

            # Trajectory samples
            traj_samples = PitchDataExtractor.sample_trajectory(sim.trajectory)
            traj_rows = [(pitch_id, idx, t, x, y, z) for idx, t, x, y, z in traj_samples]

            self.db.insert_pitch(record, traj_rows)

            # Track at-bat
            self._ab_pitch_count += 1
            self._ab_pitcher = sim.pitchername
            self._ab_hand = sim.new_data_entry.get("Handedness", "")

            # Check for terminal outcome
            outcome = getattr(sim, "outcome", "")
            if outcome and outcome.upper().replace(" ", "_") in PitchDataExtractor.TERMINAL_OUTCOMES:
                self._record_at_bat(outcome)
        except Exception as e:
            # Never let DB errors crash the game, but surface them so silent
            # data loss doesn't go unnoticed.
            print(f"[pitch_db] record_pitch failed: {e}")

    def _record_at_bat(self, final_outcome):
        ab = {
            "ab_id": str(uuid.uuid4()),
            "session_id": self.session_id,
            "pitcher_name": self._ab_pitcher,
            "batter_hand": self._ab_hand,
            "pitch_count": self._ab_pitch_count,
            "final_outcome": final_outcome,
            "created_at": datetime.now().isoformat(),
        }
        self.db.insert_at_bat(ab)
        self._ab_pitch_count = 0
