"""
SQLite pitch data collection system.

Captures every pitch with full 9-parameter kinematics, trajectory sampling,
at-bat context, outcome data, and per-pitch skill signals (timing, contact
quality, mistake flags, ABS umpire-vs-truth) for analytics and pitch
similarity analysis.

Tables:
- pitches: one row per thrown pitch
- pitch_trajectories: 20-point 3D trajectory samples per pitch
- at_bats: one row per resolved at-bat (pitches.ab_id joins back)
- games: one row per user-facing game (Arcade encounter, GameDay 9-inning,
         Sandbox session)
- batter_profiles: persisted BatterProfile aggregates per (mode, difficulty)
"""

import glob
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta

from strikefactor import outcomes, paths

SCHEMA_VERSION = 12  # Bumped when migrations are added; see PitchDB._migrate.

# v5 renamed the pop-up outcome from "POP_UP" to "POP UP", so it reads like
# every other recorded outcome ("HOME RUN", "LINEOUT"). Data written before v5
# carries the old spelling; _migrate rewrites it in place. Without that the
# analysis package groups on the raw string and would silently split pop-ups
# into two buckets, under-counting every PA/BF/out denominator that includes
# them.
V5_OUTCOME_RENAMES = (("POP_UP", "POP UP"),)


class PitchDB:
    """Raw SQLite layer — owns connection, schema, insert/query."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS pitches (
        pitch_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        game_id TEXT,
        ab_id TEXT,
        game_mode TEXT,
        difficulty TEXT,
        defense_strength TEXT,
        created_at TEXT NOT NULL,

        -- Pitcher
        pitcher_name TEXT NOT NULL,
        pitcher_hand TEXT,
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

        -- Command: where the pitch was aimed, vs target_* which is where it
        -- was actually commanded to. The gap between them is the miss.
        intent_x_ft REAL,
        intent_z_ft REAL,
        intent_kind TEXT,
        miss_kind TEXT,
        command_sigma_in REAL,
        location_archetype TEXT,
        platoon TEXT,

        -- AB / count context
        strikes_before INTEGER,
        balls_before INTEGER,
        outs_before INTEGER,
        runner_1b INTEGER,
        runner_2b INTEGER,
        runner_3b INTEGER,
        batter_hand TEXT,
        prev_pitch_type TEXT,

        -- GameDay context (NULL outside gameday)
        inning INTEGER,
        is_top_inning INTEGER,
        score_diff INTEGER,
        is_starter INTEGER,
        pitcher_pitch_count INTEGER,
        pitcher_fatigue REAL,
        mistake_pitch INTEGER,

        -- Skill signals
        swing_timing_diff_ms REAL,
        swing_timing_signed_ms REAL,
        contact_quality REAL,
        vertical_offset_in REAL,
        exit_velocity_mph REAL,

        -- Batted ball (NULL unless the ball was put in play)
        batted_ball_type TEXT,
        fielder_role TEXT,
        play_margin_s REAL,
        extra_base_margin_s REAL,
        spray_angle_deg REAL,

        -- Umpire / ABS
        ai_umpire_strike INTEGER,
        truth_strike INTEGER,
        abs_challenged INTEGER,
        abs_overturned INTEGER,

        -- Outcome
        swing_type INTEGER,
        on_time INTEGER,
        outcome TEXT,
        is_strike INTEGER,
        is_hit INTEGER,
        runs_scored_on_pitch INTEGER,
        earned_runs_on_pitch INTEGER
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
        game_id TEXT,
        pitcher_name TEXT,
        batter_hand TEXT,
        pitch_count INTEGER,
        final_outcome TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS games (
        game_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        game_mode TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        defense_strength TEXT,
        pitcher_name TEXT,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        final_player_score INTEGER,
        final_opponent_score INTEGER,
        result TEXT
    );

    CREATE TABLE IF NOT EXISTS batter_profiles (
        profile_key TEXT PRIMARY KEY,
        game_mode TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        aggregates_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """

    # Indexes created post-migration so they reference columns that may
    # only exist after the v1→v2 ALTER TABLEs in _migrate().
    POST_MIGRATE_INDEXES = (
        "CREATE INDEX IF NOT EXISTS idx_pitches_game ON pitches(game_id)",
        "CREATE INDEX IF NOT EXISTS idx_pitches_ab ON pitches(ab_id)",
        "CREATE INDEX IF NOT EXISTS idx_pitches_mode_diff ON pitches(game_mode, difficulty)",
    )

    # Columns added after the initial v1 schema. Each is applied via
    # ALTER TABLE if missing — SQLite doesn't support "ADD COLUMN IF NOT
    # EXISTS", so we probe the table info first.
    V2_PITCHES_COLUMNS = [
        ("game_id", "TEXT"),
        ("ab_id", "TEXT"),
        ("pitcher_hand", "TEXT"),
        ("inning", "INTEGER"),
        ("is_top_inning", "INTEGER"),
        ("score_diff", "INTEGER"),
        ("is_starter", "INTEGER"),
        ("pitcher_pitch_count", "INTEGER"),
        ("pitcher_fatigue", "REAL"),
        ("mistake_pitch", "INTEGER"),
        ("swing_timing_diff_ms", "REAL"),
        ("contact_quality", "REAL"),
        ("vertical_offset_in", "REAL"),
        ("ai_umpire_strike", "INTEGER"),
        ("truth_strike", "INTEGER"),
        ("abs_challenged", "INTEGER"),
        ("abs_overturned", "INTEGER"),
        ("runs_scored_on_pitch", "INTEGER"),
    ]
    V2_AT_BATS_COLUMNS = [
        ("game_id", "TEXT"),
    ]

    # v3: intent/execution split (see Pitcher.get_pitch_target). Rows written
    # before v3 have these NULL — target_* was the aim point back then, since
    # the ball always landed exactly on it.
    V3_PITCHES_COLUMNS = [
        ("intent_x_ft", "REAL"),
        ("intent_z_ft", "REAL"),
        ("intent_kind", "TEXT"),
        ("miss_kind", "TEXT"),
        ("command_sigma_in", "REAL"),
    ]

    # v4: named location archetypes (see data/pitch_locations.json) and the
    # platoon matchup they were selected for.
    V4_PITCHES_COLUMNS = [
        ("location_archetype", "TEXT"),
        ("platoon", "TEXT"),
    ]

    # v6: modelled exit velocity at contact (engine/contact_audio.py). Set on
    # every bat-on-ball event, fouls included; NULL on takes and whiffs. Note
    # the asymmetry with contact_quality, which stays NULL on fouls: fouls
    # never run the hit pipeline that populates it, and widening it now would
    # silently change what every existing contact_quality aggregate means.
    # EV is a model output, not a measurement — derived from quality and swing
    # type with jitter — so it adds no information. It is stored because it is
    # the number the contact SFX keyed off, which makes "why did that sound
    # like that" answerable after the fact.
    V6_PITCHES_COLUMNS = [
        ("exit_velocity_mph", "REAL"),
    ]

    # v7: what actually happened to the batted ball, so the fielding and
    # timing models can be checked against recorded play instead of only
    # against a Monte Carlo of themselves.
    #
    # Before this the DB could not tell a ground ball from a fly ball. Every
    # aggregate that wanted "GB BABIP" or "how often is a fielded grounder
    # beaten out" had to infer type from `outcome`, which is circular — the
    # outcome is what the model produced. `batted_ball_type` is classified at
    # *contact* by HitOutcomeManager, upstream of any fielding decision, so it
    # is an independent axis to slice on.
    #
    # `play_margin_s` is the infield race's margin in seconds — the throw to
    # first against the batter-runner — signed so positive favours the
    # defense (see infield_timing.PlayTiming.margin_s). It is the falsifiable
    # output of the timing model: a healthy distribution is centred well above
    # zero with a visible bang-bang shoulder, and if it ever comes out
    # bimodal-at-the-extremes the model has stopped deciding anything. NULL
    # when no infield race was run: a fly/liner caught in the air, a home run,
    # or a ball that got past the infield, whose race is a base race and is
    # recorded in `extra_base_margin_s` (v11) instead.
    V7_PITCHES_COLUMNS = [
        ("batted_ball_type", "TEXT"),
        ("fielder_role", "TEXT"),
        ("play_margin_s", "REAL"),
    ]

    # v8: the sign of the swing timing error. `swing_timing_diff_ms` has
    # always been stored abs()'d, so the DB could say how far off a swing was
    # but never whether it was early or late — which makes "does this hitter
    # chase ahead of the ball or behind it", the single most useful coaching
    # fact the game holds, structurally unanswerable. The value was already
    # being computed with its sign; only the foul path ever saw it, into a
    # field that was never persisted.
    #
    # The unsigned column stays exactly as it is. Widening it in place would
    # silently change what every existing aggregate over it means, for no
    # gain — abs() of this one recovers it.
    V8_PITCHES_COLUMNS = [
        ("swing_timing_signed_ms", "REAL"),
    ]

    # v9: which way the ball went. Degrees from centre field, **pull-positive
    # for either batter** — handedness is folded in, the way
    # `horizontal_inside` folded it in, so an aggregate over both hands means
    # something without a join.
    #
    # It is the first direction the DB has ever held. Before it, spray was not
    # merely unrecorded but *unmodelled*: a ball in play drew its bearing from
    # `random.uniform`, so there was nothing to record. Now it is read off the
    # bat's own face at contact (`spray`), which makes it an independent axis
    # to slice on in the same sense `batted_ball_type` is — decided at contact,
    # upstream of any fielding decision.
    #
    # NULL when the bat never met the ball. A swing that missed has no
    # direction, and per the v7 precedent that must not be coalesced to 0.0:
    # zero is dead centre field, a real and common value, so filling it in
    # would put a spike in the middle of the one distribution this column
    # exists to show the shape of.
    V9_PITCHES_COLUMNS = [
        ("spray_angle_deg", "REAL"),
    ]

    # v10: which defense the ball was hit into. A sibling of `difficulty` and a
    # separate axis from it on purpose — difficulty is the bat, this is the
    # glove. It moves BABIP, ground-ball hit rate, 2B/1B and the reached-on-error
    # rate, i.e. every headline number the analysis package exists to check, so
    # a rate measured across a mix of settings is a mix of games.
    #
    # NULL for rows written before the setting existed, and it must NOT be
    # back-filled to "league": that would assert older play was recorded at
    # league defense, which is neither true nor false but unknown. Those rows
    # also have a structurally zero error rate, because errors did not exist —
    # the same shape as the pre-v2 `game_id IS NULL` / `runs_scored_on_pitch IS
    # NULL` correlation that makes the pitching line compute over one slice. Any
    # error aggregate has to be taken over `defense_strength IS NOT NULL` and
    # surface what it dropped, rather than silently averaging zeros in.
    V10_PITCHES_COLUMNS = [
        ("defense_strength", "TEXT"),
    ]

    # Same column on `games`, for the same reason `difficulty` is on both: a
    # game is the unit history and the box score aggregate over.
    V10_GAMES_COLUMNS = [
        ("defense_strength", "TEXT"),
    ]

    # v11: the base race, and ABS challenges that actually reach the row.
    #
    # `extra_base_margin_s` is the race that settled how far a batter-runner
    # got on a ball past the infield (`extra_bases.final_base`): to the base
    # they held short of, or to third on a triple. Signed like
    # `play_margin_s` — `runner_s - defense_s`, positive favours the defense —
    # and the physical race, not the coach's aggression margin on top of it.
    # It is a column of its own rather than more rows of `play_margin_s`
    # because it is a different race: filling that column with it would change
    # what every existing row there means. The value was always computed; it
    # was never recorded, so every double and triple before v11 had no margin
    # at all. NULL when no base race ran, and on every row before v11.
    #
    # `abs_challenged` / `abs_overturned` existed from v2 and could never be
    # set: the row is written 0.7 s after the call with the 1.8 s challenge
    # window still open, and a challenge cannot be made until the pitch loop
    # has returned. From v11 a verdict amends the row after the fact
    # (`PitchDatabaseService.amend_abs_challenge`), and **`outcome` is the
    # final call after review** — `ai_umpire_strike` keeps what the umpire
    # said. Every row before v11 read 0 whether or not it was challenged, so
    # the migration sets both to NULL there: unknown, not "no".
    V11_PITCHES_COLUMNS = [
        ("extra_base_margin_s", "REAL"),
    ]

    # v12: earned runs. `runs_scored_on_pitch` is every run that crossed the
    # plate, and the pitching line had been charging all of them as earned,
    # including the ones a REACHED ON ERROR let in. This is the official
    # scorer's count instead (`helpers.ScoreKeeper`, Rule 9.16).
    #
    # It is the earned runs *credited* on this pitch, which is not a share of
    # `runs_scored_on_pitch`: a runner an error moved up can score before the
    # errorless inning would have scored him, and is ruled earned on the later
    # pitch that would have brought him home. So a row can carry an earned run
    # and no run. Only the sum over a half-inning compares with the runs.
    #
    # NULL on every row before v12, and it must not be back-filled from
    # `runs_scored_on_pitch`: for rows after errors existed (v10) that would
    # assert unearned runs were earned.
    V12_PITCHES_COLUMNS = [
        ("earned_runs_on_pitch", "INTEGER"),
    ]

    # Backup policy
    BACKUP_DIR_NAME = "backups"
    BACKUP_MIN_INTERVAL = timedelta(hours=1)  # don't backup more than once per hour
    BACKUP_KEEP = 30  # keep last N auto-backups

    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._auto_backup(db_path)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(self.SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Apply ALTER TABLE migrations and create post-migrate indexes.

        Indexes live here (not in SCHEMA) so they reference columns that may
        only exist after the ALTER TABLEs below run on a pre-v2 database.
        """
        cur = self.conn.execute("PRAGMA user_version")
        version = cur.fetchone()[0]

        if version < SCHEMA_VERSION:
            # Determine which columns already exist (running this on a fresh
            # v2 db is a no-op because executescript already created them).
            existing_pitches = {row[1] for row in self.conn.execute("PRAGMA table_info(pitches)")}
            for col, decl in (self.V2_PITCHES_COLUMNS + self.V3_PITCHES_COLUMNS
                             + self.V4_PITCHES_COLUMNS + self.V6_PITCHES_COLUMNS
                             + self.V7_PITCHES_COLUMNS + self.V8_PITCHES_COLUMNS
                             + self.V9_PITCHES_COLUMNS + self.V10_PITCHES_COLUMNS
                             + self.V11_PITCHES_COLUMNS + self.V12_PITCHES_COLUMNS):
                if col not in existing_pitches:
                    self.conn.execute(f"ALTER TABLE pitches ADD COLUMN {col} {decl}")

            existing_ab = {row[1] for row in self.conn.execute("PRAGMA table_info(at_bats)")}
            for col, decl in self.V2_AT_BATS_COLUMNS:
                if col not in existing_ab:
                    self.conn.execute(f"ALTER TABLE at_bats ADD COLUMN {col} {decl}")

            existing_games = {row[1] for row in self.conn.execute("PRAGMA table_info(games)")}
            for col, decl in self.V10_GAMES_COLUMNS:
                if col not in existing_games:
                    self.conn.execute(f"ALTER TABLE games ADD COLUMN {col} {decl}")

            # v5: outcome-string renames. Idempotent — re-running finds no rows
            # with the old spelling. Both tables store the outcome as free text,
            # so this is a value rewrite rather than a schema change.
            if version < 5:
                for old, new in V5_OUTCOME_RENAMES:
                    self.conn.execute(
                        "UPDATE pitches SET outcome = ? WHERE outcome = ?", (new, old)
                    )
                    self.conn.execute(
                        "UPDATE at_bats SET final_outcome = ? WHERE final_outcome = ?",
                        (new, old),
                    )

            # v11: the ABS flags on every earlier row are structurally 0 —
            # no challenge could ever reach the row — so they are unknown,
            # not "not challenged". See V11_PITCHES_COLUMNS.
            if version < 11:
                self.conn.execute(
                    "UPDATE pitches SET abs_challenged = NULL, abs_overturned = NULL"
                )

            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

        # Always (re)create indexes — IF NOT EXISTS makes this cheap.
        for sql in self.POST_MIGRATE_INDEXES:
            self.conn.execute(sql)

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

    def insert_game(self, game_dict):
        cols = ", ".join(game_dict.keys())
        placeholders = ", ".join("?" for _ in game_dict)
        with self.conn:
            self.conn.execute(
                f"INSERT INTO games ({cols}) VALUES ({placeholders})",
                list(game_dict.values()),
            )

    def update_game(self, game_id, updates):
        if not updates:
            return
        sets = ", ".join(f"{k} = ?" for k in updates.keys())
        params = list(updates.values()) + [game_id]
        with self.conn:
            self.conn.execute(f"UPDATE games SET {sets} WHERE game_id = ?", params)

    def amend_pitch(self, pitch_id, updates, at_bat_statements=()):
        """Update one pitch row and apply `(sql, params)` at-bat statements,
        in one transaction — a verdict that changes the pitch and not the
        at-bat it closed would leave the two tables disagreeing."""
        sets = ", ".join(f"{k} = ?" for k in updates)
        with self.conn:
            self.conn.execute(f"UPDATE pitches SET {sets} WHERE pitch_id = ?",
                              list(updates.values()) + [pitch_id])
            for sql, params in at_bat_statements:
                self.conn.execute(sql, params)

    def upsert_batter_profile(self, profile_key, game_mode, difficulty, aggregates_json):
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO batter_profiles (profile_key, game_mode, difficulty, aggregates_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(profile_key) DO UPDATE SET
                    aggregates_json = excluded.aggregates_json,
                    updated_at = excluded.updated_at
                """,
                (profile_key, game_mode, difficulty, aggregates_json, datetime.now().isoformat()),
            )

    def get_batter_profile(self, profile_key):
        row = self.conn.execute(
            "SELECT aggregates_json FROM batter_profiles WHERE profile_key = ?",
            (profile_key,),
        ).fetchone()
        return row[0] if row else None

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def close(self):
        self.conn.close()


