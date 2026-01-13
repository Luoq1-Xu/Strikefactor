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
        
        # Data file path
        self.data_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'batting_stats.json')
        
        # Load existing data if available
        self.load_data()
        
    def set_strikezone_mode(self, mode):
        """Set the strike zone display mode (1, 2, 3, 4, or 5)."""
        if 1 <= mode <= 5:
            self.strikezonedrawn = mode
    
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
    
    def record_hit(self, x, y):
        """Record a hit at the given position."""
        segment = self.get_zone_segment(x, y)
        # print(f"Recording HIT at ({x:.1f}, {y:.1f}) -> segment {segment}")
        if 0 <= segment <= 8:
            self.heatmap_data[segment] += 1
            self.total_hits += 1
            # print(f"✓ Hit recorded! Segment {segment} now has {self.heatmap_data[segment]} hits / {self.heatmap_attempts[segment]} attempts")
            
            # Auto-save data after each hit
            self.save_data()
    
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
        
        # Save the reset state
        self.save_data()
        print("✓ All batting statistics have been reset")
    
    def add_test_heatmap_data(self):
        """Add test data for heatmap visualization."""
        # Add realistic batting average test data (hits per segment)
        # These should show varying performance levels across the zone
        self.heatmap_data = [2, 8, 1, 6, 12, 3, 1, 4, 2]      # hits per segment  
        self.heatmap_attempts = [20, 25, 18, 30, 35, 28, 15, 22, 17]  # attempts per segment
        # This gives batting averages of: [0.10, 0.32, 0.06, 0.20, 0.34, 0.11, 0.07, 0.18, 0.12]
        # Should show: blue, red, blue, white, red, blue, blue, blue/white, blue
        
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
                'last_updated': datetime.now().isoformat(),
                'version': '1.0'
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
                
                print(f"✓ Batting statistics loaded from {self.data_file}")
                print(f"  Total pitches: {self.total_pitches}, Total swings: {self.total_swings}, Total hits: {self.total_hits}")
                
                # Display overall batting average if we have data
                if self.total_swings > 0:
                    overall_avg = self.total_hits / self.total_swings
                    print(f"  Overall batting average: {overall_avg:.3f}")
                    
            else:
                print("No saved batting statistics found. Starting fresh.")
                
        except Exception as e:
            print(f"✗ Error loading batting statistics: {e}")
            print("Starting with fresh data.")
            
    def get_overall_batting_average(self):
        """Get overall batting average across all zones."""
        if self.total_swings == 0:
            return 0.0
        return self.total_hits / self.total_swings
        
    def get_batting_statistics(self):
        """Get comprehensive batting statistics."""
        stats = {
            'overall_average': self.get_overall_batting_average(),
            'total_pitches': self.total_pitches,
            'total_swings': self.total_swings,
            'total_hits': self.total_hits,
            'swing_percentage': self.total_swings / max(self.total_pitches, 1),
            'zone_averages': []
        }
        
        # Calculate per-zone averages
        for i in range(9):
            if self.heatmap_attempts[i] > 0:
                avg = self.heatmap_data[i] / self.heatmap_attempts[i]
            else:
                avg = 0.0
            stats['zone_averages'].append({
                'zone': i,
                'average': avg,
                'hits': self.heatmap_data[i],
                'attempts': self.heatmap_attempts[i]
            })
            
        return stats