"""
Game state classes for StrikeFactor baseball simulator.
Each state handles its own rendering, input processing, and state transitions.
"""

import pygame
import pygame.gfxdraw
import pygame_gui
from abc import ABC, abstractmethod
from typing import Optional
from gameplay.gameday_manager import GameDayManager


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


class ModeSelectState(GameState):
    """Top-level mode selection menu (Arcade/Sandbox)."""

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
        """Initialize mode select state."""
        self.game.ui_manager.hide_banner()
        self.game.ui_manager.set_button_visibility('mode_select')
        # Reset typing effect
        self.active_message = 0
        self.counter = 0
        self.textoffset = 0
        self.messages_finished = 0
        self.done = False
        self.running = True

    def exit(self):
        """Clean up mode select state."""
        pass

    def update(self, time_delta: float):
        """Update typing effect."""
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
        """Handle mode select events."""
        self.game.ui_manager.process_events(event)
        if event.type == pygame.QUIT:
            return False
        return True

    def render(self, screen):
        """Render the mode select screen."""
        screen.fill("black")

        # Draw completed messages
        if self.messages_finished > 0:
            offset = 0
            for i in range(self.messages_finished):
                self.game.ui_manager.draw_completed_message(
                    self.messages[i], (150, 170 + offset), use_big_font=True
                )
                offset += 100

        # Draw current message with typing effect
        message = self.messages[self.active_message]
        self.game.ui_manager.draw_typing_effect(
            message, self.counter, self.game.speed,
            (150, 170 + self.textoffset), use_big_font=True
        )


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

        # Set button visibility based on current menu state
        if self.game.menu_state == 'settings':
            self.game.ui_manager.set_button_visibility('settings')
            self.game.ui_manager.update_settings_button_states(self.game.settings_manager)
            self.game.ui_manager.show_settings_info(self.game.settings_manager)
        elif self.game.menu_state == 'key_bindings':
            self.game.ui_manager.set_button_visibility('key_bindings')
            self.game.ui_manager.update_key_binding_buttons(self.game.key_binding_manager)
            # Don't show banner for key bindings page
        else:
            self.game.ui_manager.set_button_visibility('main_menu')

            # Reset typing effect only for main menu
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

        # Only run typing effect for main menu, not settings or key bindings
        if self.game.menu_state not in ['settings', 'key_bindings']:
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

        # Only render typing effect for main menu, not settings or key bindings
        if self.game.menu_state not in ['settings', 'key_bindings']:
            # Draw completed messages
            if self.messages_finished > 0:
                offset = 0
                for i in range(self.messages_finished):
                    self.game.ui_manager.draw_completed_message(
                        self.messages[i], (100, 170 + offset), use_big_font=True
                    )
                    offset += 100

            # Draw current message with typing effect
            message = self.messages[self.active_message]
            self.game.ui_manager.draw_typing_effect(
                message, self.counter, self.game.speed,
                (100, 170 + self.textoffset), use_big_font=True
            )
        elif self.game.menu_state == 'settings':
            # For settings screen, just draw a simple title
            self.game.ui_manager.draw_completed_message(
                "SETTINGS", (540, 100), use_big_font=True
            )
        elif self.game.menu_state == 'key_bindings':
            # For key bindings screen, just draw a simple title
            self.game.ui_manager.draw_completed_message(
                "KEY BINDINGS", (480, 100), use_big_font=True
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
            # Calculate triple slash statistics
            triple_slash = self.game.field_renderer.get_triple_slash_line()

            result = (
                f"<font size=6>CURRENT OUTS : {self.game.currentouts}<br>"  # Increased font size
                f"STRIKEOUTS : {self.game.currentstrikeouts}<br>"
                f"WALKS : {self.game.currentwalks}<br>"
                f"BATTING : {triple_slash}<br>"  # Replaced HITS with triple slash
                f"RUNS SCORED: {self.game.scoreKeeper.get_score()}</font>"
            )
            count_string = (
                f"<font size=6><br>COUNT IS "  # Increased font size
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
        count_state = self.game.current_pitcher._get_count_state()
        selection = self.game.current_pitcher.ai.choose_action(
            self.game.current_state,
            batter_profile=self.game.batter_profile,
            pitch_history=self.game.pitch_history,
            count_state=count_state,
        )
        pitch_names = self.game.current_pitcher.get_pitch_names()
        if selection not in pitch_names:
            selection = pitch_names[0]
        self.game.pitch_chosen = selection

        # This will be handled by the pitch simulation
        self.game.current_pitcher.pitch(self._create_pitch_simulation, selection)
        
    def _create_pitch_simulation(self, release_point, pitchername, speed_mph, pfx_x, pfx_z, target_x, target_y, pitchtype):
        """Create and start a pitch simulation."""
        from .pitch_simulation import PitchSimulation
        self.pitch_simulation = PitchSimulation(
            self.game, release_point, pitchername, speed_mph, pfx_x, pfx_z, target_x, target_y, pitchtype
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

        # Show HOT STREAK indicator in gameday mode
        if (self.game.in_gameday_mode and self.game.gameday_manager
                and self.game.gameday_manager.is_player_hot()):
            self.game.ui_manager.draw_completed_message(
                "HOT STREAK", (550, 10), use_big_font=False
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
        triple_slash = self.game.field_renderer.get_triple_slash_line()

        self.messages = [
            "INNING OVER",
            f"HITS : {self.game.hits}",
            f"BATTING : {triple_slash}",  # Added triple slash line
            f"WALKS: {self.game.currentwalks}",
            f"STRIKEOUTS : {self.game.currentstrikeouts}",
            f"RUNS SCORED : {runs_scored}"
        ]
        
    def _update_pitcher_stats(self):
        """Update pitcher statistics."""
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
        self.game.current_pitcher.print_formatted_stats()
        
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
                    self.messages[i], (350, 100 + offset), use_big_font=False
                )
                offset += 70
                
        # Draw current message with typing effect
        if self.active_message < len(self.messages):
            message = self.messages[self.active_message]
            self.game.ui_manager.draw_typing_effect(
                message, self.counter, self.game.speed,
                (350, 100 + self.textoffset), use_big_font=False
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

        # Scale playback interval based on display FPS (base: 25ms at 60 FPS)
        display_fps = self.game.settings_manager.get_display_fps()
        frame_interval = 1500 / display_fps  # 25ms at 60 FPS, 12.5ms at 120 FPS

        if time_elapsed > frame_interval and self.current_frame <= len(self.game.last_pitch_information) - 1:
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

        # Draw pitch trajectories up to current frame as thin connected lines
        # with a small endpoint marker for the final plate location
        for pitch in self.game.pitch_trajectories:
            if len(pitch) < 2:
                continue

            # Find the last in-flight point (before outcome labels like "strike", "ball", etc.)
            # This is where the ball arrives at the plate.
            plate_idx = len(pitch) - 1
            for idx in range(len(pitch)):
                if pitch[idx][4]:  # has an outcome label → post-plate point
                    plate_idx = idx
                    break

            frame_limit = min(self.current_frame, plate_idx + 1)

            # Determine trail color from the last point's color (outcome-coded)
            trail_color = pitch[-1][3] if pitch[-1][4] else (180, 180, 180)
            # Dimmer version for the line
            dim_color = tuple(max(0, c // 2) for c in trail_color)

            # Draw thin anti-aliased lines between consecutive in-flight points
            for i in range(1, frame_limit):
                x0, y0 = int(pitch[i - 1][0]), int(pitch[i - 1][1])
                x1, y1 = int(pitch[i][0]), int(pitch[i][1])
                pygame.draw.aaline(screen, dim_color, (x0, y0), (x1, y1))

            # Show endpoint circle as soon as the line reaches the plate
            if frame_limit >= plate_idx + 1:
                ep = pitch[plate_idx]
                pygame.gfxdraw.aacircle(screen, int(ep[0]), int(ep[1]), 4, trail_color)
                pygame.gfxdraw.filled_circle(screen, int(ep[0]), int(ep[1]), 4, trail_color)

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

        # Use enhanced records if available, otherwise fall back to legacy
        if hasattr(self.game, 'enhanced_pitch_records') and self.game.enhanced_pitch_records:
            self.game.ui_manager.update_pitch_info_enhanced(
                self.game.enhanced_pitch_records
            )
        else:
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


class SandboxMenuState(GameState):
    """Placeholder state for Sandbox mode (future implementation)."""

    def __init__(self, game):
        super().__init__(game)

    def enter(self):
        """Initialize sandbox menu state."""
        self.game.ui_manager.hide_banner()
        self.game.ui_manager.set_button_visibility('sandbox_placeholder')

    def exit(self):
        """Clean up sandbox menu state."""
        pass

    def update(self, time_delta: float):
        """Update sandbox menu logic."""
        pass

    def handle_event(self, event):
        """Handle sandbox menu events."""
        self.game.ui_manager.process_events(event)
        if event.type == pygame.QUIT:
            return False
        return True

    def render(self, screen):
        """Render the sandbox menu placeholder."""
        screen.fill("black")
        # Draw placeholder text
        self.game.ui_manager.draw_completed_message(
            "SANDBOX MODE", (450, 250), use_big_font=True
        )
        self.game.ui_manager.draw_completed_message(
            "Coming Soon!", (500, 400), use_big_font=False
        )


class SandboxGameplayState(GameState):
    """Sandbox gameplay state with user-controlled pitch selection."""

    def __init__(self, game):
        super().__init__(game)
        self.pitch_simulation = None
        self.active_pitches = set()  # Set of toggled-on pitch types

    def enter(self):
        """Initialize sandbox gameplay state."""
        self.game.ui_manager.set_button_visibility('sandbox_gameplay')
        self._update_pitch_buttons()
        self._refresh_display()

        # Enable all pitches by default if none active or pitcher changed
        if self.game.current_pitcher:
            pitch_names = self.game.current_pitcher.get_pitch_names()
            if not self.active_pitches or not self.active_pitches.issubset(set(pitch_names)):
                self.active_pitches = set(pitch_names)
                self._update_pitch_buttons()
                self._refresh_display()

    def exit(self):
        """Clean up sandbox gameplay state."""
        self.pitch_simulation = None

    def _refresh_display(self):
        """Refresh the game display with current stats."""
        # Calculate triple slash statistics
        triple_slash = self.game.field_renderer.get_triple_slash_line()

        result = (
            f"<font size=6>OUTS: {self.game.currentouts}<br>"  # Increased font size
            f"STRIKEOUTS: {self.game.currentstrikeouts}<br>"
            f"WALKS: {self.game.currentwalks}<br>"
            f"BATTING: {triple_slash}<br>"  # Replaced HITS with triple slash
            f"RUNS: {self.game.scoreKeeper.get_score()}</font>"
        )
        active_display = ", ".join(sorted(self.active_pitches)) if self.active_pitches else "None"
        count_string = (
            f"<font size=6>COUNT: {self.game.currentballs}-{self.game.currentstrikes}<br>"  # Increased font size
            f"ACTIVE: {active_display}</font>"
        )
        self.game.ui_manager.update_scoreboard(result)
        self.game.ui_manager.update_pitch_result(count_string)
        self.game.ui_manager.hide_banner()

    def _update_pitch_buttons(self):
        """Update pitch type buttons for current pitcher."""
        if self.game.current_pitcher:
            pitch_names = self.game.current_pitcher.get_pitch_names()
            self.game.ui_manager.update_sandbox_pitch_buttons(pitch_names, self.active_pitches)

    def switch_pitcher(self, pitcher_name: str):
        """Switch to a different pitcher."""
        self.game.pitcher_manager.set_current_pitcher(pitcher_name)

        # Enable all pitches for new pitcher
        pitch_names = self.game.current_pitcher.get_pitch_names()
        self.active_pitches = set(pitch_names) if pitch_names else set()

        self._update_pitch_buttons()
        self._refresh_display()

    def toggle_pitch(self, pitch_name: str):
        """Toggle a pitch type on or off for random selection."""
        if self.game.current_pitcher and pitch_name in self.game.current_pitcher.get_pitch_names():
            if pitch_name in self.active_pitches:
                # Don't allow deactivating the last pitch
                if len(self.active_pitches) > 1:
                    self.active_pitches.discard(pitch_name)
            else:
                self.active_pitches.add(pitch_name)
            self._update_pitch_buttons()
            self._refresh_display()

    def update(self, time_delta: float):
        """Update sandbox gameplay logic."""
        if self.pitch_simulation and self.pitch_simulation.running:
            self.pitch_simulation.update()

        if self.pitch_simulation and not self.pitch_simulation.running:
            self.pitch_simulation = None
            self.game.ui_manager.set_button_visibility('sandbox_gameplay')
            self._update_pitch_buttons()
            self._refresh_display()

    def handle_event(self, event):
        """Handle sandbox gameplay events."""
        if event.type == pygame.QUIT:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_q and not self.pitch_simulation:
                self._initiate_pitch()

        self.game.ui_manager.process_events(event)
        return True

    def _initiate_pitch(self):
        """Start a new pitch simulation with a random active pitch."""
        if not self.active_pitches:
            return  # No pitches active

        import random
        chosen_pitch = random.choice(list(self.active_pitches))

        self.game.first_pitch_thrown = True
        self.game.pitch_chosen = chosen_pitch

        # Randomly select from active pitches
        self.game.current_pitcher.pitch(self._create_pitch_simulation, chosen_pitch)

    def _create_pitch_simulation(self, release_point, pitchername, speed_mph, pfx_x, pfx_z, target_x, target_y, pitchtype):
        """Create and start a pitch simulation."""
        from .pitch_simulation import PitchSimulation
        self.pitch_simulation = PitchSimulation(
            self.game, release_point, pitchername, speed_mph, pfx_x, pfx_z, target_x, target_y, pitchtype
        )
        self.pitch_simulation.run()

    def render(self, screen):
        """Render the sandbox gameplay state."""
        screen.fill("black")
        self.game.current_pitcher.draw_pitcher(0, 0)
        self.game.field_renderer.draw_strikezone()
        self.game.field_renderer.draw_field(self.game.scoreKeeper.get_bases())
        self.game.batter.draw_stance(1)

        # Draw current ball position
        if self.game.first_pitch_thrown:
            pygame.gfxdraw.aacircle(
                screen, int(self.game.ball[0]), int(self.game.ball[1]),
                self.game.fourseamballsize, (255, 255, 255)
            )


class GameDayState(GameState):
    """Entry screen for GameDay mode - a full 9-inning simulated game."""

    def __init__(self, game):
        super().__init__(game)

    def enter(self):
        """Show the gameday entry screen."""
        # The gameday_manager should already be initialized in Game.enter_gameday_mode()
        self.game.ui_manager.set_visibility_state('gameday_start')

    def exit(self):
        """Clean up gameday state."""
        pass

    def update(self, time_delta: float):
        """Update logic."""
        pass

    def handle_event(self, event):
        """Handle events - primarily the start button."""
        self.game.ui_manager.process_events(event)

        if event.type == pygame.QUIT:
            return False

        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            if event.ui_element == self.game.ui_manager.buttons.get('start_gameday'):
                # Start the first inning - opponent bats first (top of 1st)
                self.game.inning_ended = False
                # Transition to gameday_transition to simulate opponent's half
                self.game.state_manager.change_state('gameday_transition')
        return True

    def render(self, screen):
        """Render the gameday entry screen."""
        screen.fill((30, 40, 50))  # Dark background

        # Title (regular 48px font)
        self.game.ui_manager.draw_completed_message("GameDay Mode", (500, 150))

        # Description (small 28px font)
        desc_lines = [
            "Full 9-Inning Baseball Simulation",
            "",
            "Starting Pitcher: YAMAMOTO",
            "Relief Pitchers: SASAKI, DEGROM, MCCLANAHAN",
            "",
            "Press 'Start Game' to begin!"
        ]

        y_offset = 260
        for line in desc_lines:
            if line:
                self.game.ui_manager.draw_completed_message(line, (300, y_offset), use_small_font=True)
            y_offset += 40

        # Career record
        from gameplay.gameday_manager import GameDayManager
        record = GameDayManager.get_career_record()
        if record['total'] > 0:
            record_text = f"Career Record: {record['wins']}W - {record['losses']}L - {record['ties']}T"
            self.game.ui_manager.draw_completed_message(
                record_text, (300, y_offset + 10), use_small_font=True, color=(255, 255, 100))


class GameDayTransitionState(GameState):
    """Handles transitions between player innings and opponent simulation."""

    # Button layout constants
    _BUTTON_X = 800
    _BUTTON_Y_START = 500
    _BUTTON_Y_GAP = 70

    def __init__(self, game):
        super().__init__(game)
        self.phase = "SHOW_SCORE"  # Phases: SHOW_SCORE, SIMULATING, FINAL
        self.simulation_complete = False
        self.opponent_events = []
        self._game_log_window = None
        self._result_saved = False
        self._labels = []  # Track UILabels for cleanup

    def _setup_phase_ui(self):
        """Position buttons and set visibility based on current phase."""
        # Use proper visibility states instead of manual show/hide
        if self.phase == "FINAL":
            self.game.ui_manager.set_visibility_state('gameday_final')
            self.game.ui_manager.buttons['final_menu'].set_relative_position(
                (self._BUTTON_X, self._BUTTON_Y_START))
            self.game.ui_manager.buttons['view_game_log'].set_relative_position(
                (self._BUTTON_X, self._BUTTON_Y_START + self._BUTTON_Y_GAP))
        elif self.phase == "SIMULATING":
            self.game.ui_manager.set_visibility_state('gameday_simulation')
            self.game.ui_manager.buttons['start_batting'].set_relative_position(
                (self._BUTTON_X, self._BUTTON_Y_START))
            self.game.ui_manager.buttons['view_game_log'].set_relative_position(
                (self._BUTTON_X, self._BUTTON_Y_START + self._BUTTON_Y_GAP))
        else:
            # SHOW_SCORE phase
            self.game.ui_manager.set_visibility_state('gameday_transition')
            self.game.ui_manager.buttons['next_inning'].set_relative_position(
                (self._BUTTON_X, self._BUTTON_Y_START))
            self.game.ui_manager.buttons['view_game_log'].set_relative_position(
                (self._BUTTON_X, self._BUTTON_Y_START + self._BUTTON_Y_GAP))

    def _clear_labels(self):
        """Kill all dynamic UILabels."""
        for label in self._labels:
            label.kill()
        self._labels.clear()

    def enter(self):
        """Called when entering transition state."""
        # Hide any lingering banners and panels
        self.game.ui_manager.hide_banner()
        self.game.ui_manager.hide_box_score()
        self.game.ui_manager.hide_scouting_panel()
        self.game.ui_manager.hide_lap_log_panel()

        # Hide gameplay UI elements
        self.game.ui_manager.scoreboard.hide()
        self.game.ui_manager.pitch_result.hide()

        # Clean up labels from previous entry
        self._clear_labels()

        # Determine what phase we're in
        if self.game.gameday_manager.current_inning > 9:
            self.phase = "FINAL"
            self._save_result_once()
        elif self.game.gameday_manager.is_top_inning:
            # Top of inning - opponent bats first, so simulate now
            self.phase = "SIMULATING"
            self._simulate_opponent_half_inning()
        else:
            gameday_mgr = self.game.gameday_manager
            # Check if player is leading after top of 9th - skip bottom of 9th
            if (gameday_mgr.current_inning == 9 and
                len(gameday_mgr.player_inning_scores) == 8 and  # Player hasn't batted yet in 9th
                gameday_mgr.player_score > gameday_mgr.opponent_score):
                # Skip bottom of 9th - game over
                self.phase = "FINAL"
                gameday_mgr.game_over = True
                self._save_result_once()
            else:
                # Bottom of inning just ended - show score before next inning
                self.phase = "SHOW_SCORE"

                # Check for opponent pitcher substitution (player was batting against opponent pitcher)
                if gameday_mgr.should_consider_relief_pitcher():
                    new_pitcher = gameday_mgr.substitute_relief_pitcher()
                    if new_pitcher:
                        self._load_and_switch_pitcher(new_pitcher)

        # Position buttons and set visibility for current phase
        self._setup_phase_ui()

        # Ensure gameplay UI stays hidden (redundant safety)
        self.game.ui_manager.scoreboard.hide()
        self.game.ui_manager.pitch_result.hide()

    def exit(self):
        """Called when exiting this state."""
        self.game.ui_manager.hide_box_score()
        self._clear_labels()
        if self._game_log_window is not None:
            self._game_log_window.kill()
            self._game_log_window = None

    def update(self, time_delta: float):
        """Update transition logic."""
        pass

    def _save_result_once(self):
        """Save game result exactly once when entering FINAL phase."""
        if not self._result_saved:
            self._result_saved = True
            self.game.gameday_manager.save_game_result()

    def handle_event(self, event):
        """Handle events - button clicks for continuing."""
        self.game.ui_manager.process_events(event)

        if event.type == pygame.QUIT:
            return False

        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            if event.ui_element == self.game.ui_manager.buttons.get('next_inning'):
                self._handle_next_inning()
            elif event.ui_element == self.game.ui_manager.buttons.get('start_batting'):
                self._start_player_batting()
            elif event.ui_element == self.game.ui_manager.buttons.get('view_game_log'):
                self._show_game_log()
            elif event.ui_element == self.game.ui_manager.buttons.get('final_menu'):
                self._return_to_menu()
        return True

    def _simulate_opponent_half_inning(self):
        """Simulate the opponent's at-bats for this half-inning."""
        self.opponent_events = []
        gameday_mgr = self.game.gameday_manager

        # Simulate until 3 outs
        while gameday_mgr.current_outs < 3:
            outcome, runs_scored = gameday_mgr.simulate_opponent_at_bat()
            self.opponent_events.append(f"{gameday_mgr.get_current_batter_name()}: {outcome}" +
                                       (f" ({runs_scored} run{'s' if runs_scored != 1 else ''})" if runs_scored > 0 else ""))

        # Opponent score is already tracked in simulate_opponent_at_bat()
        # No need to update it here

        # End the opponent's half inning
        gameday_mgr.end_half_inning()

        # Check for PLAYER'S pitcher substitution (opponent was batting against player's pitcher)
        if gameday_mgr.should_consider_player_relief_pitcher():
            new_pitcher = gameday_mgr.substitute_player_relief_pitcher()
            if new_pitcher:
                message = f"Pitching change (Your Team): {new_pitcher.upper()} coming in to pitch"
                self.opponent_events.append(message)

        # Check if game is over
        if gameday_mgr.game_over:
            self.phase = "FINAL"
            self._save_result_once()
            self.game.ui_manager.set_visibility_state('gameday_final')

        self.simulation_complete = True

    def _load_and_switch_pitcher(self, pitcher_name: str):
        """Load and switch to a new pitcher."""
        import pickle
        import sys
        from config import get_path

        # Clear fatigue from old pitcher
        self.game.current_pitcher.clear_fatigue_stats()

        # Set the new pitcher in the pitcher manager
        self.game.pitcher_manager.set_current_pitcher(pitcher_name)
        self.game.current_pitcher = self.game.pitcher_manager.get_current_pitcher()

        # Load AI for the new pitcher
        import ai.AI_2 as AI_2
        sys.modules['AI_2'] = AI_2

        # Get the pitcher's actual pitch arsenal
        pitcher_pitch_names = set(self.game.current_pitcher.get_pitch_names())
        ai_loaded = False

        try:
            ai_file = get_path(f"ai/{pitcher_name}_ai.pkl")
            with open(ai_file, "rb") as f:
                ai = pickle.load(f)

            # Validate that the AI's action space matches the pitcher's arsenal
            ai_actions = set(ai.actions)
            if ai_actions == pitcher_pitch_names:
                self.game.current_pitcher.attach_ai(ai)
                ai_loaded = True
            else:
                print(f"Warning: AI action space mismatch for {pitcher_name}")
                print(f"  AI actions: {sorted(ai_actions)}")
                print(f"  Pitcher arsenal: {sorted(pitcher_pitch_names)}")
                print(f"  Creating new AI with correct action space")
        except FileNotFoundError:
            print(f"Warning: AI file not found for {pitcher_name}, using default AI")

        # If AI wasn't loaded successfully or had wrong actions, create a new one
        if not ai_loaded:
            from ai.AI_2 import ERAI
            ai = ERAI(self.game.current_pitcher.get_pitch_names())
            self.game.current_pitcher.attach_ai(ai)

        # Attach fatigue stats for the new pitcher
        self.game.current_pitcher.set_fatigue_stats(
            self.game.gameday_manager.get_active_pitcher_stats()
        )

    def _handle_next_inning(self):
        """Handle transition to next inning."""
        # End the current half-inning
        self.game.gameday_manager.end_half_inning()

        # Check if game is over
        if self.game.gameday_manager.game_over:
            self.phase = "FINAL"
            self._save_result_once()
            self._setup_phase_ui()
            return

        # Check if we need to simulate opponent or start player batting
        if self.game.gameday_manager.is_top_inning:
            # Top of new inning - simulate opponent first
            self.phase = "SIMULATING"
            self._simulate_opponent_half_inning()
            self._setup_phase_ui()
        else:
            # Bottom of inning - player bats
            self._start_player_batting()

    def _start_player_batting(self):
        """Start the player's batting half-inning."""
        # At this point, end_half_inning() should have been called after opponent simulation
        # so is_top_inning should be False (player's turn)

        # Reset for new half-inning
        self.game.game_stats.reset_game_stats()
        self.game.scoreKeeper.reset()
        self.game.inning_ended = False
        self.game.just_refreshed = 1  # Force scoreboard refresh with clean stats

        # Clear pitch data from previous inning
        self.game.pitch_trajectories = []
        self.game.enhanced_pitch_records = []
        self.game.pitchDataManager.records = []
        self.game.pitches_display = []

        # Transition to gameplay
        self.game.state_manager.change_state('gameplay')

    def _show_game_log(self):
        """Show the complete game log in a scrollable window."""
        # Kill existing window if open
        if self._game_log_window is not None:
            self._game_log_window.kill()
            self._game_log_window = None

        gameday_mgr = self.game.gameday_manager
        log_lines = []

        # Box score header
        box_data = gameday_mgr.get_box_score_lines()
        log_lines.append("<b>BOX SCORE</b><br>")
        header = "              "
        for i in range(1, 10):
            header += f"{i:>3}"
        header += "  | R"
        log_lines.append(f"{header}<br>")

        opp_line = f"{'Opponent':<14}"
        for r in box_data['opponent']:
            opp_line += f"{r:>3}"
        opp_line += f"  | {box_data['opponent_total']}"
        log_lines.append(f"{opp_line}<br>")

        plr_line = f"{'Player':<14}"
        for r in box_data['player']:
            plr_line += f"{r:>3}"
        plr_line += f"  | {box_data['player_total']}"
        log_lines.append(f"{plr_line}<br>")

        # Play-by-play
        log_lines.append("<br><b>PLAY-BY-PLAY</b><br><br>")

        current_inning = 0
        current_half = None

        for event in gameday_mgr.event_log:
            half_str = 'top' if event.is_top else 'bottom'
            if event.inning != current_inning or half_str != current_half:
                current_inning = event.inning
                current_half = half_str
                half_label = "Top" if event.is_top else "Bottom"
                log_lines.append(f"<br><b>--- {half_label} of Inning {current_inning} ---</b><br>")

            log_lines.append(f"{str(event)}<br>")

        # Pitcher stats
        log_lines.append("<br><b>PITCHER STATS</b><br><br>")
        log_lines.append("<b>Opponent Pitchers:</b><br>")
        for ps in gameday_mgr.get_opponent_pitcher_stats():
            log_lines.append(f"  {ps.get_summary()}<br>")
        log_lines.append("<br><b>Your Team's Pitchers:</b><br>")
        for ps in gameday_mgr.get_player_pitcher_stats():
            log_lines.append(f"  {ps.get_summary()}<br>")

        log_text = "".join(log_lines)

        # Create window
        self._game_log_window = pygame_gui.elements.UIWindow(
            rect=pygame.Rect((140, 40), (1000, 640)),
            manager=self.game.ui_manager.manager,
            window_display_title='Game Log'
        )

        pygame_gui.elements.UITextBox(
            html_text=log_text,
            relative_rect=pygame.Rect((10, 10), (960, 570)),
            manager=self.game.ui_manager.manager,
            container=self._game_log_window
        )

    def _return_to_menu(self):
        """Return to main menu."""
        self.game.current_pitcher.clear_fatigue_stats()
        self.game.in_gameday_mode = False
        self.game.gameday_manager = None
        self.game.set_menu_state(0)

    def render(self, screen):
        """Render the transition screen."""
        screen.fill((20, 30, 40))  # Dark blue background

        # Title (regular 48px font)
        self.game.ui_manager.draw_completed_message("GameDay Mode", (100, 50))

        # Current inning and score (small 28px font)
        if self.phase == "FINAL":
            inning_text = "After 9 Innings"
        else:
            inning_text = self.game.gameday_manager.get_inning_summary()
        score_text = self.game.gameday_manager.get_score_summary()

        self.game.ui_manager.draw_completed_message(inning_text, (100, 130), use_small_font=True)
        self.game.ui_manager.draw_completed_message(score_text, (100, 170), use_small_font=True, color=(255, 255, 100))

        # Show pitcher info
        pitcher_stats = self.game.gameday_manager.get_active_pitcher_stats()
        fatigue_text = ""
        if hasattr(pitcher_stats, 'get_fatigue_label'):
            fatigue_text = f" | Fatigue: {pitcher_stats.get_fatigue_label()}"
        pitcher_text = f"Pitching: {pitcher_stats.name.upper()} ({pitcher_stats.pitch_count} pitches{fatigue_text})"
        self.game.ui_manager.draw_completed_message(pitcher_text, (100, 210), use_small_font=True, color=(150, 255, 150))

        # Inning score box (non-FINAL phases)
        if self.phase != "FINAL":
            box_data = self.game.gameday_manager.get_box_score_lines()
            current_inning = self.game.gameday_manager.current_inning
            self.game.ui_manager.show_box_score(box_data, current_inning, position=(700, 150))

        # Show recent events if simulating or just simulated
        if self.phase == "SIMULATING" and self.simulation_complete:
            self.game.ui_manager.draw_completed_message(
                "Opponent's At-Bats:", (100, 350), use_small_font=True, color=(255, 200, 100))

            y_offset = 390
            for event_str in self.opponent_events[-10:]:
                self.game.ui_manager.draw_completed_message(
                    event_str, (100, y_offset), use_small_font=True)
                y_offset += 30

        elif self.phase == "SHOW_SCORE":
            events = self.game.gameday_manager.get_recent_events(8)

            if events:
                self.game.ui_manager.draw_completed_message(
                    "Recent At-Bats:", (100, 350), use_small_font=True, color=(255, 200, 100))

                y_offset = 390
                for event in events:
                    self.game.ui_manager.draw_completed_message(
                        str(event), (100, y_offset), use_small_font=True)
                    y_offset += 30

                # Show player batting line
                batting_line = self._get_player_batting_line()
                if batting_line:
                    self.game.ui_manager.draw_completed_message(
                        batting_line, (100, y_offset + 15), use_small_font=True, color=(150, 255, 150))

        elif self.phase == "FINAL":
            # Show final game summary
            winner = self.game.gameday_manager.get_winner()
            if winner == "Player":
                result_text = "YOU WIN!"
            elif winner == "Opponent":
                result_text = "YOU LOSE"
            else:
                result_text = "TIE GAME"

            self.game.ui_manager.draw_completed_message(result_text, (450, 300), use_big_font=True)

            # Box score
            box_data = self.game.gameday_manager.get_box_score_lines()
            self.game.ui_manager.show_box_score(box_data, position=(700, 150))

            # Pitcher stats below box score
            panel_h = self.game.ui_manager.box_score_panel.get_relative_rect().height
            y_offset = 350 + panel_h + 20

            self.game.ui_manager.draw_completed_message(
                "Opponent Pitchers:", (80, y_offset), use_small_font=True, color=(255, 200, 100))
            y_offset += 28

            for pitcher_stat in self.game.gameday_manager.get_opponent_pitcher_stats():
                self.game.ui_manager.draw_completed_message(
                    pitcher_stat.get_summary(), (80, y_offset), use_small_font=True)
                y_offset += 26

            y_offset += 8
            self.game.ui_manager.draw_completed_message(
                "Your Team's Pitchers:", (80, y_offset), use_small_font=True, color=(150, 255, 150))
            y_offset += 28

            for pitcher_stat in self.game.gameday_manager.get_player_pitcher_stats():
                self.game.ui_manager.draw_completed_message(
                    pitcher_stat.get_summary(), (80, y_offset), use_small_font=True)
                y_offset += 26

    def _get_player_batting_line(self):
        """Get player's batting line for between-inning display."""
        mgr = self.game.gameday_manager
        # Count player at-bat events
        player_hits = 0
        player_abs = 0
        player_rbis = 0
        for event in mgr.event_log:
            if not event.is_top:  # Player's at-bats (bottom of inning)
                if event.result in ['SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN']:
                    player_hits += 1
                    player_abs += 1
                elif event.result in ['STRIKEOUT', 'FLYOUT', 'GROUNDOUT', 'LINEOUT']:
                    player_abs += 1
                # WALK doesn't count as AB
                player_rbis += event.runs_scored
        if player_abs == 0:
            return None
        avg = player_hits / player_abs
        return f"Batting: {player_hits}/{player_abs} ({avg:.3f}), {player_rbis} RBI"