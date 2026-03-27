import pygame
import pygame.gfxdraw
import colorsys
import json
import os
from datetime import datetime

class FieldRenderer:
    """Renders the static components of the baseball field."""
    
    def __init__(self, screen, strikezone_rect=(565, 410, 130, 150)):
        """
        Initialize the field renderer.
        
        Args:
            screen: Pygame surface to draw on
            strikezone_rect: Rectangle defining the strike zone (x, y, width, height)
        """
        self.screen = screen
        self.strikezone = pygame.Rect(strikezone_rect)
        self.strikezonedrawn = 1  # 1: Hidden, 2: Outline only, 3: Grid, 4: Heatmap, 5: Heatmap with Averages
        
        # Heatmap data structure: 9 segments [top_left, top_center, top_right, mid_left, center, mid_right, bot_left, bot_center, bot_right]
        self.heatmap_data = [0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.heatmap_attempts = [0, 0, 0, 0, 0, 0, 0, 0, 0]
        
        # Additional batting statistics
        self.total_swings = 0
        self.total_hits = 0
        self.total_pitches = 0
        self.total_at_bats = 0  # At-bats: hits + outs + strikeouts (excludes walks, fouls)

        # Triple slash statistics fields (v1.2)
        self.total_singles = 0
        self.total_doubles = 0
        self.total_triples = 0
        self.total_home_runs = 0
        self.total_walks = 0
        self.total_hbp = 0  # Hit by pitch (not yet implemented in game)
        self.total_sacrifice_flies = 0  # Sacrifice flies (not yet implemented)

        # Data file path
        self.data_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'batting_stats.json')

        # Lap history file path
        self.lap_history_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'lap_history.json')
        self.lap_start_time = datetime.now()

        # Load existing data if available
        self.load_data()
        
    def toggle_strikezone_mode(self):
        """Cycle through strike zone display modes."""
        self.strikezonedrawn = self.strikezonedrawn + 1 if self.strikezonedrawn < 5 else 1
        return self.strikezonedrawn
    
    def draw_strikezone(self):
        """Draw the strike zone based on current mode."""
        if self.strikezonedrawn == 1:
            # Hidden, don't draw
            return
            
        # Draw strike zone outline
        pygame.draw.rect(self.screen, "white", self.strikezone, 1)
        
        # Draw strike zone grid lines
        if self.strikezonedrawn == 3:
            x, y, width, height = self.strikezone
            
            # Horizontal dividing lines (divide into thirds)
            pygame.draw.line(self.screen, "white", 
                            (x, y + (height/3)), 
                            (x + width, y + (height/3)))
            pygame.draw.line(self.screen, "white", 
                            (x, y + 2*(height/3)), 
                            (x + width, y + 2*(height/3)))
            
            # Vertical dividing lines (divide into thirds)
            pygame.draw.line(self.screen, "white", 
                            (x + (width/3), y), 
                            (x + (width/3), y + height))
            pygame.draw.line(self.screen, "white", 
                            (x + 2*(width/3), y), 
                            (x + 2*(width/3), y + height))
            
        # Draw heatmap
        elif self.strikezonedrawn == 4:
            self._draw_heatmap()
        
        # Draw heatmap with batting averages
        elif self.strikezonedrawn == 5:
            self._draw_heatmap_with_averages()
    
    def draw_homeplate(self):
        """Draw the home plate."""
        x, y = 565, 660
        pygame.draw.polygon(self.screen, "white", [
            (x, y),                  # Top left
            (x + 130, y),            # Top right
            (x + 130, y + 10),       # Middle right
            (x + 65, y + 25),        # Bottom
            (x, y + 10)              # Middle left
        ], 0)
    
    def draw_bases(self, bases_status):
        """
        Draw the bases with their current status.
        
        Args:
            bases_status: List of colors for the bases ['white'/'yellow', ...]
        """
        # Draw first base (bottom right)
        pygame.draw.polygon(self.screen, bases_status[0], [
            (1115, 585), (1140, 610), (1115, 635), (1090, 610)
        ], 0 if bases_status[0] == 'yellow' else 1)
        
        # Draw second base (top)
        pygame.draw.polygon(self.screen, bases_status[1], [
            (1080, 550), (1105, 575), (1080, 600), (1055, 575)
        ], 0 if bases_status[1] == 'yellow' else 1)
        
        # Draw third base (bottom left)
        pygame.draw.polygon(self.screen, bases_status[2], [
            (1045, 585), (1070, 610), (1045, 635), (1020, 610)
        ], 0 if bases_status[2] == 'yellow' else 1)
    
    def draw_field(self, bases_status):
        """
        Draw all static field components.
        
        Args:
            bases_status: List of colors for the bases ['white'/'yellow', ...]
        """
        self.draw_strikezone()
        self.draw_homeplate()
        self.draw_bases(bases_status)
    
    def get_zone_segment(self, x, y):
        """
        Get the zone segment (0-8) for a given position.
        9 segments layout (including center):
        0  1  2
        3  4  5  
        6  7  8
        """
        sx, sy, width, height = self.strikezone
        
        # Check if point is within strikezone
        if not (sx <= x <= sx + width and sy <= y <= sy + height):
            return -1  # Outside strikezone
            
        # Calculate relative position within strikezone (0.0 to 1.0)
        rel_x = (x - sx) / width
        rel_y = (y - sy) / height
        
        # Determine segment based on thirds, including center
        if rel_y <= 1/3:  # Top row
            if rel_x <= 1/3:
                return 0  # top_left
            elif rel_x <= 2/3:
                return 1  # top_center
            else:
                return 2  # top_right
        elif rel_y <= 2/3:  # Middle row (including center)
            if rel_x <= 1/3:
                return 3  # mid_left
            elif rel_x <= 2/3:
                return 4  # center
            else:
                return 5  # mid_right
        else:  # Bottom row
            if rel_x <= 1/3:
                return 6  # bot_left
            elif rel_x <= 2/3:
                return 7  # bot_center
            else:
                return 8  # bot_right
    
    def record_hit(self, x, y, hit_type=None):
        """
        Record a hit at the given position with type tracking.

        Args:
            x: X-coordinate of the hit
            y: Y-coordinate of the hit
            hit_type: Type of hit - can be 'SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN' or numeric 1-4
        """
        print(f">>> record_hit CALLED: x={x:.1f}, y={y:.1f}, hit_type='{hit_type}'", flush=True)

        segment = self.get_zone_segment(x, y)
        print(f"    segment={segment}", flush=True)

        # Record heatmap data only if within strike zone (segment 0-8)
        if 0 <= segment <= 8:
            self.heatmap_data[segment] += 1
            print(f"    Heatmap updated for segment {segment}", flush=True)
        else:
            print(f"    Hit outside strike zone - not added to heatmap", flush=True)

        # ALWAYS record the hit for overall batting statistics (regardless of zone)
        self.total_hits += 1

        # Track hit type breakdown
        if hit_type == 'SINGLE' or hit_type == 1:
            self.total_singles += 1
            print(f"✓ SINGLE recorded (total: {self.total_singles})", flush=True)
        elif hit_type == 'DOUBLE' or hit_type == 2:
            self.total_doubles += 1
            print(f"✓ DOUBLE recorded (total: {self.total_doubles})", flush=True)
        elif hit_type == 'TRIPLE' or hit_type == 3:
            self.total_triples += 1
            print(f"✓ TRIPLE recorded (total: {self.total_triples})", flush=True)
        elif hit_type == 'HOME RUN' or hit_type == 4:
            self.total_home_runs += 1
            print(f"✓ HOME RUN recorded (total: {self.total_home_runs})", flush=True)
        else:
            # Debug: Log unrecognized hit types
            print(f"⚠ Unknown hit_type: '{hit_type}' (type: {type(hit_type).__name__})", flush=True)

        # Debug: Print current triple slash after each hit
        print(f"  Triple Slash: {self.get_triple_slash_line()} | AB:{self.total_at_bats} H:{self.total_hits} (1B:{self.total_singles} 2B:{self.total_doubles} 3B:{self.total_triples} HR:{self.total_home_runs})", flush=True)

        # Auto-save data after each hit
        self.save_data()
        print(f"    ✓ Data saved successfully", flush=True)
    
    def record_attempt(self, x, y):
        """Record an attempt (swing) at the given position."""
        segment = self.get_zone_segment(x, y)
        # print(f"Recording ATTEMPT at ({x:.1f}, {y:.1f}) -> segment {segment}")
        if 0 <= segment <= 8:
            self.heatmap_attempts[segment] += 1
            self.total_swings += 1
            # print(f"✓ Attempt recorded! Segment {segment} now has {self.heatmap_attempts[segment]} attempts")
    
    def record_pitch(self):
        """Record that a pitch was thrown (for tracking total pitches)."""
        self.total_pitches += 1

    def record_walk(self):
        """
        Record a walk (base on balls).

        Note: Walks do NOT count as at-bats in baseball.
        """
        self.total_walks += 1
        print(f"✓ WALK recorded (total: {self.total_walks})")
        print(f"  OBP now includes walk: {self.get_triple_slash_line()}")

    def record_at_bat(self):
        """
        Record an official at-bat.

        In real baseball, at-bats include plate appearances that result in:
        - Hits (singles, doubles, triples, home runs)
        - Outs (flyouts, groundouts, lineouts, strikeouts)

        At-bats EXCLUDE:
        - Walks (base on balls)
        - Hit by pitch
        - Sacrifice flies/bunts
        - Catcher's interference
        """
        self.total_at_bats += 1

    def get_hit_rate(self, segment):
        """Get the hit rate for a segment (hits/attempts)."""
        if self.heatmap_attempts[segment] == 0:
            return 0.0
        return self.heatmap_data[segment] / self.heatmap_attempts[segment]
    
    def _get_heatmap_color(self, hit_rate):
        """Convert hit rate to a color (blue = cold/low, red = hot/high)."""
        if hit_rate == 0:
            return (80, 80, 80)  # Darker gray for no data
            
        # Normalize hit rate based on realistic baseball batting averages
        # Excellent: 0.400+ (red), Good: 0.300+ (orange/yellow), Average: 0.200+ (white), Poor: <0.200 (blue)
        # Scale the hit rate so that:
        # - 0.000-0.150 maps to blue (cold)
        # - 0.150-0.250 maps to white/neutral 
        # - 0.250-0.350+ maps to red (hot)
        
        if hit_rate <= 0.150:
            # Poor performance - blue range
            intensity = hit_rate / 0.150  # 0 to 1
            hue = 240 / 360  # Blue hue
            saturation = 0.7 + intensity * 0.2  # More saturated for worse performance
            value = 0.5 + intensity * 0.3
        elif hit_rate <= 0.250:
            # Average performance - transition from blue to white
            progress = (hit_rate - 0.150) / 0.100  # 0 to 1
            hue = (240 - progress * 240) / 360  # Blue to neutral
            saturation = 0.7 - progress * 0.5  # Less saturated towards white
            value = 0.7 + progress * 0.2
        else:
            # Good to excellent performance - red range
            # Cap at 0.400 for scaling (anything above is exceptional)
            capped_rate = min(hit_rate, 0.400)
            progress = (capped_rate - 0.250) / 0.150  # 0 to 1
            hue = 0  # Red hue
            saturation = 0.6 + progress * 0.3  # More saturated for better performance
            value = 0.7 + progress * 0.3  # Brighter for better performance
        
        rgb = colorsys.hsv_to_rgb(hue, saturation, value)
        return (int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255))
    
    def _draw_heatmap(self):
        """Draw the batting heatmap."""
        x, y, width, height = self.strikezone
        
        # Calculate segment dimensions
        segment_width = width // 3
        segment_height = height // 3
        
        # Draw each segment with its color
        segments = [
            (0, 0, 0),      # top_left
            (1, 1, 0),      # top_center  
            (2, 2, 0),      # top_right
            (3, 0, 1),      # mid_left
            (4, 1, 1),      # center
            (5, 2, 1),      # mid_right
            (6, 0, 2),      # bot_left
            (7, 1, 2),      # bot_center
            (8, 2, 2),      # bot_right
        ]
        
        for segment_id, col, row in segments:
            hit_rate = self.get_hit_rate(segment_id)
            color = self._get_heatmap_color(hit_rate)
            
            # Calculate segment rectangle
            seg_x = x + col * segment_width
            seg_y = y + row * segment_height
            
            # Fill the segment with the heatmap color
            segment_rect = pygame.Rect(seg_x, seg_y, segment_width, segment_height)
            pygame.draw.rect(self.screen, color, segment_rect)
            
            # Draw segment border
            pygame.draw.rect(self.screen, "white", segment_rect, 1)
            
        # Draw the overall strikezone border
        pygame.draw.rect(self.screen, "white", self.strikezone, 2)
        
        # Add a visual indicator that heatmap is active
        font = pygame.font.Font(None, 24)
        text = font.render("HEATMAP ON", True, (255, 255, 255))
        self.screen.blit(text, (self.strikezone.x, self.strikezone.y - 30))
    
    def _draw_heatmap_with_averages(self):
        """Draw the batting heatmap with numerical averages displayed."""
        x, y, width, height = self.strikezone
        
        # Calculate segment dimensions
        segment_width = width // 3
        segment_height = height // 3
        
        # Draw each segment with its color and batting average text
        segments = [
            (0, 0, 0),      # top_left
            (1, 1, 0),      # top_center  
            (2, 2, 0),      # top_right
            (3, 0, 1),      # mid_left
            (4, 1, 1),      # center
            (5, 2, 1),      # mid_right
            (6, 0, 2),      # bot_left
            (7, 1, 2),      # bot_center
            (8, 2, 2),      # bot_right
        ]
        
        # Font for displaying averages
        font = pygame.font.Font(None, 24)
        
        for segment_id, col, row in segments:
            hit_rate = self.get_hit_rate(segment_id)
            color = self._get_heatmap_color(hit_rate)
            
            # Calculate segment rectangle
            seg_x = x + col * segment_width
            seg_y = y + row * segment_height
            
            # Fill the segment with the heatmap color
            segment_rect = pygame.Rect(seg_x, seg_y, segment_width, segment_height)
            pygame.draw.rect(self.screen, color, segment_rect)
            
            # Draw segment border
            pygame.draw.rect(self.screen, "white", segment_rect, 1)
            
            # Display batting average text in the center of each segment
            if self.heatmap_attempts[segment_id] > 0:
                if hit_rate >= 1.0:
                    # For perfect (1.000) or above, show as "1.00" 
                    avg_text = f"{hit_rate:.2f}"
                else:
                    # For averages < 1.0, show as ".333" (remove leading zero)
                    avg_text = f"{hit_rate:.3f}"[1:]  # Remove leading '0'
                    if len(avg_text) > 4:  # If more than .XXX, truncate
                        avg_text = avg_text[:4]
            else:
                avg_text = "---"  # No data indicator
            
            # Render text
            text_surface = font.render(avg_text, True, (255, 255, 255))
            text_rect = text_surface.get_rect()
            
            # Center the text in the segment
            text_x = seg_x + (segment_width - text_rect.width) // 2
            text_y = seg_y + (segment_height - text_rect.height) // 2
            
            # Draw a semi-transparent background for better text readability
            bg_rect = pygame.Rect(text_x - 2, text_y - 1, text_rect.width + 4, text_rect.height + 2)
            bg_surface = pygame.Surface((bg_rect.width, bg_rect.height))
            bg_surface.set_alpha(128)  # 50% transparency
            bg_surface.fill((0, 0, 0))  # Black background
            self.screen.blit(bg_surface, bg_rect)
            
            # Draw the text
            self.screen.blit(text_surface, (text_x, text_y))
            
        # Draw the overall strikezone border
        pygame.draw.rect(self.screen, "white", self.strikezone, 2)
        
        # Add a visual indicator that heatmap with averages is active
        font = pygame.font.Font(None, 24)
        text = font.render("HEATMAP + AVERAGES", True, (255, 255, 255))
        self.screen.blit(text, (self.strikezone.x, self.strikezone.y - 30))
    
    def reset_heatmap_data(self):
        """Reset all heatmap data and batting statistics."""
        self.heatmap_data = [0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.heatmap_attempts = [0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.total_swings = 0
        self.total_hits = 0
        self.total_pitches = 0
        self.total_at_bats = 0

        # Reset triple slash fields
        self.total_singles = 0
        self.total_doubles = 0
        self.total_triples = 0
        self.total_home_runs = 0
        self.total_walks = 0
        self.total_hbp = 0
        self.total_sacrifice_flies = 0

        # Save the reset state
        self.save_data()
        print("✓ All batting statistics have been reset")
    
    def save_data(self):
        """Save heatmap and batting statistics to file."""
        try:
            # Ensure data directory exists
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)

            data = {
                'heatmap_data': self.heatmap_data,
                'heatmap_attempts': self.heatmap_attempts,
                'total_swings': self.total_swings,
                'total_hits': self.total_hits,
                'total_pitches': self.total_pitches,
                'total_at_bats': self.total_at_bats,
                # Triple slash statistics (v1.2)
                'total_singles': self.total_singles,
                'total_doubles': self.total_doubles,
                'total_triples': self.total_triples,
                'total_home_runs': self.total_home_runs,
                'total_walks': self.total_walks,
                'total_hbp': self.total_hbp,
                'total_sacrifice_flies': self.total_sacrifice_flies,
                'last_updated': datetime.now().isoformat(),
                'version': '1.2'  # Updated version
            }

            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2)

            # print(f"✓ Batting statistics saved to {self.data_file}")

        except Exception as e:
            print(f"✗ Error saving batting statistics: {e}")
            
    def load_data(self):
        """Load heatmap and batting statistics from file."""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    data = json.load(f)

                # Load heatmap data
                self.heatmap_data = data.get('heatmap_data', [0] * 9)
                self.heatmap_attempts = data.get('heatmap_attempts', [0] * 9)

                # Load batting statistics
                self.total_swings = data.get('total_swings', 0)
                self.total_hits = data.get('total_hits', 0)
                self.total_pitches = data.get('total_pitches', 0)
                self.total_at_bats = data.get('total_at_bats', 0)

                # Load v1.2 fields (triple slash statistics)
                self.total_singles = data.get('total_singles', 0)
                self.total_doubles = data.get('total_doubles', 0)
                self.total_triples = data.get('total_triples', 0)
                self.total_home_runs = data.get('total_home_runs', 0)
                self.total_walks = data.get('total_walks', 0)
                self.total_hbp = data.get('total_hbp', 0)
                self.total_sacrifice_flies = data.get('total_sacrifice_flies', 0)

                # Data validation and migration
                version = data.get('version', '1.0')
                if version == '1.1':
                    print("  Migrating data from v1.1 to v1.2...")

                # Validate data integrity
                expected_hits = (self.total_singles + self.total_doubles +
                                 self.total_triples + self.total_home_runs)
                if expected_hits > 0 and expected_hits != self.total_hits:
                    print(f"  ⚠ Warning: Hit count mismatch. Expected {expected_hits}, got {self.total_hits}. Recalculating.")
                    self.total_hits = expected_hits
                    self.save_data()  # Save corrected data

                print(f"✓ Batting statistics loaded from {self.data_file}")
                print(f"  Total pitches: {self.total_pitches}, Total at-bats: {self.total_at_bats}, Total hits: {self.total_hits}")

                # Display overall batting average if we have data (BA = H / AB)
                if self.total_at_bats > 0:
                    overall_avg = self.total_hits / self.total_at_bats
                    print(f"  Overall batting average: {overall_avg:.3f}")

            else:
                print("No saved batting statistics found. Starting fresh.")

        except Exception as e:
            print(f"✗ Error loading batting statistics: {e}")
            print("Starting with fresh data.")
            
    def get_overall_batting_average(self):
        """
        Get overall batting average across all zones.

        Batting average (BA) = Hits / At-Bats
        - Hits: singles, doubles, triples, home runs
        - At-Bats: excludes walks, hit-by-pitch, sacrifice flies/bunts
        """
        if self.total_at_bats == 0:
            return 0.0
        return self.total_hits / self.total_at_bats

    def get_on_base_percentage(self):
        """
        Calculate On-Base Percentage (OBP).

        OBP = (H + BB + HBP) / (AB + BB + HBP + SF)
        - H: Hits
        - BB: Walks (Base on Balls)
        - HBP: Hit By Pitch
        - AB: At-Bats
        - SF: Sacrifice Flies
        """
        numerator = self.total_hits + self.total_walks + self.total_hbp
        denominator = (self.total_at_bats + self.total_walks +
                       self.total_hbp + self.total_sacrifice_flies)

        if denominator == 0:
            return 0.0
        return numerator / denominator

    def get_slugging_percentage(self):
        """
        Calculate Slugging Percentage (SLG).

        SLG = Total Bases / At-Bats
        Total Bases = (1B × 1) + (2B × 2) + (3B × 3) + (HR × 4)
        """
        if self.total_at_bats == 0:
            return 0.0

        total_bases = (
            self.total_singles * 1 +
            self.total_doubles * 2 +
            self.total_triples * 3 +
            self.total_home_runs * 4
        )
        return total_bases / self.total_at_bats

    def get_ops(self):
        """
        Calculate OPS (On-Base Plus Slugging).

        OPS = OBP + SLG
        """
        return self.get_on_base_percentage() + self.get_slugging_percentage()

    def get_triple_slash_line(self):
        """
        Get the triple slash line as a formatted string.

        Returns:
            str: Formatted as ".AVG/.OBP/.SLG"
        """
        avg = self.get_overall_batting_average()
        obp = self.get_on_base_percentage()
        slg = self.get_slugging_percentage()

        # Format: Remove leading zero for values < 1.0, show 3 decimal places
        def format_stat(value):
            if value >= 1.0:
                return f"{value:.3f}"  # Show "1.000" for perfect
            return f"{value:.3f}"[1:]  # Remove leading 0 for ".333"

        return f"{format_stat(avg)}/{format_stat(obp)}/{format_stat(slg)}"

    # ==================== Lap Feature Methods ====================

    def has_stats_to_lap(self) -> bool:
        """
        Check if there are any stats to create a lap from.

        Returns:
            bool: True if there are stats worth saving
        """
        return (self.total_pitches > 0 or
                self.total_swings > 0 or
                sum(self.heatmap_attempts) > 0)

    def create_lap(self) -> dict:
        """
        Create a new lap entry from current session stats.
        Stores the current stats in lap history and resets current stats.

        Returns:
            dict: The created lap entry data
        """
        # Calculate batting average before creating lap
        batting_avg = self.get_overall_batting_average()

        # Calculate duration since last lap (or session start)
        lap_end_time = datetime.now()
        duration = (lap_end_time - self.lap_start_time).total_seconds()

        # Load existing lap history
        lap_history = self.load_lap_history()

        # Determine lap number
        lap_number = len(lap_history.get('laps', [])) + 1

        # Create lap entry
        lap_entry = {
            'lap_number': lap_number,
            'timestamp': lap_end_time.isoformat(),
            'heatmap_data': self.heatmap_data.copy(),
            'heatmap_attempts': self.heatmap_attempts.copy(),
            'total_swings': self.total_swings,
            'total_hits': self.total_hits,
            'total_pitches': self.total_pitches,
            'total_at_bats': self.total_at_bats,
            'batting_average': round(batting_avg, 3),
            'duration_seconds': duration,
            # Triple slash statistics (v1.2)
            'triple_slash': self.get_triple_slash_line(),
            'total_singles': self.total_singles,
            'total_doubles': self.total_doubles,
            'total_triples': self.total_triples,
            'total_home_runs': self.total_home_runs,
            'total_walks': self.total_walks,
            'on_base_percentage': round(self.get_on_base_percentage(), 3),
            'slugging_percentage': round(self.get_slugging_percentage(), 3),
            'ops': round(self.get_ops(), 3)
        }

        # Add to history
        if 'laps' not in lap_history:
            lap_history['laps'] = []
            lap_history['version'] = '1.0'
            lap_history['created_date'] = lap_end_time.isoformat()

        lap_history['laps'].append(lap_entry)
        lap_history['last_updated'] = lap_end_time.isoformat()

        # Enforce max history limit (100 laps)
        MAX_LAP_HISTORY = 100
        if len(lap_history['laps']) > MAX_LAP_HISTORY:
            lap_history['laps'] = lap_history['laps'][-MAX_LAP_HISTORY:]

        # Save lap history
        self.save_lap_history(lap_history)

        # Reset current stats (using existing method)
        self.reset_heatmap_data()

        # Reset lap timer
        self.lap_start_time = datetime.now()

        print(f"✓ Lap {lap_number} created: BA {batting_avg:.3f}, {self.total_hits} hits in {self.total_at_bats} ABs")

        return lap_entry

    def load_lap_history(self) -> dict:
        """
        Load lap history from file.

        Returns:
            dict: Lap history data or empty structure if file doesn't exist
        """
        try:
            if os.path.exists(self.lap_history_file):
                with open(self.lap_history_file, 'r') as f:
                    return json.load(f)
            else:
                return {
                    'version': '1.0',
                    'created_date': datetime.now().isoformat(),
                    'last_updated': datetime.now().isoformat(),
                    'laps': []
                }
        except Exception as e:
            print(f"✗ Error loading lap history: {e}")
            return {'version': '1.0', 'laps': []}

    def save_lap_history(self, lap_history: dict):
        """
        Save lap history to file.

        Args:
            lap_history: The lap history data to save
        """
        try:
            os.makedirs(os.path.dirname(self.lap_history_file), exist_ok=True)
            with open(self.lap_history_file, 'w') as f:
                json.dump(lap_history, f, indent=2)
            print(f"✓ Lap history saved to {self.lap_history_file}")
        except Exception as e:
            print(f"✗ Error saving lap history: {e}")

    def get_lap_history(self) -> list:
        """
        Get all lap entries.

        Returns:
            list: List of lap entry dictionaries
        """
        history = self.load_lap_history()
        return history.get('laps', [])

    def clear_lap_history(self):
        """Clear all lap history."""
        empty_history = {
            'version': '1.0',
            'created_date': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'laps': []
        }
        self.save_lap_history(empty_history)
        print("✓ Lap history cleared")