"""
Game State Manager for StrikeFactor.
Manages state transitions and coordinates between different game states.
"""

from typing import Dict, Optional

import pygame

from .game_states import (
    GameDayHistoryState,
    GameDayResumeState,
    GameDayState,
    GameDayTransitionState,
    GameplayState,
    GameState,
    InningEndState,
    MenuState,
    ModeSelectState,
    SandboxGameplayState,
    SandboxMenuState,
    SummaryState,
    VisualizationState,
)


class GameStateManager:
    """Manages game states and handles transitions between them."""

    # A double-click is two presses, and the first one may change the screen.
    # The second must not land on whatever now sits under the pointer: SETTINGS
    # on the main menu opens a screen with a button in the same place. So a
    # screen takes no click for this long after it appears. Long enough for
    # the second half of a double-click, too short to feel.
    CLICK_GUARD_MS = 300

    def __init__(self, game):
        self.game = game
        self.states: Dict[str, GameState] = {}
        self.current_state: Optional[GameState] = None
        self.current_state_name: str = ""
        self._clicks_from_ms = 0

        # Initialize all game states
        self._initialize_states()
        
    def _initialize_states(self):
        """Initialize all game states."""
        self.states = {
            'mode_select': ModeSelectState(self.game),
            'menu': MenuState(self.game),
            'sandbox_menu': SandboxMenuState(self.game),
            'sandbox_gameplay': SandboxGameplayState(self.game),
            'gameplay': GameplayState(self.game),
            'summary': SummaryState(self.game),
            'visualization': VisualizationState(self.game),
            'inning_end': InningEndState(self.game),
            'gameday': GameDayState(self.game),
            'gameday_transition': GameDayTransitionState(self.game),
            'gameday_resume': GameDayResumeState(self.game),
            'gameday_history': GameDayHistoryState(self.game)
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
        self.guard_clicks()

    def guard_clicks(self):
        """Start the click guard: a new screen has just appeared.

        `change_state` calls this. The settings and key-binding screens swap
        without a state change, so `Game` calls it for those.
        """
        self._clicks_from_ms = pygame.time.get_ticks() + self.CLICK_GUARD_MS

    def get_current_state(self) -> Optional[GameState]:
        """Get the current active state."""
        return self.current_state
        
    def update(self, time_delta: float):
        """Update the current state."""
        if self.current_state:
            self.current_state.update(time_delta)
            
    def handle_event(self, event):
        """Pass events to the current state."""
        if (event.type == pygame.MOUSEBUTTONDOWN
                and pygame.time.get_ticks() < self._clicks_from_ms):
            return True
        if self.current_state:
            return self.current_state.handle_event(event)
        return True
        
    def render(self, screen):
        """Render the current state."""
        if self.current_state:
            self.current_state.render(screen)

    def render_overlay(self, screen):
        """Draw what the current state puts above the HUD."""
        if self.current_state:
            self.current_state.render_overlay(screen)

    def handle_menu_state_change(self, menu_state_value):
        """Handle legacy menu_state changes from the original code."""
        if menu_state_value == 0:
            self.change_state('menu')
        elif menu_state_value == 'mode_select':
            self.change_state('mode_select')
        elif menu_state_value in ('sandbox', 'sandbox_menu'):
            self.change_state('sandbox_menu')
        elif menu_state_value == 100:
            self.change_state('summary')
        elif menu_state_value == 'visualise':
            self.change_state('visualization')
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