import json
import os
from enum import Enum

from strikefactor.config import get_path
from strikefactor.utils.io import atomic_write_json


class DifficultyLevel(Enum):
    ROOKIE = "rookie"
    AMATEUR = "amateur"
    PROFESSIONAL = "professional"
    ALL_STAR = "all_star"
    HALL_OF_FAME = "hall_of_fame"

# Define difficulty multipliers that affect game mechanics.
#
# `aim_assist` is the fraction of the player's aim error that the
# in-swing adjustment removes before the bat is built — a hitter reads
# the ball late and adjusts the barrel's plane on the way to it, so the
# bat does not end up exactly where they set out to put it. Converted in
# `bat_contact.aim_at_pitch`, which caps the correction at
# `MAX_ASSIST_FT` so a genuinely bad guess still misses. Unlike the
# window and zone multipliers it moves the *bat* rather than widening
# its tolerance, so it lifts contact quality as well as hit-or-miss.
DIFFICULTY_MULTIPLIERS = {
    DifficultyLevel.ROOKIE: {
        "aim_assist": 0.85,                # Reads the ball best
        "contact_timing_window": 1.5,      # 50% larger timing window
        "power_timing_window": 1.3,        # 30% larger timing window
        "contact_zone_size": 1.4,          # 40% larger contact zone
        "out_probability_modifier": 0.7,   # 30% fewer outs
        "strike_zone_tolerance": 1.2,      # More forgiving strike zone
        "foul_ball_chance": 1.3            # More foul balls (second chances)
    },
    DifficultyLevel.AMATEUR: {
        "aim_assist": 0.65,                # Balanced in-swing adjustment
        "contact_timing_window": 1.0,      # Normal timing window
        "power_timing_window": 1.0,        # Normal timing window
        "contact_zone_size": 1.0,          # Normal contact zone
        "out_probability_modifier": 1.0,   # Normal out rates
        "strike_zone_tolerance": 1.0,      # Normal strike zone
        "foul_ball_chance": 1.0            # Normal foul ball rate
    },
    DifficultyLevel.PROFESSIONAL: {
        "aim_assist": 0.50,                # Half the aim error survives
        "contact_timing_window": 0.8,      # 20% smaller timing window
        "power_timing_window": 0.7,        # 30% smaller timing window
        "contact_zone_size": 0.9,          # 10% smaller contact zone
        "out_probability_modifier": 1.2,   # 20% more outs
        "strike_zone_tolerance": 0.9,      # Tighter strike zone
        "foul_ball_chance": 0.8            # Fewer foul balls
    },
    DifficultyLevel.ALL_STAR: {
        "aim_assist": 0.35,                # Little help reading the ball
        "contact_timing_window": 0.6,      # 40% smaller timing window
        "power_timing_window": 0.5,        # 50% smaller timing window
        "contact_zone_size": 0.8,          # 20% smaller contact zone
        "out_probability_modifier": 1.4,   # 40% more outs
        "strike_zone_tolerance": 0.8,      # Much tighter strike zone
        "foul_ball_chance": 0.7            # Fewer foul balls
    },
    DifficultyLevel.HALL_OF_FAME: {
        "aim_assist": 0.20,                # Almost no adjustment
        "contact_timing_window": 0.4,      # 60% smaller timing window
        "power_timing_window": 0.3,        # 70% smaller timing window
        "contact_zone_size": 0.7,          # 30% smaller contact zone
        "out_probability_modifier": 1.6,   # 60% more outs
        "strike_zone_tolerance": 0.7,      # Very tight strike zone
        "foul_ball_chance": 0.6            # Much fewer foul balls
    }
}


