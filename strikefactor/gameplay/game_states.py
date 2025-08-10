"""
Game state classes for StrikeFactor baseball simulator.
Each state handles its own rendering, input processing, and state transitions.
"""

import pygame
import pygame_gui
import sys
from abc import ABC, abstractmethod
from typing import Optional


class GameState(ABC):
    """Abstract base class for all game states."""
    
    def __init__(self, game):
        self.game = game
        
    @abstractmethod
    def enter(self):
        """Called when entering this state."""
        pass
        
    @abstractmethod
    def exit(self):
        """Called when exiting this state."""
        pass
        
    @abstractmethod
    def update(self, time_delta: float):
        """Update state logic."""
        pass
        
    @abstractmethod
    def handle_event(self, event):
        """Handle pygame events."""
        pass
        
    @abstractmethod
    def render(self, screen):
        """Render the state."""
        pass


class MenuState(GameState):
    """Main menu state with pitcher selection and typing effect."""
    
    def __init__(self, game):
        super().__init__(game)
        self.messages = ["StrikeFactor", "A Baseball At-Bat Simulator"]
        self.active_message = 0
        self.counter = 0
        self.textoffset = 0
        self.messages_finished = 0
        self.done = False
        self.running = True
        
    def enter(self):
        """Initialize menu state."""
        self.game.ui_manager.hide_banner()
        self.game.scoreKeeper.reset()
        self.game.pitch_trajectories = []
        self.game.last_pitch_information = []
        self.game.ui_manager.set_button_visibility('main_menu')
        
        # Reset typing effect
        self.active_message = 0
        self.counter = 0
        self.textoffset = 0
        self.messages_finished = 0
        self.done = False
        self.running = True
        
    def exit(self):
        """Clean up menu state."""
        pass
        
    def update(self, time_delta: float):
        """Update typing effect and menu logic."""
        if not self.running:
            return
            
        message = self.messages[self.active_message]
        
        # Update typing effect
        if self.counter < self.game.speed * len(message):
            self.counter += 1
        elif self.counter >= self.game.speed * len(message):
            self.done = True
            
        # Handle message progression
        if (self.active_message < len(self.messages) - 1) and self.done:
            pygame.time.delay(500)
            self.active_message += 1
            self.done = False
            self.textoffset += 100
            self.counter = 0
            self.messages_finished += 1
            
    def handle_event(self, event):
        """Handle menu events."""
        self.game.ui_manager.process_events(event)
        if event.type == pygame.QUIT:
            return False
        return True
            
    def render(self, screen):
        """Render the main menu."""
        screen.fill("black")
        
        # Draw completed messages
        if self.messages_finished > 0:
            offset = 0
            for i in range(self.messages_finished):
                self.game.ui_manager.draw_completed_message(
                    self.messages[i], (300, 170 + offset), use_big_font=True
                )
                offset += 100
                
        # Draw current message with typing effect
        message = self.messages[self.active_message]
        self.game.ui_manager.draw_typing_effect(
            message, self.counter, self.game.speed, 
            (300, 170 + self.textoffset), use_big_font=True
        )


