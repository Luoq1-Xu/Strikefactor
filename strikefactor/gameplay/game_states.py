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
from config import get_path, resource_path


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
        """Refresh the game display - scorebug handles stats rendering."""
        self.game.ui_manager.hide_banner()
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

        # ABS challenge prompt while the window is open after a taken pitch
        if self.game._challenge_window_active() and not self.game.abs_overlay.is_active():
            self._draw_abs_challenge_prompt(screen)

    def _draw_abs_challenge_prompt(self, screen):
        from key_binding_manager import KeyAction
        from config import ABS_PINK
        if not hasattr(self, '_abs_prompt_font'):
            self._abs_prompt_font = pygame.font.SysFont("arial", 18, bold=True)

        seconds_left = self.game.challenge_seconds_remaining()
        key_code = self.game.key_binding_manager.get_key_for_action(KeyAction.CHALLENGE)
        key_name = self.game.key_binding_manager.get_key_name(key_code)
        suffix = "∞" if self.game.challenge_manager.is_unlimited() else f"{seconds_left:.1f}s"
        msg = f"[{key_name}] Challenge ({suffix})"
        text = self._abs_prompt_font.render(msg, True, (255, 255, 255))
        bg_w = text.get_width() + 28
        bg_h = text.get_height() + 14
        bg = pygame.Surface((bg_w, bg_h), pygame.SRCALPHA)
        pygame.draw.rect(bg, (*ABS_PINK, 220), bg.get_rect(), border_radius=8)
        pygame.draw.rect(bg, (255, 255, 255, 230), bg.get_rect(), width=2, border_radius=8)
        bg.blit(text, (14, 7))
        x = (self.game.internal_width - bg_w) // 2
        y = self.game.internal_height - bg_h - 80
        screen.blit(bg, (x, y))


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
        if not self.game.pitch_trajectories:
            return

        current_time = pygame.time.get_ticks()
        time_elapsed = current_time - self.last_time

        # Scale playback interval based on display FPS (base: 25ms at 60 FPS)
        display_fps = self.game.settings_manager.get_display_fps()
        frame_interval = 1500 / display_fps  # 25ms at 60 FPS, 12.5ms at 120 FPS

        # Cap by the longest trajectory in the inning so older pitches with
        # more frames than the latest one still animate all the way to their
        # plate endpoint instead of being cut off mid-flight.
        max_len = max(len(p) for p in self.game.pitch_trajectories)
        if time_elapsed > frame_interval and self.current_frame <= max_len - 1:
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

        if not self.game.pitch_trajectories:
            return

        # Draw pitch trajectories up to current frame as thin connected lines
        # with a small endpoint marker for the final plate location
        for pitch in self.game.pitch_trajectories:
            if len(pitch) < 2:
                continue

            # plate_idx = index of the first labeled (post-arrival) entry, i.e.
            # the moment the ball reached the plate. In-flight entries before
            # that have an empty outcome label.
            plate_idx = len(pitch) - 1
            for idx in range(len(pitch)):
                if pitch[idx][4]:
                    plate_idx = idx
                    break

            frame_limit = min(self.current_frame, plate_idx + 1)

            # Trail color is taken from the last entry, which the finish-pitch
            # / ABS-overturn paths recolor to reflect the *current* call. So a
            # strike→ball overturn shows green here without extra plumbing.
            trail_color = pitch[-1][3] if pitch[-1][4] else (180, 180, 180)
            dim_color = tuple(c // 2 for c in trail_color)

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
    """State shown when inning ends (3 outs or walk-off) - allows visualization before summary.

    On a walk-off, plays a ~3-second celebration sequence (full-screen flash,
    pulsing bases, sequenced WALK-OFF WIN banner) before exposing the
    CONTINUE button. Re-entering the state (e.g. returning from pitchviz)
    is one-shot via a sentinel on the gameday manager.
    """

    # Celebration phase boundaries (ms)
    _CELEBRATION_FLASH_END = 300        # white flash decays to 0
    _CELEBRATION_BANNER_SWAP_END = 350  # hit banner -> WALK-OFF WIN swap
    _CELEBRATION_PULSE_END = 2700       # bases stop pulsing
    _CELEBRATION_END = 3000             # CONTINUE button reveals

    _CELEBRATION_FLASH_PEAK_ALPHA = 200
    _CELEBRATION_PULSE_RADIUS = 38
    _CELEBRATION_PULSE_COLOR = (255, 215, 0)  # gold

    # Approximate diamond center positions used by field_renderer.draw_bases
    # plus home plate. Mirrors the polygons in field_renderer.draw_bases /
    # draw_homeplate.
    _BASE_CENTERS = [
        (1115, 610),  # 1B
        (1080, 575),  # 2B
        (1045, 610),  # 3B
        (630, 672),   # home plate
    ]

    def __init__(self, game):
        super().__init__(game)
        self._celebration_active = False
        self._celebration_start = 0
        self._banner_swapped = False
        self._continue_revealed = False
        # Pre-built full-screen flash surface (lazy on first walkoff).
        self._flash_surface = None

    def enter(self):
        """Initialize inning end state."""
        self.game.ui_manager.set_button_visibility('inning_end')

        # Kick off the celebration sequence on the FIRST entry to inning_end
        # for a walk-off. Returning here from pitchviz must not re-fire it.
        gd = self.game.gameday_manager
        is_walkoff = bool(gd and getattr(gd, 'is_walkoff', False))
        already_played = bool(getattr(gd, '_walkoff_celebration_played', False)) if gd else False

        if is_walkoff and not already_played:
            self._start_celebration()
            if gd is not None:
                gd._walkoff_celebration_played = True
        else:
            # No celebration — restore the normal inning_end UI immediately.
            self._celebration_active = False
            self._continue_revealed = True

    def exit(self):
        """Clean up inning end state."""
        # If the user advances out of inning_end mid-celebration (shouldn't
        # be possible since CONTINUE is hidden, but defensive), make sure
        # the button is visible for the next state's UI logic to manage.
        if self._celebration_active:
            self._reveal_continue_button()
        self._celebration_active = False
        self._banner_swapped = False

    def _start_celebration(self):
        """Begin the walk-off celebration phase sequence."""
        self._celebration_active = True
        self._celebration_start = pygame.time.get_ticks()
        self._banner_swapped = False
        self._continue_revealed = False

        # Hide CONTINUE during the celebration so the player can't skip past
        # the banner reveal accidentally with a stray click.
        cont_btn = self.game.ui_manager.buttons.get('continue_to_summary')
        if cont_btn is not None:
            cont_btn.hide()

        # Lazily build the flash overlay surface at screen size.
        if self._flash_surface is None:
            screen = self.game.screen
            self._flash_surface = pygame.Surface(
                screen.get_size(), pygame.SRCALPHA
            )

    def _reveal_continue_button(self):
        if self._continue_revealed:
            return
        cont_btn = self.game.ui_manager.buttons.get('continue_to_summary')
        if cont_btn is not None:
            cont_btn.show()
        self._continue_revealed = True

    def _celebration_t(self) -> int:
        """Milliseconds since celebration start, capped at _CELEBRATION_END."""
        return min(
            self._CELEBRATION_END,
            pygame.time.get_ticks() - self._celebration_start,
        )

    def update(self, time_delta: float):
        """Drive the celebration phase machine."""
        if not self._celebration_active:
            return

        t = self._celebration_t()

        # Phase 2 — swap the leading hit/walk banner for "WALK-OFF WIN!"
        if not self._banner_swapped and t >= self._CELEBRATION_BANNER_SWAP_END:
            self.game.ui_manager.hide_banner()
            self.game.ui_manager.show_banner(
                "WALK-OFF WIN!", typing_speed=0.05
            )
            self._banner_swapped = True

        # Phase 5 — celebration finished, hand control back to the player.
        if t >= self._CELEBRATION_END:
            self._reveal_continue_button()
            self._celebration_active = False

    def handle_event(self, event):
        """Handle inning end events."""
        self.game.ui_manager.process_events(event)
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            # Block pitching input (Q key) since inning is over.
            if event.key == pygame.K_q:
                return True
            # Skip the celebration: jump start time backward so the next
            # update tick crosses _CELEBRATION_END and runs the same
            # "settle" branch as the natural timeout.
            if self._celebration_active:
                self._celebration_start = (
                    pygame.time.get_ticks() - self._CELEBRATION_END - 1
                )
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

        if self._celebration_active:
            t = self._celebration_t()
            # Draw under-banner field accents first, then the screen flash on
            # top so the flash crests during the very first beat.
            self._render_bases_pulse(screen, t)
            self._render_flash_overlay(screen, t)

    # ------------------------------------------------------------------
    # Celebration overlays

    def _render_flash_overlay(self, screen, t):
        """Full-screen white flash that decays over the first 300ms."""
        if t >= self._CELEBRATION_FLASH_END or self._flash_surface is None:
            return
        # Ease-out alpha from peak to 0 across the flash window.
        # 1 - (1 - p)^2  → quick rise then taper, mirroring _ease_out from
        # ui/abs_challenge_overlay.py without taking the import dependency.
        progress = t / self._CELEBRATION_FLASH_END
        eased = 1.0 - (1.0 - progress) * (1.0 - progress)
        alpha = int(self._CELEBRATION_FLASH_PEAK_ALPHA * (1.0 - eased))
        if alpha <= 0:
            return
        self._flash_surface.fill((255, 255, 255, alpha))
        screen.blit(self._flash_surface, (0, 0))

    def _render_bases_pulse(self, screen, t):
        """Sine-pulsing gold halos behind the bases + home plate."""
        if t >= self._CELEBRATION_END:
            return
        # Pulse intensity over time: full amplitude through PULSE_END, then
        # linearly decays to 0 at CELEBRATION_END.
        if t <= self._CELEBRATION_PULSE_END:
            envelope = 1.0
        else:
            decay_dur = self._CELEBRATION_END - self._CELEBRATION_PULSE_END
            envelope = max(
                0.0,
                1.0 - (t - self._CELEBRATION_PULSE_END) / decay_dur,
            )

        # ~2.4 Hz sine pulse (cycle ≈ 415ms) — feels alive without flickering.
        import math
        pulse = 0.5 + 0.5 * math.sin(t / 1000.0 * 2 * math.pi * 2.4)
        intensity = envelope * pulse

        peak_alpha = 180
        alpha = int(peak_alpha * intensity)
        if alpha <= 0:
            return

        r, g, b = self._CELEBRATION_PULSE_COLOR
        radius = self._CELEBRATION_PULSE_RADIUS
        # Build one halo surface and reuse it (saves per-frame allocs).
        halo = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(
            halo, (r, g, b, alpha), (radius, radius), radius
        )
        for cx, cy in self._BASE_CENTERS:
            screen.blit(halo, (cx - radius, cy - radius))


class SandboxMenuState(GameState):
    """Sandbox mode menu with pitcher selection and typing effect."""

    def __init__(self, game):
        super().__init__(game)
        self.messages = ["Sandbox Mode", "Select A Pitcher"]
        self.active_message = 0
        self.counter = 0
        self.textoffset = 0
        self.messages_finished = 0
        self.done = False
        self.running = True

    def enter(self):
        """Initialize sandbox menu state."""
        self.game.ui_manager.hide_banner()
        self.game.ui_manager.set_button_visibility('sandbox_menu')
        # Reset typing effect
        self.active_message = 0
        self.counter = 0
        self.textoffset = 0
        self.messages_finished = 0
        self.done = False
        self.running = True

    def exit(self):
        """Clean up sandbox menu state."""
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
        """Handle sandbox menu events."""
        self.game.ui_manager.process_events(event)
        if event.type == pygame.QUIT:
            return False
        return True

    def render(self, screen):
        """Render the sandbox menu with typing effect."""
        screen.fill("black")

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
        """Refresh the game display - scorebug handles stats rendering."""
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

        # Reuse the gameplay state's prompt drawer for the ABS challenge hint.
        if self.game._challenge_window_active() and not self.game.abs_overlay.is_active():
            GameplayState._draw_abs_challenge_prompt(self, screen)


class GameDayState(GameState):
    """Entry screen for GameDay mode - a full 9-inning simulated game."""

    CARD_RECT = pygame.Rect(310, 220, 660, 280)

    def __init__(self, game):
        super().__init__(game)
        from ui.pitcher_carousel import PitcherCarousel
        self.carousel = PitcherCarousel(
            self.game.pitcher_manager,
            self.game.ui_manager,
            default='yamamoto',
        )
        self._gd_fonts = None

    def enter(self):
        """Show the gameday entry screen."""
        # Reset carousel to the default starter each time the screen opens.
        self.carousel.reset('yamamoto')
        self.game.ui_manager.set_visibility_state('gameday_start')

    def exit(self):
        """Clean up gameday state."""
        pass

    def update(self, time_delta: float):
        """Update logic."""
        pass

    def handle_event(self, event):
        """Handle events - carousel navigation, start, keyboard shortcuts."""
        self.game.ui_manager.process_events(event)

        if event.type == pygame.QUIT:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                self.carousel.prev()
            elif event.key == pygame.K_RIGHT:
                self.carousel.next()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._confirm_selection()

        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            buttons = self.game.ui_manager.buttons
            if event.ui_element == buttons.get('start_gameday'):
                self._confirm_selection()
            elif event.ui_element == buttons.get('gameday_prev_pitcher'):
                self.carousel.prev()
            elif event.ui_element == buttons.get('gameday_next_pitcher'):
                self.carousel.next()
        return True

    def _confirm_selection(self):
        """Commit the chosen starter and advance into the game."""
        starter = self.carousel.get_selected()
        self.game.inning_ended = False
        self.game.start_gameday_with_starter(starter)

    def _ensure_fonts(self):
        """Lazily build the pixel fonts used by the entry-screen chrome."""
        if not hasattr(self, '_gd_fonts') or self._gd_fonts is None:
            base = resource_path(get_path("ui/font/8bitoperator_jve.ttf"))
            self._gd_fonts = {
                'micro': pygame.font.Font(base, 14),
                'tiny':  pygame.font.Font(base, 16),
                'small': pygame.font.Font(base, 18),
                'huge':  pygame.font.Font(base, 60),
            }
        return self._gd_fonts

    def render(self, screen):
        """Render the gameday entry screen."""
        screen.fill((0, 0, 0))
        f = self._ensure_fonts()
        margin_x = 40
        screen_w = 1280
        FG = (240, 240, 240)
        DIM = (140, 140, 140)
        DIVIDER = (60, 60, 60)

        # --- Header chrome ---
        header = f['micro'].render("=== GAMEDAY · SETUP ===", True, FG)
        screen.blit(header, (margin_x, 20))
        brand = f['micro'].render("StrikeFactor 0.1", True, DIM)
        screen.blit(brand, (screen_w - margin_x - brand.get_width(), 20))
        pygame.draw.line(screen, DIVIDER,
                         (margin_x, 44), (screen_w - margin_x, 44), 1)

        # Subhead + headline
        sub = f['micro'].render("9 INN · CHOOSE YOUR OPPONENT", True, DIM)
        screen.blit(sub, (margin_x, 64))
        head = f['huge'].render("STEP IN.", True, FG)
        screen.blit(head, (margin_x, 84))

        # Career record (top-right under brand) — only show when present.
        record = GameDayManager.get_career_record()
        if record['total'] > 0:
            record_text = (f"RECORD  {record['wins']}W · "
                           f"{record['losses']}L · {record['ties']}T")
            rec_surf = f['small'].render(record_text, True, FG)
            screen.blit(rec_surf,
                        (screen_w - margin_x - rec_surf.get_width(), 92))

        # Pitcher carousel card
        self.carousel.render(screen, self.CARD_RECT)


class GameDayTransitionState(GameState):
    """Handles transitions between player innings and opponent simulation."""

    # Right-aligned button column (matches the new GameDay layout).
    _BTN_PRIMARY_RECT = (780, 600, 440, 44)   # NEXT INNING / STEP IN / NEXT GAME
    _BTN_SECONDARY_RECT = (780, 650, 210, 32)  # GAME LOG

    def __init__(self, game):
        super().__init__(game)
        self.phase = "SHOW_SCORE"  # Phases: SHOW_SCORE, SIMULATING, FINAL
        self.simulation_complete = False
        self.opponent_events = []
        self._game_log_window = None
        self._labels = []  # Track UILabels for cleanup
        self._gd_fonts = None  # Lazy-init layout fonts

    def _place_button(self, btn, rect):
        btn.set_relative_position(rect[:2])
        btn.set_dimensions(rect[2:])

    def _setup_phase_ui(self):
        """Position buttons and set visibility based on current phase."""
        ui = self.game.ui_manager
        primary = self._BTN_PRIMARY_RECT
        secondary = self._BTN_SECONDARY_RECT

        if self.phase == "FINAL":
            ui.set_visibility_state('gameday_final')
            self._place_button(ui.buttons['final_menu'], primary)
            self._place_button(ui.buttons['view_game_log'], secondary)
        elif self.phase == "SIMULATING":
            ui.set_visibility_state('gameday_simulation')
            self._place_button(ui.buttons['start_batting'], primary)
            self._place_button(ui.buttons['view_game_log'], secondary)
        else:
            # SHOW_SCORE phase
            ui.set_visibility_state('gameday_transition')
            self._place_button(ui.buttons['next_inning'], primary)
            self._place_button(ui.buttons['view_game_log'], secondary)

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
        gameday_mgr = self.game.gameday_manager
        if gameday_mgr.game_over or gameday_mgr.is_walkoff:
            # Game is decided (regulation, extras, or walk-off)
            self.phase = "FINAL"
            self._save_result_once()
        elif gameday_mgr.is_top_inning:
            # Top of inning - opponent bats first, so simulate now
            self.phase = "SIMULATING"
            self._simulate_opponent_half_inning()
        else:
            # Skip the player's bottom half whenever the home team already
            # leads going into it (regular 9th *or* any extra inning).
            player_already_batted = (
                len(gameday_mgr.player_inning_scores) >= gameday_mgr.current_inning
            )
            if (gameday_mgr.current_inning >= 9
                    and not player_already_batted
                    and gameday_mgr.player_score > gameday_mgr.opponent_score):
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

        # Simulate until 3 outs, checking relief after every batter
        while gameday_mgr.current_outs < 3:
            outcome, runs_scored = gameday_mgr.simulate_opponent_at_bat()
            self.opponent_events.append(f"{gameday_mgr.get_current_batter_name()}: {outcome}" +
                                       (f" ({runs_scored} run{'s' if runs_scored != 1 else ''})" if runs_scored > 0 else ""))

            # Relief check after each batter
            if (gameday_mgr.current_outs < 3
                    and gameday_mgr.should_consider_player_relief_pitcher()):
                new_pitcher = gameday_mgr.substitute_player_relief_pitcher()
                if new_pitcher:
                    self.opponent_events.append(
                        f"Pitching change (Your Team): {new_pitcher.upper()} coming in to pitch")

        # End the opponent's half inning
        gameday_mgr.end_half_inning()

        # Check if game is over before considering between-inning relief
        if gameday_mgr.game_over:
            self.phase = "FINAL"
            self._save_result_once()
            self.game.ui_manager.set_visibility_state('gameday_final')
        else:
            # Between-inning relief check (lower threshold — clean break)
            if gameday_mgr.should_consider_player_relief_pitcher(between_innings=True):
                new_pitcher = gameday_mgr.substitute_player_relief_pitcher()
                if new_pitcher:
                    self.opponent_events.append(
                        f"Pitching change (Your Team): {new_pitcher.upper()} coming in to pitch")

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
        self.game.scorebug.last_pitch_type = ""  # Reset last pitch display for new inning

        # Clear pitch data from previous inning
        self.game.pitch_trajectories = []
        self.game.enhanced_pitch_records = []
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

    # ============================================================
    # Refreshed GameDay layout — monochrome retro/CRT aesthetic.
    # All screens share these constants and helpers.
    # ============================================================
    _SCREEN_W = 1280
    _SCREEN_H = 720
    _MARGIN_X = 40

    # Palette — strict black / white / gray, matches BroadcastHUD.
    _BG = (0, 0, 0)
    _FG = (240, 240, 240)
    _DIM = (140, 140, 140)
    _DIM_SOFT = (90, 90, 90)
    _DIVIDER = (60, 60, 60)
    _HIGHLIGHT_BG = (240, 240, 240)
    _HIGHLIGHT_FG = (10, 10, 10)

    # Hit / out classification reused across screens.
    _HIT_RESULTS = ('SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN')
    _OUT_RESULTS = ('STRIKEOUT', 'FLYOUT', 'GROUNDOUT', 'LINEOUT')
    # Compact labels for notable-play display.
    _HIT_ABBREV = {
        'SINGLE': '1B', 'DOUBLE': '2B', 'TRIPLE': '3B', 'HOME RUN': 'HR',
    }

    def _ensure_fonts(self):
        """Lazily build the pixel font set used by the GameDay layout."""
        if self._gd_fonts is not None:
            return self._gd_fonts
        base = resource_path(get_path("ui/font/8bitoperator_jve.ttf"))
        self._gd_fonts = {
            'micro': pygame.font.Font(base, 14),
            'tiny':  pygame.font.Font(base, 16),
            'small': pygame.font.Font(base, 18),
            'med':   pygame.font.Font(base, 22),
            'big':   pygame.font.Font(base, 30),
            'huge':  pygame.font.Font(base, 60),
            'mega':  pygame.font.Font(base, 110),
        }
        return self._gd_fonts

    # ---- Generic drawing helpers --------------------------------

    def _blit_text(self, screen, text, font, pos, color, align='left'):
        """Render text once and blit it. Returns the blit rect."""
        surf = font.render(text, True, color)
        x, y = pos
        if align == 'right':
            x -= surf.get_width()
        elif align == 'center':
            x -= surf.get_width() // 2
        rect = surf.get_rect(topleft=(x, y))
        screen.blit(surf, rect)
        return rect

    def _draw_top_chrome(self, screen, header_text):
        """Draw the shared header: '=== TITLE ===' top-left, brand top-right,
        plus a thin divider underneath."""
        f = self._ensure_fonts()
        self._blit_text(screen, header_text, f['micro'],
                        (self._MARGIN_X, 20), self._FG)
        self._blit_text(screen, "StrikeFactor 0.1", f['micro'],
                        (self._SCREEN_W - self._MARGIN_X, 20),
                        self._DIM, align='right')
        pygame.draw.line(
            screen, self._DIVIDER,
            (self._MARGIN_X, 44),
            (self._SCREEN_W - self._MARGIN_X, 44), 1)

    # ---- Player batting-line stats (used by SHOW_SCORE + FINAL) -

    def _player_batting_stats(self):
        """Aggregate stats from the event log for the player's batting line."""
        mgr = self.game.gameday_manager
        ab = h = hr = rbi = bb = so = 0
        for event in mgr.event_log:
            if event.is_top:
                continue  # Opponent's at-bat
            if event.result in self._HIT_RESULTS:
                ab += 1
                h += 1
                if event.result == 'HOME RUN':
                    hr += 1
            elif event.result in self._OUT_RESULTS:
                ab += 1
                if event.result == 'STRIKEOUT':
                    so += 1
            elif event.result == 'WALK':
                bb += 1
            rbi += event.runs_scored
        avg = (h / ab) if ab else 0.0
        return {'AB': ab, 'R': mgr.player_score, 'H': h, 'HR': hr,
                'RBI': rbi, 'BB': bb, 'SO': so, 'AVG': avg}

    def _notable_plays(self, limit=3):
        """Return up to `limit` notable plays (extra-base hits & HRs).
        Each item: (inning_label, hit_abbrev, pitcher_name)."""
        mgr = self.game.gameday_manager
        out = []
        ordinals = {1: '1ST', 2: '2ND', 3: '3RD'}
        for event in mgr.event_log:
            if event.is_top:
                continue
            if event.result not in ('DOUBLE', 'TRIPLE', 'HOME RUN'):
                continue
            inn = event.inning
            label = ordinals.get(inn, f"{inn}TH")
            out.append((label, self._HIT_ABBREV[event.result],
                        event.pitcher_name.upper()))
        # Keep most recent / most impactful — just trim to last `limit`.
        return out[-limit:]

    # ---- Linescore (top half of FINAL & transition screens) -----

    _LINESCORE_TEAM_COL_W = 130
    _LINESCORE_INNING_COL_W = 60
    _LINESCORE_TOTAL_COL_W = 60
    _LINESCORE_MIN_INNING_W = 36
    _LINESCORE_MIN_TOTAL_W = 50

    def _linescore_column_widths(self, n_innings: int):
        """Return (team_w, inn_w, tot_w) sized to fit `n_innings` columns
        within the screen margins; shrinks inning/total widths for extras."""
        team_w = self._LINESCORE_TEAM_COL_W
        inn_w = self._LINESCORE_INNING_COL_W
        tot_w = self._LINESCORE_TOTAL_COL_W
        max_w = self._SCREEN_W - 2 * self._MARGIN_X

        # Shrink inning columns first, then totals, until the table fits.
        if team_w + n_innings * inn_w + 3 * tot_w > max_w:
            avail = max_w - team_w - 3 * tot_w
            inn_w = max(self._LINESCORE_MIN_INNING_W, avail // n_innings)
        if team_w + n_innings * inn_w + 3 * tot_w > max_w:
            avail = max_w - team_w - n_innings * inn_w
            tot_w = max(self._LINESCORE_MIN_TOTAL_W, avail // 3)
        return team_w, inn_w, tot_w

    def _draw_linescore(self, screen, x, y, current_inning=None):
        """Draw inning-by-inning linescore with R / H / E totals.
        Auto-expands when the game has gone into extra innings.
        Returns the y position just below the table."""
        f = self._ensure_fonts()
        gm = self.game.gameday_manager
        box = gm.get_box_score_lines()
        plr_hits = sum(ps.hits_allowed for ps in gm.get_opponent_pitcher_stats())
        opp_hits = sum(ps.hits_allowed for ps in gm.get_player_pitcher_stats())

        n_innings = len(box['opponent'])
        team_w, inn_w, tot_w = self._linescore_column_widths(n_innings)
        table_w = team_w + n_innings * inn_w + 3 * tot_w
        row_h = 38

        # Section label — flag extras explicitly.
        label = "LINESCORE"
        if n_innings > 9:
            label = f"LINESCORE  ·  {n_innings} INN"
        self._blit_text(screen, label, f['micro'], (x, y), self._DIM)

        header_y = y + 28
        # Team header
        self._blit_text(screen, "TEAM", f['tiny'],
                        (x, header_y), self._DIM)
        # Inning numbers (centered in column)
        cx = x + team_w
        for i in range(1, n_innings + 1):
            color = self._FG if i == current_inning else self._DIM
            self._blit_text(screen, str(i), f['tiny'],
                            (cx + inn_w // 2, header_y),
                            color, align='center')
            cx += inn_w
        for label in ("R", "H", "E"):
            self._blit_text(screen, label, f['tiny'],
                            (cx + tot_w // 2, header_y),
                            self._DIM, align='center')
            cx += tot_w

        # Header / data divider
        sep_y = header_y + 22
        pygame.draw.line(screen, self._DIVIDER,
                         (x, sep_y), (x + table_w, sep_y), 1)

        # Opponent row
        opp_y = sep_y + 8
        self._draw_linescore_row(
            screen, "OPPONENT", box['opponent'], box['opponent_total'],
            opp_hits, 0, x, opp_y, team_w, inn_w, tot_w, table_w,
            highlight=False)

        # Player row (highlighted with white block)
        plr_y = opp_y + row_h
        self._draw_linescore_row(
            screen, "YOU", box['player'], box['player_total'],
            plr_hits, 0, x, plr_y, team_w, inn_w, tot_w, table_w,
            highlight=True)

        return plr_y + row_h

    def _draw_linescore_row(self, screen, team_label, runs_per_inning,
                            r_total, h_total, e_total,
                            x, y, team_w, inn_w, tot_w, table_w,
                            highlight=False):
        """Render a single linescore row (OPPONENT / YOU). `y` is the row top-y."""
        f = self._ensure_fonts()
        row_h = 36

        if highlight:
            block = pygame.Rect(x - 6, y - 4, table_w + 12, row_h - 4)
            pygame.draw.rect(screen, self._HIGHLIGHT_BG, block)
            text_color = self._HIGHLIGHT_FG
            dim_color = self._HIGHLIGHT_FG
        else:
            text_color = self._FG
            dim_color = self._DIM_SOFT

        # Team label
        self._blit_text(screen, team_label, f['med'],
                        (x, y), text_color)

        # Inning runs (centered in column)
        cx = x + team_w
        for runs in runs_per_inning:
            color = text_color if runs > 0 else dim_color
            self._blit_text(screen, str(runs), f['med'],
                            (cx + inn_w // 2, y),
                            color, align='center')
            cx += inn_w

        # R / H / E (always rendered even if 0)
        for value in (r_total, h_total, e_total):
            self._blit_text(screen, str(value), f['med'],
                            (cx + tot_w // 2, y),
                            text_color, align='center')
            cx += tot_w

    # ---- Stat grid (YOUR LINE) ----------------------------------

    _STATLINE_COLS = ('AB', 'R', 'H', 'HR', 'RBI', 'BB', 'SO', 'AVG')

    def _draw_player_statline(self, screen, x, y, width):
        """Draw the AB / R / H / HR / RBI / BB / SO / AVG grid."""
        f = self._ensure_fonts()
        stats = self._player_batting_stats()

        # Section label
        self._blit_text(screen, "YOUR LINE", f['micro'], (x, y), self._DIM)

        cell_h = 60
        cell_y = y + 22
        n = len(self._STATLINE_COLS)
        cell_w = width // n

        # Outer border
        pygame.draw.rect(screen, self._DIVIDER,
                         pygame.Rect(x, cell_y, cell_w * n, cell_h), 1)

        for i, col in enumerate(self._STATLINE_COLS):
            cx = x + i * cell_w
            # Vertical separator (except first column)
            if i > 0:
                pygame.draw.line(screen, self._DIVIDER,
                                 (cx, cell_y), (cx, cell_y + cell_h), 1)
            # Header (column label)
            self._blit_text(screen, col, f['tiny'],
                            (cx + cell_w // 2, cell_y + 6),
                            self._DIM, align='center')
            # Value
            value = stats[col]
            text = f"{value:.3f}".lstrip('0') if col == 'AVG' else str(value)
            self._blit_text(screen, text, f['big'],
                            (cx + cell_w // 2, cell_y + 24),
                            self._FG, align='center')

        return cell_y + cell_h

    # ---- Notable plays list -------------------------------------

    def _draw_notable_plays(self, screen, x, y, max_width):
        """Bullet list of the player's extra-base hits."""
        f = self._ensure_fonts()
        plays = self._notable_plays()
        if not plays:
            self._blit_text(screen, "NO EXTRA-BASE HITS", f['small'],
                            (x, y), self._DIM_SOFT)
            return

        line_h = 26
        for inn_label, hit, pitcher in plays:
            text = f"{inn_label}  >  {hit}  ·  {pitcher}"
            self._blit_text(screen, text, f['small'],
                            (x, y), self._FG)
            y += line_h

    # ---- Arms faced (right-side pitcher list) -------------------

    def _draw_arms_faced(self, screen, x, y, width):
        """Pitchers faced by the player, with line: NAME (HAND)  IP / K / ER."""
        f = self._ensure_fonts()
        gm = self.game.gameday_manager

        # Section label
        self._blit_text(screen, "ARMS FACED", f['micro'], (x, y), self._DIM)
        y += 26

        from ui.pitcher_carousel import PITCHER_HANDEDNESS

        line_h = 36
        shown = 0
        for ps in gm.get_opponent_pitcher_stats():
            if ps.outs_recorded == 0 and ps.pitch_count == 0:
                continue
            name = ps.name.upper()
            hand = PITCHER_HANDEDNESS.get(ps.name, '')
            hand_letter = 'L' if hand == 'LHP' else 'R' if hand == 'RHP' else ''

            # NAME on the left
            name_rect = self._blit_text(screen, name, f['med'],
                                        (x, y), self._FG)
            # Handedness chip — sits inside the name's vertical band
            # using the smallest font so it reads as a subscript.
            if hand_letter:
                self._blit_text(
                    screen, hand_letter, f['micro'],
                    (name_rect.right + 8, y + name_rect.height - 14),
                    self._DIM)

            # Right-aligned stats: ER first, then K, then IP (matching design)
            right_x = x + width
            er_text = f"ER{ps.runs_allowed}"
            er_rect = self._blit_text(screen, er_text, f['med'],
                                      (right_x, y), self._FG, align='right')
            k_text = f"K{ps.strikeouts}"
            k_x = er_rect.left - 30
            k_rect = self._blit_text(screen, k_text, f['med'],
                                     (k_x, y), self._FG, align='right')
            ip_text = f"{ps.get_ip_display()}IP"
            ip_x = k_rect.left - 30
            self._blit_text(screen, ip_text, f['med'],
                            (ip_x, y), self._FG, align='right')

            y += line_h
            shown += 1

        if shown == 0:
            self._blit_text(screen, "NO PITCHERS FACED", f['small'],
                            (x, y), self._DIM_SOFT)

    # ---- Result-headline copy -----------------------------------

    def _result_text(self):
        """Return (small_subtitle, big_headline) for the current game state."""
        gm = self.game.gameday_manager
        winner = gm.get_winner()
        innings = max(9, gm.current_inning)
        if gm.is_walkoff:
            return f"WALK-OFF · {innings} INN · GAMEDAY", "WALK-OFF!"
        if winner == "Player":
            return f"WIN · {innings} INN · GAMEDAY", "YOU TOOK IT."
        if winner == "Opponent":
            return f"LOSS · {innings} INN · GAMEDAY", "TOUGH ONE."
        return f"DRAW · {innings} INN · GAMEDAY", "STALEMATE."

    # ---- FINAL screen renderer ----------------------------------

    def _render_final(self, screen):
        """Final-screen layout: header, headline + score, linescore,
        YOUR LINE + ARMS FACED columns, notable plays, NEXT GAME button."""
        screen.fill(self._BG)
        f = self._ensure_fonts()
        gm = self.game.gameday_manager

        self._draw_top_chrome(screen, "=== FINAL · GAMEDAY ===")

        # --- Result headline + score ---
        sub, head = self._result_text()
        self._blit_text(screen, sub, f['micro'],
                        (self._MARGIN_X, 64), self._DIM)
        self._blit_text(screen, head, f['huge'],
                        (self._MARGIN_X, 84), self._FG)

        score_text = f"{gm.player_score}-{gm.opponent_score}"
        self._blit_text(screen, score_text, f['mega'],
                        (self._SCREEN_W - self._MARGIN_X, 76),
                        self._FG, align='right')

        # --- Linescore ---
        ls_x = self._MARGIN_X
        ls_y = 200
        bottom_y = self._draw_linescore(screen, ls_x, ls_y)

        # --- Two-column body: YOUR LINE (left) | ARMS FACED (right) ---
        body_y = bottom_y + 28
        col_gap = 60
        left_w = 620
        right_x = self._MARGIN_X + left_w + col_gap
        right_w = self._SCREEN_W - self._MARGIN_X - right_x

        statline_bottom = self._draw_player_statline(
            screen, self._MARGIN_X, body_y, left_w)

        # Notable plays sit just under the stat grid
        self._draw_notable_plays(
            screen, self._MARGIN_X, statline_bottom + 22, left_w)

        self._draw_arms_faced(screen, right_x, body_y, right_w)

    # ---- SHOW_SCORE / SIMULATING screen renderer ----------------

    def _render_active(self, screen):
        """Mid-game transition screen (between innings or after sim).
        Header + linescore + active pitcher + recent events."""
        screen.fill(self._BG)
        f = self._ensure_fonts()
        gm = self.game.gameday_manager

        if self.phase == "SIMULATING":
            header = "=== OPPONENT BATTING · GAMEDAY ==="
        else:
            header = "=== BETWEEN INNINGS · GAMEDAY ==="
        self._draw_top_chrome(screen, header)

        # --- Inning + score ---
        half = "TOP" if gm.is_top_inning else "BOT"
        inning_label = f"{half} {gm.current_inning} · {gm.current_outs} OUT"
        self._blit_text(screen, inning_label, f['micro'],
                        (self._MARGIN_X, 64), self._DIM)

        # Big inning text on the left
        if gm.is_top_inning:
            head = f"INNING {gm.current_inning}"
        else:
            head = f"INNING {gm.current_inning}"
        self._blit_text(screen, head, f['huge'],
                        (self._MARGIN_X, 84), self._FG)

        # Score on the right
        score_text = f"{gm.player_score}-{gm.opponent_score}"
        self._blit_text(screen, score_text, f['mega'],
                        (self._SCREEN_W - self._MARGIN_X, 76),
                        self._FG, align='right')

        # --- Linescore ---
        bottom_y = self._draw_linescore(
            screen, self._MARGIN_X, 200,
            current_inning=gm.current_inning)

        # --- Active pitcher (left) + Recent events (right) ---
        body_y = bottom_y + 28
        self._draw_active_pitcher(screen, self._MARGIN_X, body_y, 600)
        self._draw_recent_events(screen, 720, body_y,
                                 self._SCREEN_W - 720 - self._MARGIN_X)

    def _draw_active_pitcher(self, screen, x, y, width):
        """Show the opponent's currently-active pitcher and fatigue."""
        f = self._ensure_fonts()
        gm = self.game.gameday_manager
        ps = gm.get_active_pitcher_stats()

        self._blit_text(screen, "ON THE MOUND", f['micro'], (x, y), self._DIM)
        y += 26

        from ui.pitcher_carousel import PITCHER_HANDEDNESS
        hand = PITCHER_HANDEDNESS.get(ps.name, '')
        hand_letter = 'L' if hand == 'LHP' else 'R' if hand == 'RHP' else ''

        name_rect = self._blit_text(screen, ps.name.upper(), f['big'],
                                    (x, y), self._FG)
        if hand_letter:
            self._blit_text(screen, hand_letter, f['micro'],
                            (name_rect.right + 10, y + name_rect.height - 14),
                            self._DIM)
        y += name_rect.height + 6

        fatigue = ps.get_fatigue_label() if hasattr(ps, 'get_fatigue_label') else ''
        line = f"{ps.pitch_count} PC  ·  {ps.get_ip_display()} IP  ·  {fatigue.upper()}"
        self._blit_text(screen, line, f['small'], (x, y), self._DIM)

        # Player batting line (compact)
        stats = self._player_batting_stats()
        y += 36
        self._blit_text(screen, "YOUR LINE", f['micro'], (x, y), self._DIM)
        y += 22
        avg_str = f"{stats['AVG']:.3f}".lstrip('0') if stats['AB'] else "---"
        line = (f"{stats['H']}/{stats['AB']}  ·  AVG {avg_str}  ·  "
                f"{stats['HR']} HR  ·  {stats['RBI']} RBI")
        self._blit_text(screen, line, f['small'], (x, y), self._FG)

    def _draw_recent_events(self, screen, x, y, width):
        """Recent at-bat results (most recent first)."""
        f = self._ensure_fonts()
        gm = self.game.gameday_manager

        if self.phase == "SIMULATING" and self.simulation_complete:
            self._blit_text(screen, "OPPONENT AT-BATS",
                            f['micro'], (x, y), self._DIM)
            y += 26
            for ev_str in self.opponent_events[-6:]:
                self._blit_text(screen, ev_str.upper(), f['small'],
                                (x, y), self._FG)
                y += 26
            return

        events = gm.get_recent_events(6)
        if not events:
            return

        self._blit_text(screen, "RECENT AT-BATS", f['micro'], (x, y), self._DIM)
        y += 26
        for ev in events:
            text = self._format_event(ev)
            self._blit_text(screen, text, f['small'], (x, y), self._FG)
            y += 26

    def _format_event(self, ev):
        """Compact event line: 'B3 · YOU SINGLE (1R)' / 'T7 · J. SMITH HR'."""
        half = 'T' if ev.is_top else 'B'
        if ev.result.startswith("MOUND VISIT"):
            return f"{half}{ev.inning}  ·  {ev.result}".upper()
        runs_str = f"  ({ev.runs_scored}R)" if ev.runs_scored > 0 else ""
        batter = (ev.batter_name or '').upper()
        return f"{half}{ev.inning}  ·  {batter}  {ev.result}{runs_str}"

    # ---- Top-level dispatch -------------------------------------

    def render(self, screen):
        """Render the transition screen."""
        if self.phase == "FINAL":
            self._render_final(screen)
        else:
            self._render_active(screen)
