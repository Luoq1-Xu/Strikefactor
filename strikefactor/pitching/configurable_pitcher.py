"""
Enhanced pitcher class that uses the configurable pitch system.
Provides situational awareness and realistic pitch selection.
"""

import pygame
import sys
import os
from typing import Dict, Any, List

# Add the parent directory to the path to allow absolute imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pitchers.pitcher import Pitcher
from pitching.pitch_config import pitch_system, PitchConfig, PitchLocation


class ConfigurablePitcher(Pitcher):
    """Pitcher that uses the configurable pitch system instead of hardcoded values."""
    
    def __init__(self, screen, loadfunc, name: str, windup_time: int = 1100):
        super().__init__(
            (screen.get_width() / 2) - 30,
            (screen.get_height() / 3) + 175,
            pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183),
            screen,
            name,
            windup_time
        )
        
        # Store reference to game for situation awareness
        self.game = None
        
        # Available pitch types for this pitcher (customize per pitcher)
        self.available_pitches: List[str] = []
        
        # Pitcher-specific adjustments to base configurations
        self.pitch_adjustments: Dict[str, Dict[str, float]] = {}
    
    def set_game_reference(self, game):
        """Set reference to game object for situation awareness."""
        self.game = game
        
    def add_configurable_pitch(self, pitch_type: str, adjustments: Dict[str, float] = None):
        """
        Add a configurable pitch type to this pitcher's arsenal.
        
        Args:
            pitch_type: The pitch type abbreviation (e.g., 'FF', 'SL', 'CB')
            adjustments: Optional adjustments to base config (e.g., {'velocity_modifier': 1.1})
        """
        if pitch_type not in pitch_system.get_available_pitches():
            raise ValueError(f"Unknown pitch type: {pitch_type}")
            
        self.available_pitches.append(pitch_type)
        if adjustments:
            self.pitch_adjustments[pitch_type] = adjustments
            
        # Create and register the pitch function
        pitch_func = self._create_configurable_pitch_function(pitch_type)
        self.add_pitch_type(pitch_func, pitch_type)
    
    def _create_configurable_pitch_function(self, pitch_type: str):
        """Create a pitch function that uses the configuration system."""
        def pitch_function(main_simulation):
            # Get current game situation
            situation = self._get_current_situation()
            
            # Get base parameters from config system
            ax, ay, vx, vy, travel_time = pitch_system.get_pitch_parameters(pitch_type, situation)
            
            # Apply pitcher-specific adjustments
            if pitch_type in self.pitch_adjustments:
                adjustments = self.pitch_adjustments[pitch_type]
                
                # Adjust movement
                ax *= adjustments.get('horizontal_modifier', 1.0)
                ay *= adjustments.get('vertical_modifier', 1.0)
                
                # Adjust velocity/timing
                travel_time = int(travel_time * adjustments.get('velocity_modifier', 1.0))
                
                # Adjust location
                vx += adjustments.get('location_x_bias', 0.0)
                vy += adjustments.get('location_y_bias', 0.0)
            
            # Call original simulation
            main_simulation(self.release_point, self.name, ax, ay, vx, vy, travel_time, pitch_type)
        
        return pitch_function
    
    def _get_current_situation(self) -> Dict[str, Any]:
        """Get current game situation for intelligent pitch selection."""
        if not self.game:
            return {'strikes': 0, 'balls': 0, 'outs': 0}
        
        return {
            'strikes': getattr(self.game, 'currentstrikes', 0),
            'balls': getattr(self.game, 'currentballs', 0), 
            'outs': getattr(self.game, 'currentouts', 0),
            'pitch_count': getattr(self.game, 'pitchnumber', 0),
            'last_pitch': getattr(self.game, 'last_pitch_type_thrown', None),
            'runners_on_base': self._get_runners_on_base(),
            'score_differential': self._get_score_differential(),
            'inning': getattr(self.game, 'currentinning', 1),
            'batter_handedness': self._get_batter_handedness()
        }
    
    def _get_runners_on_base(self) -> Dict[str, bool]:
        """Get current base runners."""
        if not self.game or not hasattr(self.game, 'scoreKeeper'):
            return {'first': False, 'second': False, 'third': False}
        
        return {
            'first': self.game.scoreKeeper.isRunnerOnBase(1),
            'second': self.game.scoreKeeper.isRunnerOnBase(2), 
            'third': self.game.scoreKeeper.isRunnerOnBase(3)
        }
    
    def _get_score_differential(self) -> int:
        """Get score differential (positive = pitcher's team ahead)."""
        if not self.game or not hasattr(self.game, 'scoreKeeper'):
            return 0
        
        score = self.game.scoreKeeper.get_score()
        # Handle case where score is an integer (legacy format) or dictionary
        if isinstance(score, dict):
            return score.get('away', 0) - score.get('home', 0)  # Assuming pitcher is home team
        else:
            return 0  # Return 0 for integer score format
    
    def _get_batter_handedness(self) -> str:
        """Get current batter's handedness."""
        if not self.game or not hasattr(self.game, 'batter'):
            return 'right'
        
        return self.game.batter.get_handedness()
    
    def get_pitch_recommendation(self, situation: Dict[str, Any] = None) -> str:
        """Get AI recommendation for next pitch based on situation."""
        if not situation:
            situation = self._get_current_situation()
        
        strikes = situation.get('strikes', 0)
        balls = situation.get('balls', 0)
        runners = situation.get('runners_on_base', {})
        
        # Simple situational logic (can be enhanced with AI)
        if balls >= 2 and strikes < 2:  # Behind in count - need strikes
            # Prefer strikes: fastball or cutter
            preferred = ['FF', 'FC', 'SI']
        elif strikes >= 2:  # Ahead in count - can be nasty
            # Can use breaking balls out of zone
            preferred = ['SL', 'CB', 'FS']
        elif any(runners.values()):  # Runners on base - vary approach
            # Mix of pitches, avoid walks
            preferred = ['FF', 'FC', 'SL']
        else:  # Even count or clean slate
            preferred = self.available_pitches
        
        # Filter to available pitches and return random selection
        available_preferred = [p for p in preferred if p in self.available_pitches]
        if not available_preferred:
            available_preferred = self.available_pitches
            
        import random
        return random.choice(available_preferred) if available_preferred else 'FF'


