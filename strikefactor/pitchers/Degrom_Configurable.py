"""
Configurable deGrom implementation using the new pitch system.
Preserves existing animation and characteristics while adding intelligent pitching.
"""

import pygame
import sys
import os

# Add the parent directory to the path to allow absolute imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pitching.configurable_pitcher import ConfigurablePitcher


class DegromConfigurable(ConfigurablePitcher):
    """
    Jacob deGrom implemented with the configurable pitch system.
    Based on his real-life arsenal: Four-seam fastball, Slider, Changeup.
    """
    
    def __init__(self, screen, loadfunc):
        super().__init__(screen, loadfunc, 'Jacob deGrom', 1100)
        
        # Load deGrom's sprites (same as original)
        self.load_img(loadfunc, 'assets/images/degrom/RIGHTY', 9)
        
        # Set custom release point (same as original)
        self.release_point = pygame.Vector2((screen.get_width() / 2) - 45, (screen.get_height() / 3) + 187)
        
        # deGrom's pitch arsenal with realistic adjustments
        self._setup_pitch_arsenal()
    
    def _setup_pitch_arsenal(self):
        """Configure deGrom's pitch arsenal based on his real characteristics."""
        
        # deGrom's four-seam fastball - Elite velocity, good command
        # Multiple variations for different locations (FFU, FFM, FFD)
        self.add_configurable_pitch('FF', {
            'velocity_modifier': 1.10,      # deGrom throws 99+ mph
            'horizontal_modifier': 0.85,    # Less arm-side run (4-seam)
            'vertical_modifier': 0.8,       # Slight rise effect
            'location_x_bias': 0.1,         # Slightly prefers outside
        })
        
        # Map his specific fastball variations to the same FF type
        # This preserves the AI's ability to select different fastball locations
        self.add_pitch_type(self._fastball_up, "FFU")     # High fastball
        self.add_pitch_type(self._fastball_middle, "FFM") # Middle fastball  
        self.add_pitch_type(self._fastball_down, "FFD")   # Low fastball
        
        # deGrom's slider - His signature pitch, tight break
        self.add_configurable_pitch('SL', {
            'velocity_modifier': 0.8,      # ~89-93 mph
            'horizontal_modifier': 1.6,    # Sharp glove-side break
            'vertical_modifier': 1.9,       # Good downward movement
            'location_x_bias': 0.4,         # Prefers away to RHH
        })
        self.add_pitch_type(self._slider, "SLD")  # Map to original abbreviation
        
        # deGrom's changeup - Excellent pitch with fade and sink
        self.add_configurable_pitch('CH', {  # Using changeup type
            'velocity_modifier': 0.7,      # Fast changeup relative to average
            'horizontal_modifier': 1.2,     # Arm-side fade
            'vertical_modifier': 1.25,      # Good sink
            'location_x_bias': -0.2,        # Prefers arm-side
        })
        self.add_pitch_type(self._changeup, "CH")  # Map changeup function
    
    def _fastball_up(self, main_simulation):
        """High fastball using configurable system."""
        situation = self._get_current_situation()
        situation['target_location'] = 'high'
        ax, ay, vx, vy, travel_time = self._get_fastball_params(situation, location_bias=(0, -5))
        main_simulation(self.release_point, 'jacobdegrom', ax, ay, vx, vy, travel_time, 'FF')
    
    def _fastball_middle(self, main_simulation):
        """Middle fastball using configurable system."""
        situation = self._get_current_situation()
        situation['target_location'] = 'middle'
        ax, ay, vx, vy, travel_time = self._get_fastball_params(situation, location_bias=(10, 10))
        main_simulation(self.release_point, 'jacobdegrom', ax, ay, vx, vy, travel_time, 'FF')
    
    def _fastball_down(self, main_simulation):
        """Low fastball using configurable system."""
        situation = self._get_current_situation()
        situation['target_location'] = 'low'
        ax, ay, vx, vy, travel_time = self._get_fastball_params(situation, location_bias=(15, 22))
        main_simulation(self.release_point, 'jacobdegrom', ax, ay, vx, vy, travel_time, 'FF')
    
    def _slider(self, main_simulation):
        """Slider using configurable system."""
        situation = self._get_current_situation()
        ax, ay, vx, vy, travel_time = self._get_pitch_params('SL', situation)
        main_simulation(self.release_point, 'jacobdegrom', ax, ay, vx, vy, travel_time, 'SL')
    
    def _changeup(self, main_simulation):
        """Changeup using configurable system."""
        situation = self._get_current_situation()
        ax, ay, vx, vy, travel_time = self._get_pitch_params('CH', situation)
        main_simulation(self.release_point, 'jacobdegrom', ax, ay, vx, vy, travel_time, 'CH')
    
    def _get_fastball_params(self, situation, location_bias=(0, 0)):
        """Get fastball parameters with location bias."""
        ax, ay, vx, vy, travel_time = self._get_pitch_params('FF', situation)
        
        # Apply location bias for specific fastball types
        vx += location_bias[0]
        vy += location_bias[1]
        
        return ax, ay, vx, vy, travel_time
    
    def _get_pitch_params(self, pitch_type, situation):
        """Get pitch parameters from the configurable system."""
        from pitching.pitch_config import pitch_system
        return pitch_system.get_pitch_parameters(pitch_type, situation)
    
    def draw_pitcher(self, start_time, current_time):
        """
        Keep deGrom's exact animation timing (same as original).
        This preserves the visual experience while using the new pitch system.
        """
        if current_time == 0 and start_time == 0:
            self.draw(self.screen, 1)
        if current_time <= start_time + 300:
            self.draw(self.screen, 1)
        elif current_time > start_time + 300 and current_time <= start_time + 500:
            self.draw(self.screen, 2, -10, 0)
        elif current_time > start_time + 500 and current_time <= start_time + 700:
            self.draw(self.screen, 3, -13, 0)
        elif current_time > start_time + 700 and current_time <= start_time + 900:
            self.draw(self.screen, 4, -27, 5)
        elif current_time > start_time + 900 and current_time <= start_time + 1000:
            self.draw(self.screen, 5, -33, 12)
        elif current_time > start_time + 1000 and current_time <= start_time + 1100:
            self.draw(self.screen, 6, 12, 13)
        elif current_time > start_time + 1100 and current_time <= start_time + 1110:
            self.draw(self.screen, 7, -20, 7)
        elif current_time > start_time + 1110 and current_time <= start_time + 1140:
            self.draw(self.screen, 8, 0, 27)
        elif current_time > start_time + 1140:
            self.draw(self.screen, 9, -11, 25)


# For easy import compatibility
Degrom = DegromConfigurable  # Allow existing imports to work