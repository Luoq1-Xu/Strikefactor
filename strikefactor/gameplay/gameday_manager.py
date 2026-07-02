"""
GameDay Manager - Handles full 9-inning game simulation logic.
Manages opponent at-bats, pitcher substitutions, and event logging.
"""

import json
import os
import random
import uuid
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from helpers import ScoreKeeper
from utils.io import atomic_write_json
# Single source of truth for the pitcher roster lives in config; re-exported
# here so existing `from gameplay.gameday_manager import ALL_PITCHERS` imports
# keep working.
from config import ALL_PITCHERS


# --- Player-team pitcher attributes (roles, caps, quality multipliers) ---
# Loaded from data/pitcher_attributes.json so designers can tune without
# editing code. Each entry shapes the simulation in three ways:
#   role / max_pitches / max_ip → bullpen management & hook timing
#   k_mult / bb_mult / hit_mult → per-pitcher outcome distribution
_ATTRS_PATH = os.path.join(os.path.dirname(__file__), '..', 'data',
                           'pitcher_attributes.json')

NEUTRAL_ATTRS = {
    "role": "MIDDLE",
    "max_pitches": 30,
    "max_ip": 1.0,
    "k_mult": 1.0,
    "bb_mult": 1.0,
    "hit_mult": 1.0,
}