class GameplayState(GameState):
    """Main gameplay state where pitching and batting occur."""
    
    def __init__(self, game):
        super().__init__(game)
        self.pitch_simulation = None # Is in simulation state?
        
    def enter(self):
        """Initialize gameplay state."""
        self.game.ui_manager.set_button_visibility('in_game')
        self._refresh_display()
        
    def exit(self):
        """Clean up gameplay state."""
        self.pitch_simulation = None
        
    def _refresh_display(self):
        """Refresh the game display with current stats."""
        if self.game.just_refreshed == 1:
            result = (
                f"<font size=5>CURRENT OUTS : {self.game.currentouts}<br>"
                f"STRIKEOUTS : {self.game.currentstrikeouts}<br>"
                f"WALKS : {self.game.currentwalks}<br>"
                f"HITS : {self.game.hits}<br>"
                f"RUNS SCORED: {self.game.scoreKeeper.get_score()}</font>"
            )
            count_string = (
                f"<font size=5><br>COUNT IS "
                f"{self.game.currentballs} - {self.game.currentstrikes}</font>"
            )
            self.game.ui_manager.update_scoreboard(result)
            self.game.ui_manager.update_pitch_result(count_string)
            self.game.ui_manager.hide_banner()
            self.game.just_refreshed = 0
            self.game.current_gamemode = self.game.menu_state
            
    def update(self, time_delta: float):
        """Update gameplay logic."""
        if self.pitch_simulation and self.pitch_simulation.running:
            self.pitch_simulation.update()

        if self.pitch_simulation and not self.pitch_simulation.running:
            self.pitch_simulation = None
            self.game.ui_manager.set_button_visibility('in_game')
                
    def handle_event(self, event):
        """Handle gameplay events."""
        if event.type == pygame.QUIT:
            return False
            
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_q and not self.pitch_simulation:
                self._initiate_pitch()
                
        self.game.ui_manager.process_events(event)
        return True
        
    def _initiate_pitch(self):
        """Start a new pitch simulation."""
        self.game.first_pitch_thrown = True
        selection = self.game.current_pitcher.ai.choose_action(self.game.current_state)
        self.game.pitch_chosen = selection
        
        # This will be handled by the pitch simulation
        self.game.current_pitcher.pitch(self._create_pitch_simulation, selection)
        
    def _create_pitch_simulation(self, release_point, pitchername, ax, ay, vx, vy, traveltime, pitchtype):
        """Create and start a pitch simulation."""
        from .pitch_simulation import PitchSimulation
        self.pitch_simulation = PitchSimulation(
            self.game, release_point, pitchername, ax, ay, vx, vy, traveltime, pitchtype
        )
        self.pitch_simulation.run()
        
    def render(self, screen):
        """Render the gameplay state."""
        screen.fill("black")
        self.game.current_pitcher.draw_pitcher(0, 0)
        self.game.field_renderer.draw_strikezone()
        self.game.field_renderer.draw_field(self.game.scoreKeeper.get_bases())
        self.game.batter.draw_stance(1)
        
        # Draw pitch positions if in view mode
        if self.game.menu_state == 'view_pitches':
            for pitch_pos in self.game.pitches_display:
                pygame.gfxdraw.aacircle(
                    screen, int(pitch_pos[0]), int(pitch_pos[1]), 
                    self.game.fourseamballsize, (255, 255, 255)
                )
                
        # Draw current ball position
        if self.game.first_pitch_thrown:
            pygame.gfxdraw.aacircle(
                screen, int(self.game.ball[0]), int(self.game.ball[1]), 
                self.game.fourseamballsize, (255, 255, 255)
            )


