"""
Configurable pitch system for realistic baseball pitch simulation.
Provides a data-driven approach to define pitch characteristics and location variance.
"""

import random
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass, field


@dataclass
class PitchMovement:
    """Defines the movement characteristics of a pitch."""
    # Base movement (acceleration in pixels/frame^2)
    horizontal_break: float  # Positive = toward right-handed batter
    vertical_break: float   # Positive = downward movement
    
    # Velocity characteristics
    base_velocity: float    # Base velocity modifier (affects travel time)
    velocity_variance: float = 0.02  # Random variance in velocity
    
    # Movement variance for realism
    break_variance: float = 0.003  # Random variance in break
    

@dataclass 
class PitchLocation:
    """Defines where a pitch can be located in the strike zone."""
    # Base target location (relative to strike zone center)
    target_x: float = 0.0  # -1.0 (inside) to 1.0 (outside) 
    target_y: float = 0.0  # -1.0 (high) to 1.0 (low)
    
    # Location variance
    x_variance: float = 0.3  # How much horizontal variance
    y_variance: float = 0.3  # How much vertical variance
    
    # Intent modifiers (for specific locations)
    inside_bias: float = 0.0   # Bias toward inside (-) or outside (+)
    vertical_bias: float = 0.0  # Bias toward high (-) or low (+)


@dataclass
class PitchConfig:
    """Complete configuration for a pitch type."""
    name: str
    abbreviation: str
    movement: PitchMovement
    locations: List[PitchLocation] = field(default_factory=list)
    base_travel_time: int = 400  # Base travel time in milliseconds
    
    def get_location_for_situation(self, situation: Dict[str, Any]) -> PitchLocation:
        """Get appropriate location based on game situation."""
        if not self.locations:
            return PitchLocation()
        
        # Enhanced situation-based location selection
        strikes = situation.get('strikes', 0)
        balls = situation.get('balls', 0)
        
        # Chase pitch situations (0-2, 1-2) - prioritize out-of-zone locations
        if strikes == 2 and balls <= 1:
            # Filter for chase pitches (high distance from center)
            chase_locations = [loc for loc in self.locations 
                             if abs(loc.target_x) > 0.3 or abs(loc.target_y) > 0.4]
            if chase_locations:
                # 70% chance for chase pitch, 30% competitive strike
                if random.random() < 0.70:
                    return random.choice(chase_locations)
            # Fallback to competitive strike
            return min(self.locations, key=lambda loc: abs(loc.target_x) + abs(loc.target_y))
        
        # Behind in count (2+ balls) - need competitive strikes
        elif balls >= 2 and strikes < 2:
            competitive_strikes = [loc for loc in self.locations 
                                 if abs(loc.target_x) <= 0.4 and abs(loc.target_y) <= 0.4]
            if competitive_strikes:
                return random.choice(competitive_strikes)
            return min(self.locations, key=lambda loc: abs(loc.target_x) + abs(loc.target_y))
        
        # Ahead in count (more strikes than balls, but not 0-2/1-2) - work edges
        elif strikes > balls:
            return max(self.locations, key=lambda loc: abs(loc.target_x) + abs(loc.target_y))
        
        # Even count or early count - mix of locations
        else:
            return random.choice(self.locations)


