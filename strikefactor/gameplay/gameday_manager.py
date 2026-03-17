"""
GameDay Manager - Handles full 9-inning game simulation logic.
Manages opponent at-bats, pitcher substitutions, and event logging.
"""

import json
import os
import random
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from helpers import ScoreKeeper


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
        runs_str = f" ({self.runs_scored} run{'s' if self.runs_scored != 1 else ''})" if self.runs_scored > 0 else ""
        return f"[{half} {self.inning}] {self.batter_name} - {self.result}{runs_str} (vs {self.pitcher_name})"


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
        if outcome in ['STRIKEOUT', 'FLYOUT', 'GROUNDOUT', 'LINEOUT']:
            self.outs_recorded += 1
            if outcome == 'STRIKEOUT':
                self.strikeouts += 1
        elif outcome in ['SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN']:
            self.hits_allowed += 1
        elif outcome == 'WALK':
            self.walks += 1

        self.runs_allowed += runs

    def get_innings_pitched(self) -> float:
        """Calculate innings pitched."""
        return self.outs_recorded / 3.0

    def get_summary(self) -> str:
        """Get a summary string of pitcher stats."""
        ip = self.get_innings_pitched()
        return (f"{self.name}: {ip:.1f} IP, {self.hits_allowed} H, "
                f"{self.runs_allowed} R, {self.strikeouts} K, "
                f"{self.walks} BB, {self.pitch_count} pitches")


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

    def __init__(self, player_name: str = "Player", difficulty: str = "amateur"):
        self.player_name = player_name
        self.opponent_name = "Opponent"
        self.difficulty = difficulty

        # Game state
        self.current_inning = 1
        self.is_top_inning = True  # True = opponent batting, False = player batting
        self.player_score = 0
        self.opponent_score = 0
        self.game_over = False

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

        # Opponent pitchers (player bats against these - actual game pitchers)
        self.opponent_pitcher_preset = {
            'starter': 'yamamoto',
            'relievers': ['sasaki', 'degrom', 'mcclanahan'],
            'pitch_count_thresholds': [90, 100, 110]  # More aggressive relief thresholds
        }
        self.current_pitcher_name = self.opponent_pitcher_preset['starter']
        self.opponent_pitcher_stats: Dict[str, PitcherStats] = {}
        self.opponent_pitcher_stats[self.current_pitcher_name] = PitcherStats(self.current_pitcher_name)
        self.opponent_pitcher_stats[self.current_pitcher_name].is_active = True
        self.available_opponent_relievers = self.opponent_pitcher_preset['relievers'].copy()

        # Player's team pitchers (opponent bats against these - simulated only)
        self.player_pitcher_preset = {
            'starters': ['yesavage', 'scherzer', 'snell'],
            'relievers': ['hoffman', 'lauer', 'vesia', 'chapman'],
            'relief_thresholds': [1, 2]  # Relievers pitch 1-2 innings max
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
        self.opponent_lineup = [
            "J. Smith", "A. Johnson", "M. Davis", "R. Wilson",
            "K. Brown", "T. Martinez", "C. Garcia", "D. Rodriguez", "S. Lee"
        ]
        self.current_batter_index = 0

    # --- Probability adjustment methods ---

    def _get_adjusted_probabilities(self, extra_hit_boost: float = 0.0) -> dict:
        """Get opponent outcome probabilities adjusted for difficulty and situational modifiers."""
        mods = self.DIFFICULTY_MODIFIERS.get(self.difficulty,
               self.DIFFICULTY_MODIFIERS['amateur'])

        probs = dict(self.BASE_OPPONENT_OUTCOMES)

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

        # Log mound visit event
        old_pitcher = self.current_pitcher_name
        mound_event = GameEvent(
            self.current_inning, self.is_top_inning,
            "", old_pitcher,
            f"MOUND VISIT - {old_pitcher.upper()} being relieved"
        )
        self.event_log.append(mound_event)

        # Set current pitcher as inactive
        self.opponent_pitcher_stats[self.current_pitcher_name].is_active = False

        # Choose a random reliever
        new_pitcher = random.choice(self.available_opponent_relievers)
        self.available_opponent_relievers.remove(new_pitcher)

        # Initialize stats for new pitcher
        self.current_pitcher_name = new_pitcher
        self.opponent_pitcher_stats[new_pitcher] = PitcherStats(new_pitcher)
        self.opponent_pitcher_stats[new_pitcher].is_active = True

        return new_pitcher

    def should_consider_player_relief_pitcher(self) -> bool:
        """Check if we should bring in a relief pitcher for player's team."""
        # Don't relieve if no relievers available
        if not self.available_player_relievers:
            return False

        stats = self.get_active_player_pitcher_stats()

        # For starters, consider relief after 5-6 innings
        # For relievers, consider relief after 1-2 innings
        is_reliever = self.current_player_pitcher_name in self.player_pitcher_preset['relievers']

        if is_reliever:
            # Relievers: 1-2 innings max
            if stats.get_innings_pitched() >= random.choice([1.0, 2.0]):
                return random.random() < 0.7  # 70% chance to change
        else:
            # Starters: 5-6 innings
            if stats.get_innings_pitched() >= random.choice([5.0, 6.0]):
                return random.random() < 0.6  # 60% chance to change

        return False

    def substitute_player_relief_pitcher(self) -> Optional[str]:
        """Substitute in a relief pitcher for player's team. Returns new pitcher name or None."""
        if not self.available_player_relievers:
            return None

        # Set current pitcher as inactive
        self.player_pitcher_stats[self.current_player_pitcher_name].is_active = False

        # Choose a random reliever
        new_pitcher = random.choice(self.available_player_relievers)
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
        # Simulate some pitches (3-6 per at-bat)
        pitches_thrown = random.randint(3, 6)
        for _ in range(pitches_thrown):
            pitcher_stats.record_pitch()

        # Process the outcome
        runs_scored = 0

        if outcome in ['STRIKEOUT', 'FLYOUT', 'GROUNDOUT', 'LINEOUT']:
            self.current_outs += 1
            pitcher_stats.record_outcome(outcome)
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
            hit_type = {'SINGLE': 1, 'DOUBLE': 2, 'TRIPLE': 3, 'HOME RUN': 4}[outcome]
            before_score = self.opponent_scorekeeper.get_score()
            self.opponent_scorekeeper.update_hit_event(hit_type)
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

        # Update player score (runs_scored is already added in check_inning_end)
        # DON'T add it again here

        # Track player momentum
        if outcome in ['SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN']:
            self.player_consecutive_hits += 1
        elif outcome in ['STRIKEOUT', 'FLYOUT', 'GROUNDOUT', 'LINEOUT']:
            self.player_consecutive_hits = 0
        # WALK doesn't reset streak

        # Check for outs
        if outcome in ['STRIKEOUT', 'FLYOUT', 'GROUNDOUT', 'LINEOUT']:
            self.current_outs += 1

    def end_half_inning(self):
        """End the current half inning and switch sides."""
        self.current_outs = 0
        self._consecutive_hits = 0

        if self.is_top_inning:
            # Top half ended, switch to bottom (player bats)
            self.opponent_inning_scores.append(self._current_half_runs)
            self._current_half_runs = 0
            self.is_top_inning = False
            self.opponent_scorekeeper.reset()

            # In baseball, if home team leads after top of 9th, bottom is not played
            if self.current_inning >= 9 and self.player_score > self.opponent_score:
                self.game_over = True
                return
        else:
            # Bottom half ended
            self.player_inning_scores.append(self._current_half_runs)
            self._current_half_runs = 0
            self.is_top_inning = True
            self.player_scorekeeper.reset()

            # Check if 9 innings are complete before incrementing
            if self.current_inning >= 9:
                self.game_over = True
            else:
                # Move to next inning
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

    def is_inning_over(self) -> bool:
        """Check if the current half-inning is over."""
        return self.current_outs >= 3

    # --- Display / summary methods ---

    def get_box_score_lines(self) -> dict:
        """Get inning-by-inning score arrays for box score display."""
        opp = self.opponent_inning_scores + [0] * (9 - len(self.opponent_inning_scores))
        plr = self.player_inning_scores + [0] * (9 - len(self.player_inning_scores))
        return {
            'opponent': opp[:9],
            'player': plr[:9],
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

    def get_pitcher_summary(self) -> str:
        """Get current pitcher info."""
        stats = self.get_active_pitcher_stats()
        return f"Pitching: {stats.name.upper()} ({stats.pitch_count} pitches)"

    def get_all_pitcher_stats(self) -> List[PitcherStats]:
        """Get stats for all pitchers who appeared in the game (both teams)."""
        all_stats = []
        all_stats.extend(self.opponent_pitcher_stats.values())
        all_stats.extend(self.player_pitcher_stats.values())
        return all_stats

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
        elif self.opponent_score > self.player_score:
            return self.opponent_name
        else:
            return "Tie"

    # --- Persistence methods ---

    def save_game_result(self):
        """Save the completed game result to gameday_history.json."""
        result_str = "WIN" if self.player_score > self.opponent_score else \
                     "LOSS" if self.opponent_score > self.player_score else "TIE"
        result = {
            'date': datetime.now().isoformat(),
            'player_score': self.player_score,
            'opponent_score': self.opponent_score,
            'result': result_str,
            'difficulty': self.difficulty,
            'player_inning_scores': self.player_inning_scores,
            'opponent_inning_scores': self.opponent_inning_scores,
            'opponent_starter': self.opponent_pitcher_preset['starter'],
        }

        history = self._load_history()
        history['games'].append(result)
        history['last_updated'] = datetime.now().isoformat()

        # Keep last 100 games
        if len(history['games']) > 100:
            history['games'] = history['games'][-100:]

        os.makedirs(os.path.dirname(self.HISTORY_FILE), exist_ok=True)
        with open(self.HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)

    @classmethod
    def _load_history(cls) -> dict:
        """Load game history from file."""
        try:
            if os.path.exists(cls.HISTORY_FILE):
                with open(cls.HISTORY_FILE, 'r') as f:
                    return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            pass
        return {'version': '1.0', 'games': [], 'last_updated': None}

    @classmethod
    def get_career_record(cls) -> dict:
        """Get win/loss/tie record from saved history."""
        history = cls._load_history()
        wins = sum(1 for g in history['games'] if g.get('result') == 'WIN')
        losses = sum(1 for g in history['games'] if g.get('result') == 'LOSS')
        ties = sum(1 for g in history['games'] if g.get('result') == 'TIE')
        return {'wins': wins, 'losses': losses, 'ties': ties, 'total': len(history['games'])}