class SummaryState(GameState):
    """End of inning summary state."""
    
    def __init__(self, game):
        super().__init__(game)
        self.messages = []
        self.active_message = 0
        self.counter = 0
        self.textoffset = 0
        self.messages_finished = 0
        self.done = False
        self.running = True
        self.stats_updated = False
        
    def enter(self):
        """Initialize summary state."""
        self._generate_summary_messages()
        if not self.stats_updated:
            self._update_pitcher_stats()
            self.stats_updated = True
        self.game.ui_manager.set_button_visibility('summary')
        self.game.scoreKeeper.reset()
        
        # Reset typing effect
        self.active_message = 0
        self.counter = 0
        self.textoffset = 0
        self.messages_finished = 0
        self.done = False
        self.running = True
        
    def exit(self):
        """Clean up summary state."""
        # Reset the flag so stats can be updated again for next inning
        self.stats_updated = False
        
    def _generate_summary_messages(self):
        """Generate summary messages based on game stats."""
        runs_scored = self.game.scoreKeeper.get_score()
        self.messages = [
            "INNING OVER",
            f"HITS : {self.game.hits}",
            f"WALKS: {self.game.currentwalks}",
            f"STRIKEOUTS : {self.game.currentstrikeouts}",
            f"RUNS SCORED : {runs_scored}"
        ]
        
    def _update_pitcher_stats(self):
        """Update pitcher statistics."""
        print("\n <--- INNING SUMMARY ---> \n")
        print(self.game.current_pitcher.name + " stats")
        
        stats_update = {
            'strikeouts': self.game.currentstrikeouts,
            'walks': self.game.currentwalks,
            'hits_allowed': self.game.hits,
            'outs': self.game.currentouts,
            'runs': self.game.scoreKeeper.get_score(),
            'pitch_count': self.game.current_pitches
        }
        
        basic_stats_update = {
            'strikes': self.game.strikes,
            'balls': self.game.balls,
            'strikeouts': self.game.currentstrikeouts,
            'walks': self.game.currentwalks,
            'hits_allowed': self.game.hits,
            'outs': self.game.currentouts,
            'runs_allowed': self.game.scoreKeeper.get_score(),
            'home_runs_allowed': self.game.homeruns_allowed,
            'pitch_count': self.game.current_pitches
        }
        
        self.game.current_pitcher.update_stats(stats_update)
        self.game.current_pitcher.update_basic_stats(basic_stats_update)
        self.game.current_pitcher.print_stats()
        print("\n <--- Accumulated Stats ---> \n")
        self.game.current_pitcher.print_basic_stats()
        print()
        
    def update(self, time_delta: float):
        """Update summary typing effect."""
        if not self.running or self.active_message >= len(self.messages):
            return
            
        message = self.messages[self.active_message]
        
        # Update typing effect
        if self.counter < self.game.speed * len(message):
            self.counter += 1
        elif self.counter >= self.game.speed * len(message):
            self.done = True
            
        # Handle message progression
        if (self.active_message < len(self.messages) - 1) and self.done:
            pygame.time.delay(500)
            self.active_message += 1
            self.done = False
            self.textoffset += 70
            self.counter = 0
            self.messages_finished += 1
            
    def handle_event(self, event):
        """Handle summary events."""
        self.game.ui_manager.process_events(event)
        if event.type == pygame.QUIT:
            return False
        return True
            
    def render(self, screen):
        """Render the summary screen."""
        screen.fill("black")
        
        # Draw completed messages
        if self.messages_finished > 0:
            offset = 0
            for i in range(self.messages_finished):
                self.game.ui_manager.draw_completed_message(
                    self.messages[i], (350, 170 + offset), use_big_font=False
                )
                offset += 70
                
        # Draw current message with typing effect
        if self.active_message < len(self.messages):
            message = self.messages[self.active_message]
            self.game.ui_manager.draw_typing_effect(
                message, self.counter, self.game.speed,
                (350, 170 + self.textoffset), use_big_font=False
            )