class PitchConfigSystem:
    """System for managing pitch configurations and generating realistic pitches."""
    
    # Strike zone dimensions in pixels (based on field renderer at 565, 410, 130, 150)
    STRIKE_ZONE_WIDTH = 130
    STRIKE_ZONE_HEIGHT = 150
    STRIKE_ZONE_CENTER_X = 630  # 565 + 130/2
    STRIKE_ZONE_CENTER_Y = 485  # 410 + 150/2
    
    def __init__(self):
        self.pitch_configs: Dict[str, PitchConfig] = {}
        self._initialize_default_configs()
    
    def _initialize_default_configs(self):
        """Initialize realistic pitch configurations based on real baseball physics."""
        
        # Four-seam Fastball - minimal movement, command locations
        self.register_pitch(PitchConfig(
            name="Four-Seam Fastball",
            abbreviation="FF",
            movement=PitchMovement(
                horizontal_break=-0.005, # Slight arm-side run
                vertical_break=0.005,    # Slight rise effect
                base_velocity=1.0,       # Fastest pitch
                velocity_variance=0.015,
                break_variance=0.001
            ),
            locations=[
                PitchLocation(0.0, -0.4, 0.25, 0.25),   # High strike (increased variance)
                PitchLocation(0.0, 0.4, 0.25, 0.25),    # Low strike (increased variance)
                PitchLocation(-0.4, 0.0, 0.3, 0.3),     # Inside (increased variance)
                PitchLocation(0.5, 0.0, 0.3, 0.3),      # Outside (increased variance)
                PitchLocation(0.0, 0.0, 0.35, 0.35),    # Middle-middle (increased variance)
                PitchLocation(0.0, -0.6, 0.25, 0.25),   # High (might be ball)
                PitchLocation(-0.6, -0.1, 0.2, 0.3),    # High inside (new)
                PitchLocation(0.7, 0.2, 0.2, 0.2),      # Outside corner (new)
                PitchLocation(0.2, 0.6, 0.25, 0.2),     # Low away (new)
                PitchLocation(-0.2, 0.5, 0.3, 0.25),    # Low inside (new)
            ],
            base_travel_time=380
        ))
        
        # Splitter - heavy downward movement
        self.register_pitch(PitchConfig(
            name="Splitter",
            abbreviation="FS", 
            movement=PitchMovement(
                horizontal_break=-0.008,  # Slight arm-side
                vertical_break=0.020,     # Heavy drop
                base_velocity=0.92,       # Slower than fastball
                velocity_variance=0.025,
                break_variance=0.004
            ),
            locations=[
                PitchLocation(0.0, 0.3, 0.35, 0.25),    # Low zone (increased variance)
                PitchLocation(0.2, 0.4, 0.3, 0.3),      # Low away (increased variance)
                PitchLocation(-0.2, 0.4, 0.3, 0.3),     # Low inside (increased variance)
                PitchLocation(0.0, 0.7, 0.35, 0.2),     # Below zone (chase)
                PitchLocation(0.4, 0.6, 0.25, 0.2),     # Low away chase (new)
                PitchLocation(-0.3, 0.5, 0.3, 0.25),    # Low inside chase (new)
                PitchLocation(0.1, 0.1, 0.4, 0.35),     # Middle-low (new)
            ],
            base_travel_time=410
        ))
        
        # Curveball - sharp downward and glove-side break
        self.register_pitch(PitchConfig(
            name="Curveball",
            abbreviation="CB",
            movement=PitchMovement(
                horizontal_break=0.002,   # Glove-side break
                vertical_break=0.025,     # Sharp drop
                base_velocity=0.75,       # Much slower
                velocity_variance=0.03,
                break_variance=0.006
            ),
            locations=[
                PitchLocation(0.0, 0.5, 0.25, 0.2),     # Low strike
                PitchLocation(0.3, 0.6, 0.2, 0.15),     # Low away (chase)
                PitchLocation(0.0, -0.2, 0.2, 0.25),    # High (show pitch)
            ],
            base_travel_time=500
        ))
        
        # Slider - tight break, firm
        self.register_pitch(PitchConfig(
            name="Slider", 
            abbreviation="SL",
            movement=PitchMovement(
                horizontal_break=0.008,   # Glove-side break
                vertical_break=0.015,     # Moderate drop
                base_velocity=0.92,       # Firm
                velocity_variance=0.02,
                break_variance=0.002      # Reduced variance for consistency
            ),
            locations=[
                PitchLocation(0.3, 0.2, 0.35, 0.35),    # Away (increased Y variance)
                PitchLocation(0.6, 0.1, 0.3, 0.4),      # Well off the plate away (increased Y)
                PitchLocation(0.0, 0.4, 0.3, 0.35),     # Low middle (increased Y variance)
                PitchLocation(-0.2, 0.1, 0.35, 0.4),    # Back foot (increased Y variance)
                PitchLocation(0.4, -0.1, 0.25, 0.45),   # High away (increased Y range)
                PitchLocation(0.8, 0.3, 0.2, 0.3),      # Chase pitch way outside (increased Y)
                PitchLocation(-0.1, 0.6, 0.4, 0.3),     # Low middle-in (increased Y)
                PitchLocation(0.2, 0.7, 0.3, 0.35),     # Below zone away (increased Y)
            ],
            base_travel_time=430
        ))
        
        # Cutter - late horizontal movement
        self.register_pitch(PitchConfig(
            name="Cutter",
            abbreviation="FC", 
            movement=PitchMovement(
                horizontal_break=0.003,   # Glove-side cut
                vertical_break=0.008,     # Slight drop
                base_velocity=0.95,       # Fast
                velocity_variance=0.018,
                break_variance=0.002
            ),
            locations=[
                PitchLocation(0.3, -0.1, 0.15, 0.2),    # Up and away
                PitchLocation(-0.3, 0.1, 0.2, 0.15),    # Inside (jam)
                PitchLocation(0.0, 0.0, 0.2, 0.2),      # Middle
            ],
            base_travel_time=400
        ))
        
        # Sinker - arm-side run and sink
        self.register_pitch(PitchConfig(
            name="Sinker",
            abbreviation="SI",
            movement=PitchMovement(
                horizontal_break=-0.008,  # Arm-side run
                vertical_break=0.012,     # Moderate sink
                base_velocity=0.96,       # Similar to fastball
                velocity_variance=0.02,
                break_variance=0.003
            ),
            locations=[
                PitchLocation(-0.2, 0.3, 0.2, 0.15),    # Arm-side low
                PitchLocation(0.1, 0.4, 0.15, 0.15),    # Away and down
                PitchLocation(0.0, 0.2, 0.2, 0.2),      # Low middle
            ],
            base_travel_time=390
        ))
        
        # Changeup - arm-side fade and sink, significant speed difference
        self.register_pitch(PitchConfig(
            name="Changeup",
            abbreviation="CH",
            movement=PitchMovement(
                horizontal_break=-0.010,  # Arm-side fade
                vertical_break=0.015,     # Sink
                base_velocity=0.90,       # Much slower than fastball
                velocity_variance=0.025,
                break_variance=0.003
            ),
            locations=[
                PitchLocation(-0.2, 0.2, 0.4, 0.3),     # Arm-side low (increased variance)
                PitchLocation(0.1, 0.3, 0.35, 0.25),    # Away and low (increased variance)
                PitchLocation(0.0, 0.1, 0.4, 0.35),     # Middle-low (increased variance)
                PitchLocation(-0.4, 0.3, 0.3, 0.25),    # Well inside (show pitch)
                PitchLocation(-0.3, -0.1, 0.3, 0.4),    # High arm-side (new location)
                PitchLocation(0.3, 0.5, 0.25, 0.2),     # Low away (new)
                PitchLocation(-0.6, 0.4, 0.2, 0.2),     # Way inside (chase pitch)
                PitchLocation(0.0, 0.6, 0.35, 0.15),    # Below zone middle (chase)
                PitchLocation(-0.1, -0.2, 0.4, 0.3),    # High middle-in (new)
            ],
            base_travel_time=480
        ))
    
    def register_pitch(self, config: PitchConfig):
        """Register a pitch configuration."""
        self.pitch_configs[config.abbreviation] = config
    
    def get_pitch_parameters(self, pitch_type: str, situation: Dict[str, Any] = None) -> Tuple[float, float, float, float, int]:
        """
        Generate pitch parameters based on configuration and situation.
        
        Returns:
            (ax, ay, vx, vy, travel_time) - Same format as original system
        """
        if pitch_type not in self.pitch_configs:
            raise ValueError(f"Unknown pitch type: {pitch_type}")
        
        config = self.pitch_configs[pitch_type]
        situation = situation or {}
        
        # Get movement with variance
        ax = config.movement.horizontal_break + random.uniform(
            -config.movement.break_variance, config.movement.break_variance)
        ay = config.movement.vertical_break + random.uniform(
            -config.movement.break_variance, config.movement.break_variance)
        
        # Get location
        location = config.get_location_for_situation(situation)
        
        # Calculate target position with variance  
        target_x = location.target_x + random.uniform(-location.x_variance, location.x_variance)
        target_y = location.target_y + random.uniform(-location.y_variance, location.y_variance)
        
        # Add count-aware variance to avoid perfect control and create realistic strike rates
        strikes = situation.get('strikes', 0)
        balls = situation.get('balls', 0)
        
        # Base wildness varies by count situation
        if strikes == 2 and balls <= 1:  # Two-strike counts - more intentional misses
            wildness_chance = 0.25  # 25% chance for chase pitches
            miss_magnitude = 0.4    # Larger misses for chase effect
        elif balls >= 2:  # Behind in count - less wildness, need strikes
            wildness_chance = 0.08  # 8% chance - better control needed
            miss_magnitude = 0.2    # Smaller misses
        else:  # Even counts or ahead - standard variance
            wildness_chance = 0.18  # 18% chance - realistic imperfection
            miss_magnitude = 0.3    # Standard miss size
            
        if random.random() < wildness_chance:
            target_x += random.uniform(-miss_magnitude, miss_magnitude)
            target_y += random.uniform(-miss_magnitude, miss_magnitude)
        
        # Apply location biases
        target_x += location.inside_bias
        target_y += location.vertical_bias
        
        # Convert to screen coordinates relative to strike zone center
        # Original system uses pixel offsets from center, typically -25 to +35 range
        vx = target_x * 25  # Scale to match original system range
        vy = target_y * 20  # Scale to match original system range 
        
        # Apply velocity variance
        velocity_modifier = config.movement.base_velocity * (
            1.0 + random.uniform(-config.movement.velocity_variance, config.movement.velocity_variance))
        
        # Adjust travel time based on velocity
        travel_time = int(config.base_travel_time / velocity_modifier)
        
        return ax, ay, vx, vy, travel_time
    
    def create_pitch_function(self, pitch_type: str):
        """Create a pitch function that uses the configuration system."""
        def pitch_function(main_simulation):
            # Get current game situation (you'll need to pass this somehow)
            situation = {
                'strikes': 0,  # You'd get this from game state
                'balls': 0,    # You'd get this from game state
                'outs': 0,     # etc.
            }
            
            ax, ay, vx, vy, travel_time = self.get_pitch_parameters(pitch_type, situation)
            
            # Call original simulation with generated parameters
            # Note: You'll need to get release_point and pitcher_name from somewhere
            main_simulation(None, 'ConfigurablePitcher', ax, ay, vx, vy, travel_time, pitch_type)
        
        return pitch_function
    
    def get_available_pitches(self) -> List[str]:
        """Get list of available pitch types."""
        return list(self.pitch_configs.keys())
    
    def get_pitch_info(self, pitch_type: str) -> PitchConfig:
        """Get configuration for a specific pitch type."""
        return self.pitch_configs.get(pitch_type)


# Global instance for easy access
pitch_system = PitchConfigSystem()