class PitchDataExtractor:
    """Extract pitch records from a PitchSimulation instance."""

    # The underscored form, because this set is compared against
    # `outcomes.db_key(outcome)`. Derived rather than enumerated: an outcome
    # missing here does not raise, it silently never closes the at-bat, so the
    # set must not be somewhere a new outcome can fail to be added.
    TERMINAL_OUTCOMES = outcomes.DB_TERMINAL_OUTCOMES

    @staticmethod
    def _classify_game_mode(sim):
        """The mode of the session the pitch was thrown in (`Game.game_mode`).

        Read off the session rather than inferred from `menu_state`, which
        names whatever screen is up and was the source of a Sandbox session
        being filed as Arcade. A pitch is only ever thrown inside a session,
        so the Arcade default is for the stub games tests build.
        """
        return getattr(sim.game, 'game_mode', None) or "arcade"

    @staticmethod
    def _difficulty_value(sim):
        # Use the .value form ("hall_of_fame") so it joins cleanly against
        # gameday_history.json and the games table.
        return sim.game.settings_manager.get_difficulty().value

    @staticmethod
    def _defense_value(sim):
        """Which defense this pitch was thrown in front of.

        Falls back to None rather than to the neutral level: a row that could
        not read the setting is unknown, not average, and the v10 column's
        whole contract is that NULL means "not recorded" (see
        V10_PITCHES_COLUMNS).
        """
        try:
            return sim.game.settings_manager.get_defense_level()
        except Exception:
            return None

    @staticmethod
    def _gameday_context(sim):
        """Pull GameDay-specific context. Returns dict with NULL-able fields."""
        if not sim.game.in_gameday_mode or sim.game.gameday_manager is None:
            return {
                "inning": None,
                "is_top_inning": None,
                "score_diff": None,
                "is_starter": None,
                "pitcher_pitch_count": None,
                "pitcher_fatigue": None,
            }
        gm = sim.game.gameday_manager
        # pitch_count on PitcherStats is incremented AFTER the pitch resolves
        # via the gameplay flow; at extract time it reflects the count BEFORE
        # this pitch (which is what we want for "pitcher_pitch_count entering
        # this pitch"). The active stats object updates fatigue with it.
        try:
            stats = gm.get_active_pitcher_stats()
            pc = stats.pitch_count
            fatigue = stats.fatigue
        except Exception:
            pc, fatigue = None, None
        is_starter = int(gm.current_pitcher_name == gm.opponent_pitcher_preset.get('starter'))
        return {
            "inning": gm.current_inning,
            "is_top_inning": int(bool(gm.is_top_inning)),
            "score_diff": gm.player_score - gm.opponent_score,
            "is_starter": is_starter,
            "pitcher_pitch_count": pc,
            "pitcher_fatigue": fatigue,
        }

    @staticmethod
    def extract_pitch_record(sim, session_id, game_id, ab_id):
        """Build a dict suitable for the pitches table."""
        traj = sim.trajectory
        pitch_id = str(uuid.uuid4())

        # Plate location from trajectory at travel_time
        plate_x, _, plate_z = traj.position_at(traj.travel_time)

        game_mode = PitchDataExtractor._classify_game_mode(sim)
        difficulty = PitchDataExtractor._difficulty_value(sim)
        defense_strength = PitchDataExtractor._defense_value(sim)
        ai_selection = getattr(sim.game, "pitch_chosen", None)
        ctx = sim.new_data_entry
        gd = PitchDataExtractor._gameday_context(sim)
        # The pitcher's own `throws`, stamped on the simulation. It used to be
        # a lookup keyed by roster name ('sale') against `sim.pitchername`,
        # which is the name the pitch methods pass ('chrissale') — so every
        # pitcher but Yamamoto recorded NULL.
        pitcher_hand = getattr(sim, "pitcher_hand", None)
        intent = getattr(sim, "pitch_intent", None)

        record = {
            "pitch_id": pitch_id,
            "session_id": session_id,
            "game_id": game_id,
            "ab_id": ab_id,
            "game_mode": game_mode,
            "difficulty": difficulty,
            "defense_strength": defense_strength,
            "created_at": datetime.now().isoformat(),
            "pitcher_name": sim.pitchername,
            "pitcher_hand": pitcher_hand,
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
            "intent_x_ft": getattr(sim, "intent_x_ft", None),
            "intent_z_ft": getattr(sim, "intent_z_ft", None),
            "intent_kind": intent.intent_kind if intent else None,
            "miss_kind": intent.miss_kind if intent else None,
            "command_sigma_in": intent.command_sigma_in if intent else None,
            "location_archetype": (intent.archetype or None) if intent else None,
            "platoon": intent.platoon if intent else None,
            "strikes_before": ctx.get("Strikes", 0),
            "balls_before": ctx.get("Balls", 0),
            "outs_before": ctx.get("Outs", 0),
            "runner_1b": int(ctx.get("RunnerFirst", False)),
            "runner_2b": int(ctx.get("RunnerSecond", False)),
            "runner_3b": int(ctx.get("RunnerThird", False)),
            "batter_hand": ctx.get("Handedness", ""),
            "prev_pitch_type": ctx.get("PrevPitch", ""),
            "inning": gd["inning"],
            "is_top_inning": gd["is_top_inning"],
            "score_diff": gd["score_diff"],
            "is_starter": gd["is_starter"],
            "pitcher_pitch_count": gd["pitcher_pitch_count"],
            "pitcher_fatigue": gd["pitcher_fatigue"],
            "mistake_pitch": int(bool(getattr(sim, "mistake_pitch", False))),
            "swing_timing_diff_ms": getattr(sim, "swing_timing_diff_ms", None),
            "swing_timing_signed_ms": getattr(sim, "swing_timing_signed_ms", None),
            "contact_quality": getattr(sim, "contact_quality", None),
            "vertical_offset_in": getattr(sim, "vertical_offset_in", None),
            "exit_velocity_mph": getattr(sim, "exit_velocity_mph", None),
            "batted_ball_type": getattr(sim, "batted_ball_type", None),
            "fielder_role": getattr(sim, "fielder_role", None),
            "play_margin_s": getattr(sim, "play_margin_s", None),
            "extra_base_margin_s": getattr(sim, "extra_base_margin_s", None),
            "spray_angle_deg": getattr(sim, "spray_angle_deg", None),
            "ai_umpire_strike": _nullable_int(getattr(sim, "ai_umpire_strike", None)),
            "truth_strike": _nullable_int(getattr(sim, "truth_strike", None)),
            "abs_challenged": int(bool(getattr(sim, "abs_challenged", False))),
            "abs_overturned": int(bool(getattr(sim, "abs_overturned", False))),
            "swing_type": sim.swing_type,
            "on_time": sim.on_time,
            "outcome": getattr(sim, "outcome", ""),
            "is_strike": int(sim.is_strike),
            "is_hit": int(sim.is_hit),
            "runs_scored_on_pitch": int(getattr(sim, "runs_scored_on_pitch", 0) or 0),
            "earned_runs_on_pitch": int(getattr(sim, "earned_runs_on_pitch", 0) or 0),
        }
        return pitch_id, record

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


