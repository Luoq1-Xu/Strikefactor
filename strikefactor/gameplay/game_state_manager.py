"""
Game State Manager for StrikeFactor.
Manages state transitions and coordinates between different game states.
"""

from typing import Dict, Optional
from .game_states import (
    GameState, MenuState, GameplayState, SummaryState, 
    VisualizationState, ViewPitchesState, InningEndState
)


class GameStateManager:
    """Manages game states and handles transitions between them."""
    
    def __init__(self, game):
        self.game = game
        self.states: Dict[str, GameState] = {}
        self.current_state: Optional[GameState] = None
        self.current_state_name: str = ""
        
        # Initialize all game states
        self._initialize_states()
        
    def _initialize_states(self):
        """Initialize all game states."""
        self.states = {
            'menu': MenuState(self.game),
            'gameplay': GameplayState(self.game),
            'summary': SummaryState(self.game),
            'visualization': VisualizationState(self.game),
            'view_pitches': ViewPitchesState(self.game),
            'inning_end': InningEndState(self.game)
        }
        
    def change_state(self, state_name: str):
        """Change to a new game state."""
        if state_name not in self.states:
            print(f"Warning: State '{state_name}' does not exist")
            return
            
        # Exit current state
        if self.current_state:
            self.current_state.exit()
            
        # Enter new state
        self.current_state = self.states[state_name]
        self.current_state_name = state_name
        self.current_state.enter()
        
    def get_current_state(self) -> Optional[GameState]:
        """Get the current active state."""
        return self.current_state
        
    def get_current_state_name(self) -> str:
        """Get the name of the current active state."""
        return self.current_state_name
        
    def update(self, time_delta: float):
        """Update the current state."""
        if self.current_state:
            self.current_state.update(time_delta)
            
    def handle_event(self, event):
        """Pass events to the current state."""
        if self.current_state:
            return self.current_state.handle_event(event)
        return True
        
    def render(self, screen):
        """Render the current state."""
        if self.current_state:
            self.current_state.render(screen)
            
    def handle_menu_state_change(self, menu_state_value):
        """Handle legacy menu_state changes from the original code."""
        if menu_state_value == 0:
            self.change_state('menu')
        elif menu_state_value == 100:
            self.change_state('summary')
        elif menu_state_value == 'visualise':
            self.change_state('visualization')
        elif menu_state_value == 'view_pitches':
            self.change_state('view_pitches')
        elif menu_state_value == 'inning_end':
            self.change_state('inning_end')
        elif isinstance(menu_state_value, str) and menu_state_value in ['Sale', 'Degrom', 'Yamamoto', 'Sasaki', 'Experimental']:
            self.change_state('gameplay')
        else:
            # Default to gameplay state for other values
            self.change_state('gameplay')
            
    def is_current_state(self, state_name: str) -> bool:
        """Check if the given state is currently active."""
        return self.current_state_name == state_name