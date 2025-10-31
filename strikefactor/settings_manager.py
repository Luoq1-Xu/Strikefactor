import json
import os
from enum import Enum
from config import get_path

class DifficultyLevel(Enum):
    ROOKIE = "rookie"
    AMATEUR = "amateur"
    PROFESSIONAL = "professional"
    ALL_STAR = "all_star"
    HALL_OF_FAME = "hall_of_fame"

class SettingsManager:
    def __init__(self):
        self.settings_file = get_path("settings.json")
        self.default_settings = {
            "difficulty": DifficultyLevel.AMATEUR.value,
            "umpire_sound": True,
            "master_volume": 1.0,
            "show_strikezone": True,
            "batter_handedness": "R",
            "display_mode": "windowed"  # "windowed" or "fullscreen"
        }
        self.current_settings = self.load_settings()

    def load_settings(self):
        """Load settings from file, create with defaults if doesn't exist."""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                # Ensure all default keys exist
                for key, value in self.default_settings.items():
                    if key not in settings:
                        settings[key] = value
                return settings
            else:
                return self.default_settings.copy()
        except (json.JSONDecodeError, FileNotFoundError):
            return self.default_settings.copy()

    def save_settings(self):
        """Save current settings to file."""
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            with open(self.settings_file, 'w') as f:
                json.dump(self.current_settings, f, indent=2)
        except Exception as e:
            print(f"Failed to save settings: {e}")

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
        """Get difficulty-specific game multipliers."""
        difficulty = self.get_difficulty()

        # Define difficulty multipliers that affect game mechanics
        multipliers = {
            DifficultyLevel.ROOKIE: {
                "contact_timing_window": 1.5,      # 50% larger timing window
                "power_timing_window": 1.3,        # 30% larger timing window
                "contact_zone_size": 1.4,          # 40% larger contact zone
                "out_probability_modifier": 0.7,   # 30% fewer outs
                "strike_zone_tolerance": 1.2,      # More forgiving strike zone
                "foul_ball_chance": 1.3            # More foul balls (second chances)
            },
            DifficultyLevel.AMATEUR: {
                "contact_timing_window": 1.0,      # Normal timing window
                "power_timing_window": 1.0,        # Normal timing window
                "contact_zone_size": 1.0,          # Normal contact zone
                "out_probability_modifier": 1.0,   # Normal out rates
                "strike_zone_tolerance": 1.0,      # Normal strike zone
                "foul_ball_chance": 1.0            # Normal foul ball rate
            },
            DifficultyLevel.PROFESSIONAL: {
                "contact_timing_window": 0.8,      # 20% smaller timing window
                "power_timing_window": 0.7,        # 30% smaller timing window
                "contact_zone_size": 0.9,          # 10% smaller contact zone
                "out_probability_modifier": 1.2,   # 20% more outs
                "strike_zone_tolerance": 0.9,      # Tighter strike zone
                "foul_ball_chance": 0.8            # Fewer foul balls
            },
            DifficultyLevel.ALL_STAR: {
                "contact_timing_window": 0.6,      # 40% smaller timing window
                "power_timing_window": 0.5,        # 50% smaller timing window
                "contact_zone_size": 0.8,          # 20% smaller contact zone
                "out_probability_modifier": 1.4,   # 40% more outs
                "strike_zone_tolerance": 0.8,      # Much tighter strike zone
                "foul_ball_chance": 0.7            # Fewer foul balls
            },
            DifficultyLevel.HALL_OF_FAME: {
                "contact_timing_window": 0.4,      # 60% smaller timing window
                "power_timing_window": 0.3,        # 70% smaller timing window
                "contact_zone_size": 0.7,          # 30% smaller contact zone
                "out_probability_modifier": 1.6,   # 60% more outs
                "strike_zone_tolerance": 0.7,      # Very tight strike zone
                "foul_ball_chance": 0.6            # Much fewer foul balls
            }
        }

        return multipliers.get(difficulty, multipliers[DifficultyLevel.AMATEUR])

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

    def reset_to_defaults(self):
        """Reset all settings to default values."""
        self.current_settings = self.default_settings.copy()
        self.save_settings()

    def get_all_settings(self):
        """Get all current settings."""
        return self.current_settings.copy()