def _load_pitcher_attributes() -> dict:
    try:
        with open(_ATTRS_PATH, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


PITCHER_ATTRS = _load_pitcher_attributes()


DEFAULT_OPPONENT_LINEUP = [
    "J. Smith", "A. Johnson", "M. Davis", "R. Wilson",
    "K. Brown", "T. Martinez", "C. Garcia", "D. Rodriguez", "S. Lee",
]


def get_pitcher_attrs(name: str) -> dict:
    """Look up attributes for a pitcher, falling back to a neutral default.

    Returns a fresh copy of the neutral default so a caller mutating the
    result can't corrupt NEUTRAL_ATTRS for every other attr-less pitcher.
    """
    return PITCHER_ATTRS.get(name, dict(NEUTRAL_ATTRS))


class GameEvent:
    """Represents a single game event (at-bat result)."""

    def __init__(self, inning: int, is_top: bool, batter_name: str,
                 pitcher_name: str, result: str, runs_scored: int = 0):
        self.inning = inning
        self.is_top = is_top  # Top = opponent batting, Bottom = player batting
        self.batter_name = batter_name
        self.pitcher_name = pitcher_name
        self.result = result  # "SINGLE", "DOUBLE", "STRIKEOUT", "GROUNDOUT", etc.
        self.runs_scored = runs_scored

    def __str__(self):
        half = "Top" if self.is_top else "Bot"
        # Mound visits have no batter — show just the result
        if self.result.startswith("MOUND VISIT"):
            return f"[{half} {self.inning}] {self.result}"
        runs_str = f" ({self.runs_scored} run{'s' if self.runs_scored != 1 else ''})" if self.runs_scored > 0 else ""
        return f"[{half} {self.inning}] {self.batter_name} - {self.result}{runs_str} (vs {self.pitcher_name})"

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict (used by GameDayManager.to_dict)."""
        return {
            'inning': self.inning,
            'is_top': self.is_top,
            'batter_name': self.batter_name,
            'pitcher_name': self.pitcher_name,
            'result': self.result,
            'runs_scored': self.runs_scored,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'GameEvent':
        return cls(
            inning=d['inning'],
            is_top=d['is_top'],
            batter_name=d['batter_name'],
            pitcher_name=d['pitcher_name'],
            result=d['result'],
            runs_scored=d.get('runs_scored', 0),
        )


class PitcherStats:
    """Track pitcher statistics during a game."""

    def __init__(self, name: str):
        self.name = name
        self.pitch_count = 0
        self.outs_recorded = 0
        self.hits_allowed = 0
        self.runs_allowed = 0
        self.strikeouts = 0
        self.walks = 0
        self.home_runs_allowed = 0
        self.consecutive_hits = 0  # Tracks back-to-back hits for relief decisions
        self.is_active = False

    @property
    def fatigue(self) -> float:
        """Fatigue level from 0.0 to 1.0 based on pitch count."""
        if self.pitch_count < 30:
            return 0.0
        return min(1.0, (self.pitch_count - 30) / 90.0)  # 0 at 30, 1.0 at 120

    def get_fatigue_label(self) -> str:
        """Get a human-readable fatigue level."""
        f = self.fatigue
        if f < 0.15:
            return "Fresh"
        elif f < 0.4:
            return "Low"
        elif f < 0.65:
            return "Moderate"
        elif f < 0.85:
            return "High"
        else:
            return "Gassed"

    def get_mistake_chance(self) -> float:
        """Chance of throwing a mistake pitch (drifts to center zone)."""
        if self.pitch_count >= 100:
            return 0.15
        elif self.pitch_count >= 80:
            return 0.08
        return 0.0

    def get_velocity_modifier(self) -> float:
        """Velocity multiplier (1.0 = no change, decreases with fatigue)."""
        return 1.0 - (0.05 * self.fatigue)  # Up to -5% at max fatigue

    def get_movement_modifier(self) -> float:
        """Movement (acceleration) multiplier, decreases with fatigue."""
        return 1.0 - (0.10 * self.fatigue)  # Up to -10% at max fatigue

    def record_pitch(self):
        """Increment pitch count."""
        self.pitch_count += 1

    def record_outcome(self, outcome: str, runs: int = 0):
        """Record the result of an at-bat."""
        if outcome in ['STRIKEOUT', 'FLYOUT', 'GROUNDOUT', 'LINEOUT', 'POP_UP']:
            self.outs_recorded += 1
            if outcome == 'STRIKEOUT':
                self.strikeouts += 1
            self.consecutive_hits = 0
        elif outcome in ['SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN']:
            self.hits_allowed += 1
            self.consecutive_hits += 1
            if outcome == 'HOME RUN':
                self.home_runs_allowed += 1
        elif outcome == 'WALK':
            self.walks += 1
            # Walk doesn't reset consecutive hits (still in trouble)

        self.runs_allowed += runs

    def get_innings_pitched(self) -> float:
        """Calculate innings pitched (true decimal, for internal logic)."""
        return self.outs_recorded / 3.0

    def get_ip_display(self) -> str:
        """Format innings pitched in baseball notation (e.g. 6.2 = 6 full + 2 outs)."""
        full_innings = self.outs_recorded // 3
        partial_outs = self.outs_recorded % 3
        return f"{full_innings}.{partial_outs}"

    def get_summary(self) -> str:
        """Get a summary string of pitcher stats."""
        ip = self.get_ip_display()
        return (f"{self.name}: {ip} IP, {self.hits_allowed} H, "
                f"{self.runs_allowed} R, {self.strikeouts} K, "
                f"{self.walks} BB, {self.pitch_count} pitches")

    # All PitcherStats fields are flat primitives, so (de)serialization is a
    # straight attribute copy. Keyed by this tuple so to_dict/from_dict stay in
    # sync if a field is added.
    _SERIAL_FIELDS = ('name', 'pitch_count', 'outs_recorded', 'hits_allowed',
                      'runs_allowed', 'strikeouts', 'walks', 'home_runs_allowed',
                      'consecutive_hits', 'is_active')

    def to_dict(self) -> dict:
        return {f: getattr(self, f) for f in self._SERIAL_FIELDS}

    @classmethod
    def from_dict(cls, d: dict) -> 'PitcherStats':
        stats = cls(d['name'])
        for f in cls._SERIAL_FIELDS:
            if f in d:
                setattr(stats, f, d[f])
        return stats


class GameDayManager:
    """Manages a full 9-inning baseball game."""

    HISTORY_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'gameday_history.json')

    # Base outcome probabilities for opponent simulation
    BASE_OPPONENT_OUTCOMES = {
        'STRIKEOUT': 0.22,
        'WALK': 0.08,
        'GROUNDOUT': 0.23,
        'FLYOUT': 0.20,
        'LINEOUT': 0.05,
        'SINGLE': 0.14,
        'DOUBLE': 0.05,
        'TRIPLE': 0.01,
        'HOME RUN': 0.02
    }

    # Difficulty modifiers for opponent batting strength
    DIFFICULTY_MODIFIERS = {
        'rookie':       {'hit_mult': 0.6,  'walk_mult': 0.7, 'k_mult': 1.4},
        'amateur':      {'hit_mult': 1.0,  'walk_mult': 1.0, 'k_mult': 1.0},
        'professional': {'hit_mult': 1.15, 'walk_mult': 1.1, 'k_mult': 0.9},
        'all_star':     {'hit_mult': 1.3,  'walk_mult': 1.2, 'k_mult': 0.8},
        'hall_of_fame': {'hit_mult': 1.5,  'walk_mult': 1.3, 'k_mult': 0.7},
    }

    def __init__(self, player_name: str = "Player", difficulty: str = "amateur",
                 starter_name: str = "yamamoto"):
        self.player_name = player_name
        self.opponent_name = "Opponent"
        self.difficulty = difficulty

        # Stable per-game id. Used to key this game's resumable session entry
        # (gameday_sessions.json) so each inning-boundary autosave updates the
        # same row, and so completion can remove it. Preserved across resume.
        self.session_uuid = str(uuid.uuid4())

        # Game state
        self.current_inning = 1
        self.is_top_inning = True  # True = opponent batting, False = player batting
        self.player_score = 0
        self.opponent_score = 0
        self.game_over = False
        self.is_walkoff = False
        self._result_saved = False

        # Inning-by-inning score tracking
        self.player_inning_scores = []
        self.opponent_inning_scores = []
        self._current_half_runs = 0

        # Momentum tracking (opponent consecutive hits for simulation)
        self._consecutive_hits = 0
        # Player momentum tracking
        self.player_consecutive_hits = 0

        # Current half-inning state
        self.current_outs = 0
        self.player_scorekeeper = ScoreKeeper()  # For player's at-bats
        self.opponent_scorekeeper = ScoreKeeper()  # For opponent's at-bats

        # Opponent pitchers (player bats against these - actual game pitchers).
        # Relievers are derived from ALL_PITCHERS minus the chosen starter so
        # the pool always mirrors the currently installed roster.
        if starter_name not in ALL_PITCHERS:
            starter_name = 'yamamoto'
        self.opponent_pitcher_preset = {
            'starter': starter_name,
            'relievers': [p for p in ALL_PITCHERS if p != starter_name],
            'pitch_count_thresholds': [90, 100, 110]  # More aggressive relief thresholds
        }
        self.current_pitcher_name = self.opponent_pitcher_preset['starter']
        self.opponent_pitcher_stats: Dict[str, PitcherStats] = {}
        self.opponent_pitcher_stats[self.current_pitcher_name] = PitcherStats(self.current_pitcher_name)
        self.opponent_pitcher_stats[self.current_pitcher_name].is_active = True
        self.available_opponent_relievers = self.opponent_pitcher_preset['relievers'].copy()

        # Player's team pitchers (opponent bats against these - simulated only).
        # Starter/reliever split is derived from pitcher_attributes.json so
        # changes to roles live in one place. Fall back to the legacy lists if
        # the attributes file is unavailable.
        #
        # Invariant: only one starter is used per game. STARTER-role pitchers
        # never enter `available_player_relievers`, so the reliever-selection
        # code can't bring a second starter in for relief.
        starters_from_attrs = [n for n, a in PITCHER_ATTRS.items()
                               if a.get('role') == 'STARTER']
        relievers_from_attrs = [n for n, a in PITCHER_ATTRS.items()
                                if a.get('role') and a.get('role') != 'STARTER']
        self.player_pitcher_preset = {
            'starters': starters_from_attrs or ['yesavage', 'scherzer', 'snell'],
            'relievers': relievers_from_attrs or ['hoffman', 'lauer', 'vesia', 'chapman'],
        }
        self.current_player_pitcher_name = random.choice(self.player_pitcher_preset['starters'])
        self.player_pitcher_stats: Dict[str, PitcherStats] = {}
        self.player_pitcher_stats[self.current_player_pitcher_name] = PitcherStats(self.current_player_pitcher_name)
        self.player_pitcher_stats[self.current_player_pitcher_name].is_active = True
        self.available_player_relievers = self.player_pitcher_preset['relievers'].copy()
        self.player_pitcher_innings_pitched = 0  # Track innings for current pitcher

        # Event log
        self.event_log: List[GameEvent] = []

        # Opponent batter lineup (just names for logging)
        self.opponent_lineup = list(DEFAULT_OPPONENT_LINEUP)
        self.current_batter_index = 0

    # --- Probability adjustment methods ---

    def _get_adjusted_probabilities(self, extra_hit_boost: float = 0.0) -> dict:
        """Get opponent outcome probabilities adjusted for difficulty,
        the active pitcher's quality, and situational modifiers.
        """
        mods = self.DIFFICULTY_MODIFIERS.get(self.difficulty,
               self.DIFFICULTY_MODIFIERS['amateur'])
        attrs = get_pitcher_attrs(self.current_player_pitcher_name)

        probs = dict(self.BASE_OPPONENT_OUTCOMES)

        # Per-pitcher quality: applied first so it stacks multiplicatively
        # with difficulty and situational modifiers.
        for key in ('SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN'):
            probs[key] *= attrs.get('hit_mult', 1.0)
        probs['WALK'] *= attrs.get('bb_mult', 1.0)
        probs['STRIKEOUT'] *= attrs.get('k_mult', 1.0)

        # Apply difficulty modifiers
        for key in ['SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN']:
            probs[key] *= mods['hit_mult']
        probs['WALK'] *= mods['walk_mult']
        probs['STRIKEOUT'] *= mods['k_mult']

        # Apply situational boost (fatigue + momentum + clutch)
        if extra_hit_boost > 0:
            for key in ['SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN']:
                probs[key] *= (1.0 + extra_hit_boost)

        # Renormalize to sum to 1.0
        total = sum(probs.values())
        return {k: v / total for k, v in probs.items()}

    def _get_pitcher_fatigue_boost(self) -> float:
        """Calculate hit probability boost based on pitcher fatigue.
        Returns 0.0 under 50 pitches, linear ramp to 0.15 at 100+ pitches."""
        stats = self.get_active_player_pitcher_stats()
        if stats.pitch_count < 50:
            return 0.0
        return min(0.15, (stats.pitch_count - 50) / 333.0)

    def _get_momentum_boost(self) -> float:
        """Calculate momentum boost from consecutive hits (2% per hit, max 8%)."""
        return min(0.08, self._consecutive_hits * 0.02)

    def _get_clutch_boost(self) -> float:
        """Calculate clutch boost with runners in scoring position (3%)."""
        sk = self.opponent_scorekeeper
        if sk.get_runners_on_base() > 0:
            if sk.isRunnerOnBase(2) or sk.isRunnerOnBase(3):
                return 0.03
        return 0.0

    # --- Core game methods ---

    def get_current_batter_name(self) -> str:
        """Get the current batter's name."""
        if self.is_top_inning:
            return self.opponent_lineup[self.current_batter_index]
        else:
            return self.player_name

    def advance_batter(self):
        """Move to the next batter in the lineup."""
        self.current_batter_index = (self.current_batter_index + 1) % len(self.opponent_lineup)

    def get_current_pitcher(self) -> str:
        """Get the current pitcher's name."""
        return self.current_pitcher_name

    def get_active_pitcher_stats(self) -> PitcherStats:
        """Get stats for the currently active opponent pitcher (player faces)."""
        return self.opponent_pitcher_stats[self.current_pitcher_name]

    def get_active_player_pitcher_stats(self) -> PitcherStats:
        """Get stats for the currently active player's pitcher (opponent faces)."""
        return self.player_pitcher_stats[self.current_player_pitcher_name]

    def should_consider_relief_pitcher(self) -> bool:
        """Check if we should consider bringing in a relief pitcher (opponent team)."""
        stats = self.get_active_pitcher_stats()

        # Don't relieve if no relievers available
        if not self.available_opponent_relievers:
            return False

        # Check if current pitcher is a reliever (not the starter)
        is_starter = (self.current_pitcher_name == self.opponent_pitcher_preset['starter'])

        # Emergency relief: high fatigue + runs allowed this inning
        if stats.fatigue >= 0.6 and stats.runs_allowed >= 2:
            return random.random() < 0.85  # 85% emergency pull

        # Common: Check runs allowed for any pitcher type
        if stats.runs_allowed >= 5:
            return random.random() < 0.8
        if stats.runs_allowed >= 3:
            return random.random() < 0.4

        if is_starter:
            if stats.pitch_count >= 110:
                return random.random() < 0.95
            if stats.pitch_count >= 100:
                return random.random() < 0.8
            if stats.pitch_count >= 90:
                return random.random() < 0.6
        else:
            innings_pitched = stats.get_innings_pitched()
            if innings_pitched >= 3.0:
                return random.random() < 0.9
            if innings_pitched >= 2.0:
                return random.random() < 0.6
            if innings_pitched >= 1.0:
                return random.random() < 0.3
            if stats.pitch_count >= 40:
                return random.random() < 0.8
            if stats.pitch_count >= 30:
                return random.random() < 0.5

        return False

    def substitute_relief_pitcher(self) -> Optional[str]:
        """Substitute in a relief pitcher (opponent team). Returns new pitcher name or None."""
        if not self.available_opponent_relievers:
            return None

        # Set current pitcher as inactive
        old_pitcher = self.current_pitcher_name
        self.opponent_pitcher_stats[old_pitcher].is_active = False

        # Choose a random reliever
        new_pitcher = random.choice(self.available_opponent_relievers)
        self.available_opponent_relievers.remove(new_pitcher)

        # Log mound visit event with both old and new pitcher names
        mound_event = GameEvent(
            self.current_inning, self.is_top_inning,
            "", old_pitcher,
            f"MOUND VISIT - {old_pitcher.upper()} relieved by {new_pitcher.upper()}"
        )
        self.event_log.append(mound_event)

        # Initialize stats for new pitcher
        self.current_pitcher_name = new_pitcher
        self.opponent_pitcher_stats[new_pitcher] = PitcherStats(new_pitcher)
        self.opponent_pitcher_stats[new_pitcher].is_active = True

        return new_pitcher

    def _get_pull_score(self, between_innings: bool = False) -> float:
        """Compute a 0-1 'pull score' for the active player pitcher.

        Pulls together what a real pitching coach weighs batter-to-batter:
        per-role pitch/IP caps, cumulative damage (the *whole outing*, not
        just this inning), recent trouble, and leverage. A higher score
        means the pitcher is more likely to be pulled. Values >= 1.0 are
        automatic.
        """
        stats = self.get_active_player_pitcher_stats()
        attrs = get_pitcher_attrs(self.current_player_pitcher_name)
        role = attrs.get('role', 'MIDDLE')
        is_starter = role == 'STARTER'
        is_mopup = role == 'MOPUP'

        pc = stats.pitch_count
        ip = stats.get_innings_pitched()
        max_pitches = attrs.get('max_pitches', 30)
        # Starters don't have a hard IP cap; relievers do.
        max_ip = attrs.get('max_ip', 99.0)

        # --- Hard pulls: any of these returns 1.0 immediately ---
        if pc >= max_pitches:
            return 1.0
        if ip >= max_ip:
            return 1.0
        # Cumulative meltdown threshold: standard arms get pulled at 5 ER,
        # but the mop-up man is *expected* to absorb runs in a blowout, so
        # we let him soak more before yanking him.
        meltdown_er = 8 if is_mopup else 5
        if stats.runs_allowed >= meltdown_er:
            return 1.0

        score = 0.0

        # --- Pitch-count fatigue ramp, scaled to the pitcher's own cap ---
        # Ramp begins at 70% of max_pitches and saturates at the cap.
        ramp_start = 0.7 * max_pitches
        if pc >= ramp_start:
            denom = max(1.0, 0.3 * max_pitches)
            score += min(0.6, (pc - ramp_start) / denom * 0.6)

        # --- Workload (innings pitched) ---
        if is_starter:
            if ip >= 7.0:
                score += 0.5
            elif ip >= 6.0:
                score += 0.25
            elif ip >= 5.0:
                score += 0.1
        else:
            # Approaching the IP cap is its own pressure on the manager.
            if ip >= 0.85 * max_ip:
                score += 0.4
            elif ip >= 0.5 * max_ip:
                score += 0.15

        # --- Cumulative damage across the whole outing ---
        # This is what makes a reliever's full-game ER history matter, not
        # just whatever fits inside the current half-inning. The mop-up
        # man's whole job is to eat a bad game, so we don't sweat his ER.
        cum_er = stats.runs_allowed
        if not is_mopup:
            if cum_er >= 4:
                score += 0.5
            elif cum_er >= 3:
                score += 0.3
            elif cum_er >= 2 and not is_starter:
                # Relievers wear damage harder than starters do.
                score += 0.2

        # --- Recent trouble (consecutive hits) ---
        # Same intuition: don't yank the mop-up arm for in-game trouble.
        if not is_mopup:
            consec = stats.consecutive_hits
            if consec >= 3:
                score += 0.5
            elif consec >= 2:
                score += 0.25

        # --- This inning's damage (situational on top of cumulative) ---
        if self._current_half_runs >= 3:
            score += 0.45
        elif self._current_half_runs >= 2:
            score += 0.2
        elif self._current_half_runs >= 1:
            score += 0.05

        # --- Big inning with no outs (meltdown signature) ---
        if self._current_half_runs >= 2 and self.current_outs == 0:
            score += 0.2

        # --- Closer-out-of-context guard ---
        # The closer belongs in the 9th+ when the game is on the line
        # (save spot, tied, or trailing by 1). If he ended up in any other
        # context — early-game blowout, mid-game mop-up — push the hook
        # hard so he gets pulled the next batter.
        if role == 'CLOSER':
            lead = self.player_score - self.opponent_score
            in_context = (self.current_inning >= 9 and -1 <= lead <= 3)
            if not in_context:
                score += 0.6

        # --- Between innings: lower threshold for a clean change ---
        if between_innings:
            score += 0.15

        return score

    def should_consider_player_relief_pitcher(self, between_innings: bool = False) -> bool:
        """Decide whether to pull the active player pitcher.

        Called after every batter (mid-inning) and between innings.
        Uses a composite pull score with a probabilistic threshold so
        decisions feel natural rather than mechanical.
        """
        if not self.available_player_relievers:
            return False
        # No point pulling if no eligible replacement (e.g. only CLOSER left
        # outside a save spot). Leaves the current pitcher in.
        if self._pick_player_reliever() is None:
            return False

        score = self._get_pull_score(between_innings)

        # Automatic pull
        if score >= 1.0:
            return True

        # Below a minimum score, never pull
        if score < 0.35:
            return False

        # Probabilistic zone: higher score → higher chance
        # At 0.35 → ~10%, at 0.7 → ~70%, at 0.9 → ~95%
        pull_prob = (score - 0.25) / 0.75  # linear map 0.25→0, 1.0→1.0
        pull_prob = max(0.0, min(1.0, pull_prob))
        return random.random() < pull_prob

    def _pick_player_reliever(self) -> Optional[str]:
        """Pick a reliever by role + leverage, mirroring how a real bullpen
        is sequenced. Priorities in order:
          - Blowout (down 5+) → MOPUP, then LONG (eat innings cheaply).
          - 9th+ save spot (lead 1-3) → CLOSER.
          - 9th+ tied / 1-run game → CLOSER (high-leverage tied game).
          - 7th-8th close game → SETUP > MIDDLE > LONG.
          - Default mid-game → MIDDLE > LONG > SETUP.
          - Last-resort fallback if everything else is gone → MOPUP, then
            CLOSER (only in 8th+, never first-half mop-up duty).
        Returns None when no eligible replacement exists (caller leaves
        the current pitcher in).
        """
        pool = self.available_player_relievers
        if not pool:
            return None

        def role_of(name: str) -> str:
            return get_pitcher_attrs(name).get('role', 'MIDDLE')

        def first_with_role(target: str) -> Optional[str]:
            for p in pool:
                if role_of(p) == target:
                    return p
            return None

        lead = self.player_score - self.opponent_score  # >0 means we lead
        inning = self.current_inning

        # Blowout (down 5+) → mop-up first (designed for this), then long
        # man. Protects high-leverage arms for closer games.
        if lead <= -5:
            for target in ('MOPUP', 'LONG'):
                cand = first_with_role(target)
                if cand:
                    return cand

        # 9th+ save situation (lead by 1-3) → closer.
        if inning >= 9 and 1 <= lead <= 3:
            cand = first_with_role('CLOSER')
            if cand:
                return cand

        # 9th+ tied or trailing by 1 → closer (high-leverage tied game,
        # what real managers do on the road).
        if inning >= 9 and -1 <= lead <= 0:
            cand = first_with_role('CLOSER')
            if cand:
                return cand

        # Late and close (7th-8th, within 3) → setup arms first.
        if inning >= 7 and abs(lead) <= 3:
            for target in ('SETUP', 'MIDDLE', 'LONG'):
                cand = first_with_role(target)
                if cand:
                    return cand

        # Default mid-game sequence — CLOSER and MOPUP excluded.
        for target in ('MIDDLE', 'LONG', 'SETUP'):
            cand = first_with_role(target)
            if cand:
                return cand

        # Last-resort fallback: standard arms exhausted. Try mop-up first
        # (he's built for this); then closer in late game only. This keeps
        # us from getting stuck letting one melted-down reliever absorb
        # an entire inning worth of damage.
        cand = first_with_role('MOPUP')
        if cand:
            return cand
        cand = first_with_role('CLOSER')
        if cand and inning >= 8:
            return cand

        return None

    def substitute_player_relief_pitcher(self) -> Optional[str]:
        """Substitute in a relief pitcher for player's team. Returns new pitcher name or None."""
        if not self.available_player_relievers:
            return None

        new_pitcher = self._pick_player_reliever()
        if new_pitcher is None:
            return None

        # Set current pitcher as inactive
        self.player_pitcher_stats[self.current_player_pitcher_name].is_active = False

        self.available_player_relievers.remove(new_pitcher)

        # Initialize stats for new pitcher
        self.current_player_pitcher_name = new_pitcher
        self.player_pitcher_stats[new_pitcher] = PitcherStats(new_pitcher)
        self.player_pitcher_stats[new_pitcher].is_active = True

        return new_pitcher

    def simulate_opponent_at_bat(self) -> Tuple[str, int]:
        """
        Simulate one at-bat for the opponent.
        Returns (outcome, runs_scored).
        """
        # Calculate situational boosts
        fatigue = self._get_pitcher_fatigue_boost()
        momentum = self._get_momentum_boost()
        clutch = self._get_clutch_boost()
        total_boost = fatigue + momentum + clutch

        # Choose outcome based on adjusted probabilities
        probs = self._get_adjusted_probabilities(extra_hit_boost=total_boost)
        outcomes = list(probs.keys())
        probabilities = list(probs.values())
        outcome = random.choices(outcomes, weights=probabilities, k=1)[0]

        # Track PLAYER'S pitcher stats (opponent is batting against player's pitcher)
        pitcher_stats = self.get_active_player_pitcher_stats()
        # Simulate pitches per at-bat (weighted toward realistic counts)
        # Strikeouts/walks tend to have more pitches; outs in play fewer
        if outcome == 'STRIKEOUT':
            pitches_thrown = random.choices([3, 4, 5, 6], weights=[15, 30, 35, 20], k=1)[0]
        elif outcome == 'WALK':
            pitches_thrown = random.choices([4, 5, 6, 7], weights=[10, 30, 40, 20], k=1)[0]
        else:
            pitches_thrown = random.choices([1, 2, 3, 4, 5], weights=[5, 15, 35, 30, 15], k=1)[0]
        for _ in range(pitches_thrown):
            pitcher_stats.record_pitch()

        # Process the outcome
        runs_scored = 0

        if outcome in ['STRIKEOUT', 'FLYOUT', 'GROUNDOUT', 'LINEOUT', 'POP_UP']:
            self.current_outs += 1
            if outcome == 'STRIKEOUT':
                pitcher_stats.record_outcome(outcome)
            else:
                before_score = self.opponent_scorekeeper.get_score()
                suppress_advancement = self.current_outs >= 3
                self.opponent_scorekeeper.update_hit_event(
                    outcome,
                    suppress_out_advancement=suppress_advancement,
                )
                runs_scored = self.opponent_scorekeeper.get_score() - before_score
                self.opponent_score += runs_scored  # Add to cumulative score
                self._current_half_runs += runs_scored
                pitcher_stats.record_outcome(outcome, runs_scored)
            self._consecutive_hits = 0

        elif outcome == 'WALK':
            before_score = self.opponent_scorekeeper.get_score()
            self.opponent_scorekeeper.update_walk_event()
            runs_scored = self.opponent_scorekeeper.get_score() - before_score
            self.opponent_score += runs_scored  # Add to cumulative score
            self._current_half_runs += runs_scored
            pitcher_stats.record_outcome(outcome, runs_scored)
            # Walk doesn't reset or add to consecutive hits

        elif outcome in ['SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN']:
            before_score = self.opponent_scorekeeper.get_score()
            self.opponent_scorekeeper.update_hit_event(outcome)
            runs_scored = self.opponent_scorekeeper.get_score() - before_score
            self.opponent_score += runs_scored  # Add to cumulative score
            self._current_half_runs += runs_scored
            pitcher_stats.record_outcome(outcome, runs_scored)
            self._consecutive_hits += 1

        # Log the event (with player's pitcher name)
        batter_name = self.get_current_batter_name()
        event = GameEvent(
            self.current_inning, self.is_top_inning,
            batter_name, self.current_player_pitcher_name,
            outcome, runs_scored
        )
        self.event_log.append(event)

        # Advance to next batter
        self.advance_batter()

        return outcome, runs_scored

    def record_player_at_bat(self, outcome: str, runs_scored: int = 0, pitches_thrown: int = 0):
        """
        Record a player's at-bat result.

        Args:
            outcome: The result (e.g., "SINGLE", "STRIKEOUT", etc.)
            runs_scored: Number of runs scored on this play
            pitches_thrown: Number of pitches thrown during this at-bat
        """
        # Update opponent pitcher stats (player is batting against opponent pitcher)
        pitcher_stats = self.get_active_pitcher_stats()

        # Record pitches thrown
        for _ in range(pitches_thrown):
            pitcher_stats.record_pitch()

        pitcher_stats.record_outcome(outcome, runs_scored)

        # Log the event with actual pitcher name
        event = GameEvent(
            self.current_inning, self.is_top_inning,
            self.player_name, self.current_pitcher_name,
            outcome, runs_scored
        )
        self.event_log.append(event)

        # Fold this at-bat's runs into the cumulative + half-inning totals so
        # the box score and check_walkoff stay in sync with each batter.
        self.player_score += runs_scored
        self._current_half_runs += runs_scored

        # Track player momentum
        if outcome in ['SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN']:
            self.player_consecutive_hits += 1
        elif outcome in ['STRIKEOUT', 'FLYOUT', 'GROUNDOUT', 'LINEOUT', 'POP_UP']:
            self.player_consecutive_hits = 0
        # WALK doesn't reset streak

        # Check for outs
        if outcome in ['STRIKEOUT', 'FLYOUT', 'GROUNDOUT', 'LINEOUT', 'POP_UP']:
            self.current_outs += 1

    def check_walkoff(self) -> bool:
        """Check if a walk-off condition is met.

        Returns:
            True if the player has taken the lead in the bottom of the 9th+.
        """
        if (self.current_inning >= 9
                and not self.is_top_inning
                and not self.game_over
                and self.player_score > self.opponent_score):
            # Commit the walk-off half-inning's runs before ending the game.
            # end_half_inning() won't run on a walk-off, so without this the
            # persisted player_inning_scores would omit this inning and fail
            # to sum to player_score. The not-game_over guard above keeps this
            # idempotent if check_walkoff() is called again.
            self.player_inning_scores.append(self._current_half_runs)
            self._current_half_runs = 0
            self.game_over = True
            self.is_walkoff = True
            return True
        return False

    def end_half_inning(self):
        """End the current half inning and switch sides.

        After 9 innings, the game ends as soon as one side leads at the end
        of a complete inning. If still tied, play continues into extras
        (10th, 11th, ...). The home team's bottom half is skipped whenever
        they already lead going into it (standard baseball convention)."""
        self.current_outs = 0
        self._consecutive_hits = 0

        if self.is_top_inning:
            # Top half ended, switch to bottom (player bats)
            self.opponent_inning_scores.append(self._current_half_runs)
            self._current_half_runs = 0
            self.is_top_inning = False
            self.opponent_scorekeeper.reset()

            # If the home team (player) already leads after the top of the
            # 9th or any extra inning, the bottom half isn't played.
            if self.current_inning >= 9 and self.player_score > self.opponent_score:
                self.game_over = True
                return
        else:
            # Bottom half ended
            self.player_inning_scores.append(self._current_half_runs)
            self._current_half_runs = 0
            self.is_top_inning = True
            self.player_scorekeeper.reset()

            # After the 9th, end the game only if a winner is decided.
            # Otherwise (tied), keep playing extra innings.
            if (self.current_inning >= 9
                    and self.player_score != self.opponent_score):
                self.game_over = True
                return

            # Move to the next inning (regular or extra).
            self.current_inning += 1

    def get_player_momentum_bonus(self) -> float:
        """Get momentum bonus for player (expands contact window or boosts hit quality).
        Returns 0.0 if streak < 2, otherwise 0.03 per consecutive hit, max 0.12."""
        if self.player_consecutive_hits < 2:
            return 0.0
        return min(0.12, self.player_consecutive_hits * 0.03)

    def is_player_hot(self) -> bool:
        """Check if player is on a hot streak (2+ consecutive hits)."""
        return self.player_consecutive_hits >= 2

    # --- Display / summary methods ---

    def get_box_score_lines(self) -> dict:
        """Get inning-by-inning score arrays for box score display.

        Includes the current half-inning's runs even before
        end_half_inning() has been called, so the box score stays in sync.
        Always returns at least 9 columns; expands automatically when the
        game has gone into extra innings.
        """
        opp = list(self.opponent_inning_scores)
        plr = list(self.player_inning_scores)

        # Append the in-progress half-inning runs if not yet committed
        if self.is_top_inning and len(opp) < self.current_inning:
            opp.append(self._current_half_runs)
        elif (not self.is_top_inning) and len(plr) < self.current_inning:
            plr.append(self._current_half_runs)

        # Show at least 9 innings; grow if we've reached extras
        n = max(9, len(opp), len(plr), self.current_inning)
        opp = opp + [0] * (n - len(opp))
        plr = plr + [0] * (n - len(plr))
        return {
            'opponent': opp,
            'player': plr,
            'opponent_total': self.opponent_score,
            'player_total': self.player_score,
        }

    def get_score_summary(self) -> str:
        """Get a formatted score summary."""
        return f"{self.opponent_name}: {self.opponent_score}  |  {self.player_name}: {self.player_score}"

    def get_inning_summary(self) -> str:
        """Get current inning info."""
        half = "Top" if self.is_top_inning else "Bottom"
        return f"{half} of Inning {self.current_inning} - {self.current_outs} out{'s' if self.current_outs != 1 else ''}"

    def get_opponent_pitcher_stats(self) -> List[PitcherStats]:
        """Get stats for opponent pitchers (player bats against)."""
        return list(self.opponent_pitcher_stats.values())

    def get_player_pitcher_stats(self) -> List[PitcherStats]:
        """Get stats for player's pitchers (opponent bats against)."""
        return list(self.player_pitcher_stats.values())

    def get_recent_events(self, count: int = 10) -> List[GameEvent]:
        """Get the most recent events."""
        return self.event_log[-count:] if len(self.event_log) > count else self.event_log

    def get_winner(self) -> str:
        """Get the winner of the game (call after game is over)."""
        if self.player_score > self.opponent_score:
            return self.player_name
        return self.opponent_name

    # --- Persistence methods ---

    def save_game_result(self, game_id: Optional[str] = None,
                         session_id: Optional[str] = None):
        """Save the completed game result to gameday_history.json.

        game_id / session_id are foreign keys back into the pitch DB so the
        per-pitch log can be joined to the high-level game outcome.
        """
        if self._result_saved:
            return
        self._result_saved = True

        player_hits, opponent_hits = self._game_hit_totals()
        play_log = []
        for play_index, event in enumerate(self.event_log, start=1):
            play_entry = event.to_dict()
            play_entry['play_index'] = play_index
            play_log.append(play_entry)

        if self.player_score > self.opponent_score:
            result_str = "WIN"
        elif self.player_score < self.opponent_score:
            result_str = "LOSS"
        else:
            result_str = "TIE"
        result = {
            'date': datetime.now().isoformat(),
            'game_id': game_id,
            'session_id': session_id,
            'player_score': self.player_score,
            'opponent_score': self.opponent_score,
            'player_name': self.player_name,
            'player_hits': player_hits,
            'opponent_hits': opponent_hits,
            'result': result_str,
            'difficulty': self.difficulty,
            'player_inning_scores': self.player_inning_scores,
            'opponent_inning_scores': self.opponent_inning_scores,
            'opponent_starter': self.opponent_pitcher_preset['starter'],
            'opponent_lineup': list(self.opponent_lineup),
            'play_log_version': 1,
            'play_log': play_log,
        }

        history = self._load_history()
        history['games'].append(result)
        history['last_updated'] = datetime.now().isoformat()

        # Keep last 100 games
        if len(history['games']) > 100:
            history['games'] = history['games'][-100:]

        # Atomic write so a crash mid-save can't truncate the history file and
        # silently wipe the entire career record on the next load.
        atomic_write_json(self.HISTORY_FILE, history)

    def _game_hit_totals(self) -> tuple[int, int]:
        """Return (player_hits, opponent_hits) for the completed game.

        Hits are derived from the event log so the completed history record
        doesn't depend on the pitch database being available at read time.
        """
        player_hits = 0
        opponent_hits = 0
        for event in self.event_log:
            if event.result not in ('SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN'):
                continue
            if event.is_top:
                opponent_hits += 1
            else:
                player_hits += 1
        return player_hits, opponent_hits

    @classmethod
    def _load_history(cls) -> dict:
        """Load game history from file."""
        try:
            if os.path.exists(cls.HISTORY_FILE):
                with open(cls.HISTORY_FILE, 'r') as f:
                    return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            if isinstance(e, json.JSONDecodeError):
                print(f"Warning: GameDay history file {cls.HISTORY_FILE} is corrupt "
                      f"({e}); starting from an empty record.")
        return {'version': '1.0', 'games': [], 'last_updated': None}

    @classmethod
    def get_career_record(cls) -> dict:
        """Get win/loss record from saved history."""
        history = cls._load_history()
        wins = sum(1 for g in history['games'] if g.get('result') == 'WIN')
        losses = sum(1 for g in history['games'] if g.get('result') == 'LOSS')
        return {'wins': wins, 'losses': losses, 'total': wins + losses}

    @classmethod
    def load_history_record_vs(cls, pitcher_name: str) -> dict:
        """Get win/loss record from saved history, filtered to games where
        the given pitcher was the opponent starter. Callable without an instance
        because the pitcher carousel renders before a GameDayManager exists."""
        target = (pitcher_name or '').lower()
        history = cls._load_history()
        games = [g for g in history['games']
                 if (g.get('opponent_starter') or '').lower() == target]
        wins = sum(1 for g in games if g.get('result') == 'WIN')
        losses = sum(1 for g in games if g.get('result') == 'LOSS')
        return {'wins': wins, 'losses': losses, 'total': wins + losses}

    @classmethod
    def get_history_games(cls) -> List[dict]:
        """Return completed games most-recent-first for the history viewer.

        gameday_history.json stores games oldest-first (newest appended), so we
        reverse a copy here. Safe to call without an instance.
        """
        history = cls._load_history()
        return list(reversed(history.get('games', [])))

    # --- In-progress session (resume) serialization ---

    def to_dict(self) -> dict:
        """Serialize the full in-progress game state to a JSON-safe dict.

        Scorekeepers are intentionally omitted: a session is only ever saved at
        a half-inning boundary (see GameDayTransitionState), where both
        scorekeepers have just been reset, so from_dict rebuilds them fresh.
        """
        return {
            'session_uuid': self.session_uuid,
            'player_name': self.player_name,
            'opponent_name': self.opponent_name,
            'difficulty': self.difficulty,
            # Core game state
            'current_inning': self.current_inning,
            'is_top_inning': self.is_top_inning,
            'player_score': self.player_score,
            'opponent_score': self.opponent_score,
            'game_over': self.game_over,
            'is_walkoff': self.is_walkoff,
            '_result_saved': self._result_saved,
            'player_inning_scores': list(self.player_inning_scores),
            'opponent_inning_scores': list(self.opponent_inning_scores),
            '_current_half_runs': self._current_half_runs,
            '_consecutive_hits': self._consecutive_hits,
            'player_consecutive_hits': self.player_consecutive_hits,
            'current_outs': self.current_outs,
            # Opponent staff (player bats against these)
            'opponent_pitcher_preset': self.opponent_pitcher_preset,
            'current_pitcher_name': self.current_pitcher_name,
            'available_opponent_relievers': list(self.available_opponent_relievers),
            'opponent_pitcher_stats': {
                name: ps.to_dict()
                for name, ps in self.opponent_pitcher_stats.items()
            },
            # Player staff (opponent bats against these)
            'player_pitcher_preset': self.player_pitcher_preset,
            'current_player_pitcher_name': self.current_player_pitcher_name,
            'available_player_relievers': list(self.available_player_relievers),
            'player_pitcher_innings_pitched': self.player_pitcher_innings_pitched,
            'player_pitcher_stats': {
                name: ps.to_dict()
                for name, ps in self.player_pitcher_stats.items()
            },
            # Lineup + log
            'opponent_lineup': list(self.opponent_lineup),
            'current_batter_index': self.current_batter_index,
            'event_log': [e.to_dict() for e in self.event_log],
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'GameDayManager':
        """Rebuild a GameDayManager from a to_dict() payload.

        Tolerant of roster drift: a saved pitcher no longer present in
        ALL_PITCHERS still loads (PitcherStats are keyed by name and the sim
        only needs the name + attrs), but the chosen starter falls back to a
        valid one if it has vanished, mirroring __init__.
        """
        preset = d.get('opponent_pitcher_preset') or {}
        mgr = cls(
            player_name=d.get('player_name', 'Player'),
            difficulty=d.get('difficulty', 'amateur'),
            starter_name=preset.get('starter', 'yamamoto'),
        )

        mgr.session_uuid = d.get('session_uuid', mgr.session_uuid)
        mgr.opponent_name = d.get('opponent_name', mgr.opponent_name)

        # Core game state
        mgr.current_inning = d['current_inning']
        mgr.is_top_inning = d['is_top_inning']
        mgr.player_score = d['player_score']
        mgr.opponent_score = d['opponent_score']
        mgr.game_over = d['game_over']
        mgr.is_walkoff = d['is_walkoff']
        mgr._result_saved = d.get('_result_saved', False)
        mgr.player_inning_scores = list(d.get('player_inning_scores', []))
        mgr.opponent_inning_scores = list(d.get('opponent_inning_scores', []))
        mgr._current_half_runs = d.get('_current_half_runs', 0)
        mgr._consecutive_hits = d.get('_consecutive_hits', 0)
        mgr.player_consecutive_hits = d.get('player_consecutive_hits', 0)
        mgr.current_outs = d.get('current_outs', 0)

        # Opponent staff
        if preset:
            mgr.opponent_pitcher_preset = preset
        mgr.current_pitcher_name = d['current_pitcher_name']
        mgr.available_opponent_relievers = list(d.get('available_opponent_relievers', []))
        mgr.opponent_pitcher_stats = {
            name: PitcherStats.from_dict(ps)
            for name, ps in d.get('opponent_pitcher_stats', {}).items()
        }

        # Player staff
        if d.get('player_pitcher_preset'):
            mgr.player_pitcher_preset = d['player_pitcher_preset']
        mgr.current_player_pitcher_name = d['current_player_pitcher_name']
        mgr.available_player_relievers = list(d.get('available_player_relievers', []))
        mgr.player_pitcher_innings_pitched = d.get('player_pitcher_innings_pitched', 0)
        mgr.player_pitcher_stats = {
            name: PitcherStats.from_dict(ps)
            for name, ps in d.get('player_pitcher_stats', {}).items()
        }

        # Defensive: guarantee the active pitchers always have a stats row so
        # get_active_*_pitcher_stats() can't KeyError on a partial/legacy payload.
        if mgr.current_pitcher_name not in mgr.opponent_pitcher_stats:
            mgr.opponent_pitcher_stats[mgr.current_pitcher_name] = \
                PitcherStats(mgr.current_pitcher_name)
        if mgr.current_player_pitcher_name not in mgr.player_pitcher_stats:
            mgr.player_pitcher_stats[mgr.current_player_pitcher_name] = \
                PitcherStats(mgr.current_player_pitcher_name)

        # Lineup + log
        if d.get('opponent_lineup'):
            mgr.opponent_lineup = list(d['opponent_lineup'])
        mgr.current_batter_index = d.get('current_batter_index', 0)
        mgr.event_log = [GameEvent.from_dict(e) for e in d.get('event_log', [])]

        return mgr
