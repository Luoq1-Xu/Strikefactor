import pygame
import pygame.gfxdraw

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
        self.strikezonedrawn = 1  # 1: Hidden, 2: Outline only, 3: Grid
        
    def set_strikezone_mode(self, mode):
        """Set the strike zone display mode (1, 2, or 3)."""
        if 1 <= mode <= 3:
            self.strikezonedrawn = mode
    
    def toggle_strikezone_mode(self):
        """Cycle through strike zone display modes."""
        self.strikezonedrawn = self.strikezonedrawn + 1 if self.strikezonedrawn < 3 else 1
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