class SettingsManager:
    # FPS option constants
    DISPLAY_FPS_OPTIONS = [60, 120]
    ENGINE_FPS_OPTIONS = [60, 120]  # 60 is baseline for original physics

    HUD_MODES = ["legacy", "broadcast", "minimal"]

    def __init__(self):
        self.settings_file = get_path("settings.json")
        self.default_settings = {
            "difficulty": DifficultyLevel.AMATEUR.value,
            "umpire_sound": True,
            "master_volume": 1.0,
            "show_strikezone": True,
            "batter_handedness": "R",
            "display_mode": "windowed",  # "windowed" or "fullscreen"
            "display_fps": 60,           # Options: 60, 120
            "engine_fps": 60,            # Options: 60, 120 (60 = original physics)
            "abs_enabled": True,         # MLB-style ball/strike challenge system
            "foul_animation_enabled": True,  # Play the hit animation for foul balls
            "hud_mode": "legacy"         # "legacy" | "broadcast" | "minimal"
        }
        self.current_settings = self.load_settings()

    def load_settings(self):
        """Load settings from file, create with defaults if doesn't exist."""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                # Migrate legacy boolean minimal_hud → hud_mode string.
                if "hud_mode" not in settings:
                    settings["hud_mode"] = "minimal" if settings.get("minimal_hud") else "legacy"
                settings.pop("minimal_hud", None)
                # Ensure all default keys exist
                for key, value in self.default_settings.items():
                    if key not in settings:
                        settings[key] = value
                return settings
            else:
                return self.default_settings.copy()
        except (json.JSONDecodeError, FileNotFoundError) as e:
            if isinstance(e, json.JSONDecodeError):
                print(f"Warning: settings file {self.settings_file} is corrupt "
                      f"({e}); falling back to defaults.")
            return self.default_settings.copy()

    def save_settings(self):
        """Save current settings to file (atomically, so a mid-write crash
        can't truncate the file and silently reset all preferences)."""
        atomic_write_json(self.settings_file, self.current_settings)

    def get_setting(self, key):
        """Get a specific setting value."""
        return self.current_settings.get(key, self.default_settings.get(key))

    def set_setting(self, key, value):
        """Set a specific setting value."""
        if key in self.default_settings:
            self.current_settings[key] = value
            self.save_settings()

    def get_difficulty(self):
        """Get current difficulty as enum."""
        difficulty_str = self.get_setting("difficulty")
        try:
            return DifficultyLevel(difficulty_str)
        except ValueError:
            return DifficultyLevel.AMATEUR

    def set_difficulty(self, difficulty_level):
        """Set difficulty level."""
        if isinstance(difficulty_level, DifficultyLevel):
            self.set_setting("difficulty", difficulty_level.value)
        elif isinstance(difficulty_level, str):
            try:
                diff = DifficultyLevel(difficulty_level)
                self.set_setting("difficulty", diff.value)
            except ValueError:
                print(f"Invalid difficulty level: {difficulty_level}")

    def get_difficulty_multipliers(self):
        """Get difficulty-specific game multipliers.

        Reads `DIFFICULTY_MULTIPLIERS` rather than rebuilding it, so the table
        has exactly one definition. A second hand-written copy of the AMATEUR
        row lived in `HitOutcomeManager._get_difficulty_multipliers` as its
        no-settings fallback, and it silently went stale the moment
        `aim_assist` was added here — `resolve_aim` raised `KeyError` for any
        caller constructed without a `SettingsManager`. Returns a fresh dict:
        callers used to get one per call, and handing out the shared table
        would let one of them mutate every later reader's copy.
        """
        return dict(DIFFICULTY_MULTIPLIERS.get(
            self.get_difficulty(), DIFFICULTY_MULTIPLIERS[DifficultyLevel.AMATEUR]))

    def get_difficulty_description(self, difficulty_level=None):
        """Get human-readable description of difficulty level."""
        if difficulty_level is None:
            difficulty_level = self.get_difficulty()

        descriptions = {
            DifficultyLevel.ROOKIE: "Rookie: Larger timing windows",
            DifficultyLevel.AMATEUR: "Amateur: Balanced gameplay",
            DifficultyLevel.PROFESSIONAL: "Professional: Tighter timing",
            DifficultyLevel.ALL_STAR: "All-Star: Challenging timing",
            DifficultyLevel.HALL_OF_FAME: "Hall of Fame: Precise timing"
        }

        return descriptions.get(difficulty_level, descriptions[DifficultyLevel.AMATEUR])

    def get_display_fps(self):
        """Get display/render FPS setting."""
        fps = self.get_setting("display_fps")
        return fps if fps in self.DISPLAY_FPS_OPTIONS else 60

    def get_engine_fps(self):
        """Get engine/physics FPS setting."""
        fps = self.get_setting("engine_fps")
        return fps if fps in self.ENGINE_FPS_OPTIONS else 60

    def cycle_display_fps(self):
        """Cycle to next display FPS option."""
        current = self.get_display_fps()
        idx = self.DISPLAY_FPS_OPTIONS.index(current)
        next_fps = self.DISPLAY_FPS_OPTIONS[(idx + 1) % len(self.DISPLAY_FPS_OPTIONS)]
        self.set_setting("display_fps", next_fps)
        return next_fps

    def cycle_engine_fps(self):
        """Cycle to next engine FPS option."""
        current = self.get_engine_fps()
        idx = self.ENGINE_FPS_OPTIONS.index(current)
        next_fps = self.ENGINE_FPS_OPTIONS[(idx + 1) % len(self.ENGINE_FPS_OPTIONS)]
        self.set_setting("engine_fps", next_fps)
        return next_fps

    def get_hud_mode(self) -> str:
        """Return the current HUD mode, defaulting to legacy if invalid."""
        mode = self.get_setting("hud_mode")
        return mode if mode in self.HUD_MODES else "legacy"

    def cycle_hud_mode(self) -> str:
        """Advance to the next HUD mode in legacy → broadcast → minimal → legacy."""
        current = self.get_hud_mode()
        idx = self.HUD_MODES.index(current)
        next_mode = self.HUD_MODES[(idx + 1) % len(self.HUD_MODES)]
        self.set_setting("hud_mode", next_mode)
        return next_mode

    def reset_to_defaults(self):
        """Reset all settings to default values."""
        self.current_settings = self.default_settings.copy()
        self.save_settings()