def _nullable_int(v):
    if v is None:
        return None
    return int(bool(v))


class PitchDatabaseService:
    """Singleton facade — coordinates extraction and insertion.

    Lifecycle model:
    - session_id: per-process UUID, set in __init__ and never reset.
    - current_game_id: per-game UUID, set by start_game(), cleared by end_game().
    - current_ab_id: per-at-bat UUID, generated lazily on first pitch of an AB
      and cleared once the at-bat resolves.
    """

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.db = PitchDB(paths.db_path())
        self.session_id = str(uuid.uuid4())
        self.current_game_id = None
        self.current_ab_id = None
        self._ab_pitch_count = 0
        self._ab_pitcher = None
        self._last_pitch = None
        self._ab_hand = None

    # --- Game lifecycle ---

    def start_game(self, game_mode, difficulty, pitcher_name=None,
                   defense_strength=None):
        """Begin a new game. Returns the new game_id.

        Auto-ends any previously-open game so callers don't have to remember
        to balance every transition path. The auto-end stamps ended_at but
        leaves scores/result NULL since the previous game wasn't completed
        through a normal end (player abandoned to menu mid-game).
        """
        if self.current_game_id is not None:
            self.end_game()
        game_id = str(uuid.uuid4())
        try:
            self.db.insert_game({
                "game_id": game_id,
                "session_id": self.session_id,
                "game_mode": game_mode,
                "difficulty": difficulty,
                "defense_strength": defense_strength,
                "pitcher_name": pitcher_name,
                "started_at": datetime.now().isoformat(),
                "ended_at": None,
                "final_player_score": None,
                "final_opponent_score": None,
                "result": None,
            })
        except Exception as e:
            print(f"[pitch_db] start_game failed: {e}")
        self.current_game_id = game_id
        # Reset per-AB state so a new game doesn't inherit a stale AB.
        self.current_ab_id = None
        self._ab_pitch_count = 0
        self._ab_pitcher = None
        self._last_pitch = None
        self._ab_hand = None
        return game_id

    def resume_game(self, game_id):
        """Reattach to an existing games row so a resumed game keeps one game_id.

        Used by the GameDay resume path. Returns the game_id actually attached,
        or None if the row no longer exists — the caller should fall back to
        start_game() in that case. Any currently-open game is closed first, the
        same as start_game() does.
        """
        if not game_id:
            return None
        try:
            row = self.db.conn.execute(
                "SELECT game_id FROM games WHERE game_id = ?", (game_id,)).fetchone()
        except Exception as e:
            print(f"[pitch_db] resume_game lookup failed: {e}")
            return None
        if row is None:
            return None

        if self.current_game_id is not None and self.current_game_id != game_id:
            self.end_game()
        # Reopen the row: a mid-game quit stamped ended_at via the auto-end in
        # start_game(), and leaving that set would mark a live game finished.
        try:
            self.db.update_game(game_id, {
                "ended_at": None,
                "final_player_score": None,
                "final_opponent_score": None,
                "result": None,
            })
        except Exception as e:
            print(f"[pitch_db] resume_game reopen failed: {e}")
        self.current_game_id = game_id
        self.current_ab_id = None
        self._ab_pitch_count = 0
        self._ab_pitcher = None
        self._last_pitch = None
        self._ab_hand = None
        return game_id

    def end_game(self, player_score=None, opponent_score=None, result=None):
        """Finalize the current game with score and result. No-op if no game open."""
        if self.current_game_id is None:
            return
        try:
            self.db.update_game(self.current_game_id, {
                "ended_at": datetime.now().isoformat(),
                "final_player_score": player_score,
                "final_opponent_score": opponent_score,
                "result": result,
            })
        except Exception as e:
            print(f"[pitch_db] end_game failed: {e}")
        ended_id = self.current_game_id
        self.current_game_id = None
        self.current_ab_id = None
        self._ab_pitch_count = 0
        self._ab_pitcher = None
        self._last_pitch = None
        self._ab_hand = None
        return ended_id

    # --- Pitch / AB recording ---

    def record_pitch(self, sim):
        """Record a single pitch from a completed PitchSimulation.

        Returns the new row's `pitch_id`, or None if the write failed. The id
        is how an ABS verdict finds the row afterwards — see
        `amend_abs_challenge`.
        """
        self._last_pitch = None
        try:
            # Ensure an AB id exists for this pitch — generate lazily so that
            # even pitches outside a started_game (shouldn't happen, but
            # defensive) still get grouped.
            if self.current_ab_id is None:
                self.current_ab_id = str(uuid.uuid4())

            pitch_id, record = PitchDataExtractor.extract_pitch_record(
                sim, self.session_id, self.current_game_id, self.current_ab_id
            )

            traj_samples = PitchDataExtractor.sample_trajectory(sim.trajectory)
            traj_rows = [(pitch_id, idx, t, x, y, z) for idx, t, x, y, z in traj_samples]

            self.db.insert_pitch(record, traj_rows)

            # Track at-bat
            self._ab_pitch_count += 1
            self._ab_pitcher = sim.pitchername
            self._ab_hand = sim.new_data_entry.get("Handedness", "")

            # The at-bat as it stands before this pitch can close it. An ABS
            # overturn of this pitch may have to reopen it, and closing it
            # clears the live tracking this is copied from.
            self._last_pitch = dict(self._open_at_bat(), pitch_id=pitch_id,
                                    closed_at_bat=False)

            # Check for terminal outcome
            outcome = getattr(sim, "outcome", "")
            if self._is_terminal(outcome):
                self._record_at_bat(outcome)
                self._last_pitch["closed_at_bat"] = True
            return pitch_id
        except Exception as e:
            # Never let DB errors crash the game, but surface them so silent
            # data loss doesn't go unnoticed.
            print(f"[pitch_db] record_pitch failed: {e}")
            return None

    @staticmethod
    def _is_terminal(outcome):
        return bool(outcome) and (outcomes.db_key(outcome)
                                  in PitchDataExtractor.TERMINAL_OUTCOMES)

    def _open_at_bat(self):
        return {
            "ab_id": self.current_ab_id,
            "game_id": self.current_game_id,
            "ab_pitch_count": self._ab_pitch_count,
            "pitcher": self._ab_pitcher,
            "hand": self._ab_hand,
        }

    def _at_bat_row(self, final_outcome, ab):
        return {
            "ab_id": ab["ab_id"],
            "session_id": self.session_id,
            "game_id": ab["game_id"],
            "pitcher_name": ab["pitcher"],
            "batter_hand": ab["hand"],
            "pitch_count": ab["ab_pitch_count"],
            "final_outcome": final_outcome,
            "created_at": datetime.now().isoformat(),
        }

    def _record_at_bat(self, final_outcome):
        try:
            self.db.insert_at_bat(self._at_bat_row(final_outcome,
                                                   self._open_at_bat()))
        except Exception as e:
            print(f"[pitch_db] insert_at_bat failed: {e}")
        self._close_at_bat()

    def _close_at_bat(self):
        self.current_ab_id = None
        self._ab_pitch_count = 0

    def amend_abs_challenge(self, pitch_id, *, overturned, outcome=None,
                            is_strike=None, runs_scored_on_pitch=None,
                            earned_runs_on_pitch=None):
        """Record an ABS challenge against the pitch it was made on.

        After the fact because it has to be: the row is written with the
        challenge window still open (see `PitchSimulation.cleanup`). On an
        overturn the row takes the call as it now stands — `outcome` is the
        final call after review, `ai_umpire_strike` keeps the umpire's — and
        the at-bat that call closed, or did not, is put right in the same
        transaction:

            walk <-> strikeout              the at-bat's final_outcome
            walk/strikeout -> ball/strike   the at-bat is reopened
            ball/strike -> walk/strikeout   the at-bat is closed now

        Only the most recently recorded pitch of the current game can be
        amended. That costs nothing in play — the next pitch closes the
        window — and it is what makes reopening an at-bat safe: nothing has
        been recorded into it since. Returns True when the row was amended.
        """
        last = self._last_pitch
        if pitch_id is None or last is None or last["pitch_id"] != pitch_id:
            print(f"[pitch_db] ABS verdict for pitch {pitch_id} not recorded: "
                  f"it is not the latest pitch of this game")
            return False

        updates = {"abs_challenged": 1, "abs_overturned": int(bool(overturned))}
        statements = []
        was_terminal = last["closed_at_bat"]
        now_terminal = was_terminal
        if overturned and outcome:
            updates["outcome"] = outcome
            if is_strike is not None:
                updates["is_strike"] = int(bool(is_strike))
            if runs_scored_on_pitch is not None:
                updates["runs_scored_on_pitch"] = int(runs_scored_on_pitch)
            if earned_runs_on_pitch is not None:
                updates["earned_runs_on_pitch"] = int(earned_runs_on_pitch)
            now_terminal = self._is_terminal(outcome)
            if was_terminal and now_terminal:
                statements.append(("UPDATE at_bats SET final_outcome = ? WHERE ab_id = ?",
                                   (outcome, last["ab_id"])))
            elif was_terminal:
                statements.append(("DELETE FROM at_bats WHERE ab_id = ?",
                                   (last["ab_id"],)))
            elif now_terminal:
                row = self._at_bat_row(outcome, last)
                statements.append((
                    f"INSERT INTO at_bats ({', '.join(row)}) "
                    f"VALUES ({', '.join('?' for _ in row)})",
                    list(row.values())))
        try:
            self.db.amend_pitch(pitch_id, updates, statements)
        except Exception as e:
            print(f"[pitch_db] ABS amend failed: {e}")
            return False

        # Bring the live at-bat tracking into line with the table.
        if was_terminal and not now_terminal:
            self.current_ab_id = last["ab_id"]
            self._ab_pitch_count = last["ab_pitch_count"]
            self._ab_pitcher = last["pitcher"]
            self._ab_hand = last["hand"]
        elif now_terminal and not was_terminal:
            self._close_at_bat()
        last["closed_at_bat"] = now_terminal
        return True

    # --- BatterProfile persistence ---

    @staticmethod
    def _profile_key(game_mode, difficulty):
        return f"{game_mode}|{difficulty}"

    def save_batter_profile(self, game_mode, difficulty, aggregates_dict):
        """Persist a BatterProfile's serialized aggregates."""
        try:
            self.db.upsert_batter_profile(
                self._profile_key(game_mode, difficulty),
                game_mode,
                difficulty,
                json.dumps(aggregates_dict),
            )
        except Exception as e:
            print(f"[pitch_db] save_batter_profile failed: {e}")

    def load_batter_profile(self, game_mode, difficulty):
        """Return a previously persisted BatterProfile dict, or None."""
        try:
            blob = self.db.get_batter_profile(self._profile_key(game_mode, difficulty))
            if blob is None:
                return None
            return json.loads(blob)
        except Exception as e:
            print(f"[pitch_db] load_batter_profile failed: {e}")
            return None
