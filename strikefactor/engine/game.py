import pygame
import sys
from config import FPS, SCREEN_WIDTH, SCREEN_HEIGHT

class GameEngine:
    def __init__(self):
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.running = True
        self.current_state = None
        self.states = {}
        
    def add_state(self, state_name, state):
        self.states[state_name] = state
        
    def change_state(self, state_name):
        if state_name in self.states:
            self.current_state = self.states[state_name]
        
    def run(self):
        while self.running:
            time_delta = self.clock.tick(FPS) / 1000.0
            
            # Process events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                if self.current_state:
                    self.current_state.process_event(event)
            
            # Update and render current state
            if self.current_state:
                self.current_state.update(time_delta)
                self.screen.fill("black")
                self.current_state.render(self.screen)
                
            pygame.display.flip()
            
        pygame.quit()
        sys.exit()