class VisualizationState(GameState):
    """State for visualizing pitch trajectories."""
    
    def __init__(self, game):
        super().__init__(game)
        self.current_frame = 0
        self.last_time = 0
        self.running = True
        
    def enter(self):
        """Initialize visualization state."""
        self.game.ui_manager.set_button_visibility('visualise')
        self.current_frame = 0
        self.last_time = pygame.time.get_ticks()
        self.running = True
        
    def exit(self):
        """Clean up visualization state."""
        pass
        
    def update(self, time_delta: float):
        """Update visualization animation."""
        if not self.game.last_pitch_information:
            return
            
        current_time = pygame.time.get_ticks()
        time_elapsed = current_time - self.last_time
        
        if time_elapsed > 25 and self.current_frame <= len(self.game.last_pitch_information) - 1:
            self.current_frame += 1
            self.last_time = current_time
            
    def handle_event(self, event):
        """Handle visualization events."""
        if event.type == pygame.QUIT:
            return False
        self.game.ui_manager.process_events(event)
        return True
        
    def render(self, screen):
        """Render the pitch visualization."""
        screen.fill("black")
        
        if not self.game.last_pitch_information:
            return
            
        # Draw pitch trajectories up to current frame
        for pitch in self.game.pitch_trajectories:
            for i in range(min(self.current_frame, len(pitch))):
                if i < len(pitch):
                    pygame.draw.ellipse(
                        screen, pitch[i][3],
                        (int(pitch[i][0]), int(pitch[i][1]), 
                         int(pitch[i][2]), int(pitch[i][2]))
                    )
                else:
                    # Draw final position if we've run out of frames
                    pygame.draw.ellipse(
                        screen, pitch[-1][3],
                        (int(pitch[-1][0]), int(pitch[-1][1]), 
                         int(pitch[-1][2]), int(pitch[-1][2]))
                    )
                    
        self.game.field_renderer.draw_strikezone()
        self.game.field_renderer.draw_field(self.game.scoreKeeper.get_bases())
        self.game.batter.draw_stance(1)


class ViewPitchesState(GameState):
    """State for viewing pitch locations."""
    
    def __init__(self, game):
        super().__init__(game)
        
    def enter(self):
        """Initialize view pitches state."""
        self.game.ui_manager.set_button_visibility('view_pitches')
        self.game.ui_manager.update_pitch_info(
            self.game.pitch_trajectories, self.game.last_pitch_information
        )
        self.game.ui_manager.show_view_window()
        
    def exit(self):
        """Clean up view pitches state."""
        self.game.ui_manager.hide_view_window()
        
    def update(self, time_delta: float):
        """Update view pitches logic."""
        pass
        
    def handle_event(self, event):
        """Handle view pitches events."""
        self.game.ui_manager.process_events(event)
        if event.type == pygame.QUIT:
            return False
        return True
        
    def render(self, screen):
        """Render the view pitches state."""
        screen.fill("black")
        self.game.current_pitcher.draw_pitcher(0, 0)
        self.game.field_renderer.draw_strikezone()
        self.game.field_renderer.draw_field(self.game.scoreKeeper.get_bases())
        
        # Draw all pitch positions
        for pitch_pos in self.game.pitches_display:
            pygame.gfxdraw.aacircle(
                screen, int(pitch_pos[0]), int(pitch_pos[1]), 
                self.game.fourseamballsize, (255, 255, 255)
            )


class InningEndState(GameState):
    """State shown when inning ends (3 outs reached) - allows visualization before summary."""
    
    def __init__(self, game):
        super().__init__(game)
        
    def enter(self):
        """Initialize inning end state."""
        self.game.ui_manager.set_button_visibility('inning_end')
        # Keep current display showing the final pitch result
        
    def exit(self):
        """Clean up inning end state."""
        pass
        
    def update(self, time_delta: float):
        """Update inning end logic."""
        # No special update logic needed - just maintain display
        pass
        
    def handle_event(self, event):
        """Handle inning end events."""
        self.game.ui_manager.process_events(event)
        if event.type == pygame.QUIT:
            return False
        # Block pitching input (Q key) since inning is over
        if event.type == pygame.KEYDOWN and event.key == pygame.K_q:
            return True  # Consume the event without processing
        return True
        
    def render(self, screen):
        """Render the inning end state - same as gameplay but no new pitches allowed."""
        screen.fill("black")
        self.game.current_pitcher.draw_pitcher(0, 0)
        self.game.field_renderer.draw_strikezone()
        self.game.field_renderer.draw_field(self.game.scoreKeeper.get_bases())
        self.game.batter.draw_stance(1)
        
        # Draw current ball position (final position)
        if self.game.first_pitch_thrown:
            pygame.gfxdraw.aacircle(
                screen, int(self.game.ball[0]), int(self.game.ball[1]), 
                self.game.fourseamballsize, (255, 255, 255)
            )