# Example: Create a modern Yamamoto using the configurable system
class ConfigurableYamamoto(ConfigurablePitcher):
    """Yamamoto implemented with the configurable pitch system."""
    
    def __init__(self, screen, loadfunc):
        super().__init__(screen, loadfunc, 'Yoshinobu Yamamoto', 1100)
        
        # Load sprites
        self.load_img(loadfunc, 'assets/images/yamamoto/', 14)
        
        # Add his pitch arsenal with specific adjustments
        self.add_configurable_pitch('FF', {
            'velocity_modifier': 1.05,  # Yamamoto throws hard
            'horizontal_modifier': 0.8,  # Less arm-side run
        })
        
        self.add_configurable_pitch('FS', {
            'vertical_modifier': 1.2,  # Extra drop on splitter
            'velocity_modifier': 0.95,
        })
        
        self.add_configurable_pitch('CB', {
            'vertical_modifier': 1.1,  # Sharp curve
            'horizontal_modifier': 0.9,
        })
        
        self.add_configurable_pitch('FC', {
            'horizontal_modifier': 1.1,  # Sharp cut
        })
        
        self.add_configurable_pitch('SL', {
            'velocity_modifier': 0.92,
            'horizontal_modifier': 1.05,
        })
        
        self.add_configurable_pitch('SI')  # Standard sinker
    
    def draw_pitcher(self, start_time, current_time):
        """Keep existing animation logic."""
        if current_time == 0 and start_time == 0:
            self.draw(self.screen, 1)
        if current_time <= start_time + 250:
            self.draw(self.screen, 1)
        elif current_time > start_time + 250 and current_time <= start_time + 350:
            self.draw(self.screen, 2, -6, 0)
        elif current_time > start_time + 350 and current_time <= start_time + 400:
            self.draw(self.screen, 3, -6, 0)
        elif current_time > start_time + 400 and current_time <= start_time + 550:
            self.draw(self.screen, 4, -13, -1)
        elif current_time > start_time + 550 and current_time <= start_time + 700:
            self.draw(self.screen, 5, -20, 1)
        elif current_time > start_time + 700 and current_time <= start_time + 800:
            self.draw(self.screen, 6, -26, 2)
        elif current_time > start_time + 800 and current_time <= start_time + 900:
            self.draw(self.screen, 7, -11, 3)
        elif current_time > start_time + 900 and current_time <= start_time + 975:
            self.draw(self.screen, 8, -3, 4)
        elif current_time > start_time + 975 and current_time <= start_time + 1000:
            self.draw(self.screen, 9, 8, 4)
        elif current_time > start_time + 1000 and current_time <= start_time + 1050:
            self.draw(self.screen, 10, 5, 4)
        elif current_time > start_time + 1050 and current_time <= start_time + 1100:
            self.draw(self.screen, 11, -8, 11)
        elif current_time > start_time + 1100 and current_time <= start_time + 1110:
            self.draw(self.screen, 12, -24, 1)
        elif current_time > start_time + 1110 and current_time <= start_time + 1120:
            self.draw(self.screen, 13, 5, 12)
        elif current_time > start_time + 1120:
            self.draw(self.screen, 14, -33, 19)