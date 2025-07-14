import pygame
import pygame_gui


class GameState:
    def __init__(self, game_engine):
        self.game_engine = game_engine
        
    def process_event(self, event):
        pass
        
    def update(self, time_delta):
        pass
        
    def render(self, screen):
        pass
        
    def enter(self):
        pass
        
    def exit(self):
        pass

class MainMenuState(GameState):
    def __init__(self, game_engine, manager):
        super().__init__(game_engine)
        self.manager = manager
        # Initialize menu buttons and text
        
    def process_event(self, event):
        self.manager.process_events(event)
        # Handle menu button clicks
        
    def update(self, time_delta):
        self.manager.update(time_delta)
        
    def render(self, screen):
        # Draw menu background and buttons
        self.manager.draw_ui(screen)