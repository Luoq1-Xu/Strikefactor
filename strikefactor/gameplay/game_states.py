"""
Game state classes for StrikeFactor baseball simulator.
Each state handles its own rendering, input processing, and state transitions.
"""

import pygame
import pygame.gfxdraw
import pygame_gui
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from gameplay.gameday_manager import GameDayManager
from config import get_path, resource_path
from ui import gameday_theme as gdt
from ui.play_by_play_panel import PlayByPlayPanel


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
        self._message_pause_until = 0

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

        # Handle message progression (non-blocking 500ms pause between messages)
        if (self.active_message < len(self.messages) - 1) and self.done:
            now = pygame.time.get_ticks()
            if getattr(self, '_message_pause_until', 0) == 0:
                self._message_pause_until = now + 500
            elif now >= self._message_pause_until:
                self.active_message += 1
                self.done = False
                self.textoffset += 100
                self.counter = 0
                self.messages_finished += 1
                self._message_pause_until = 0

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
            self._message_pause_until = 0
        
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

            # Handle message progression (non-blocking 500ms pause between messages)
            if (self.active_message < len(self.messages) - 1) and self.done:
                now = pygame.time.get_ticks()
                if getattr(self, '_message_pause_until', 0) == 0:
                    self._message_pause_until = now + 500
                elif now >= self._message_pause_until:
                    self.active_message += 1
                    self.done = False
                    self.textoffset += 100
                    self.counter = 0
                    self.messages_finished += 1
                    self._message_pause_until = 0
            
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
        self._message_pause_until = 0
        
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
            
        # Handle message progression (non-blocking 500ms pause between messages)
        if (self.active_message < len(self.messages) - 1) and self.done:
            now = pygame.time.get_ticks()
            if getattr(self, '_message_pause_until', 0) == 0:
                self._message_pause_until = now + 500
            elif now >= self._message_pause_until:
                self.active_message += 1
                self.done = False
                self.textoffset += 70
                self.counter = 0
                self.messages_finished += 1
                self._message_pause_until = 0
            
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
        self._message_pause_until = 0

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

        # Handle message progression (non-blocking 500ms pause between messages)
        if (self.active_message < len(self.messages) - 1) and self.done:
            now = pygame.time.get_ticks()
            if getattr(self, '_message_pause_until', 0) == 0:
                self._message_pause_until = now + 500
            elif now >= self._message_pause_until:
                self.active_message += 1
                self.done = False
                self.textoffset += 100
                self.counter = 0
                self.messages_finished += 1
                self._message_pause_until = 0

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
            elif event.ui_element == buttons.get('gameday_resume'):
                self.game.enter_gameday_resume()
            elif event.ui_element == buttons.get('gameday_past_games'):
                self.game.enter_gameday_history()
        return True

    def _confirm_selection(self):
        """Commit the chosen starter and advance into the game."""
        starter = self.carousel.get_selected()
        self.game.inning_ended = False
        self.game.start_gameday_with_starter(starter)

    def _ensure_fonts(self):
        """Lazily build the shared GameDay pixel font set."""
        if not hasattr(self, '_gd_fonts') or self._gd_fonts is None:
            self._gd_fonts = gdt.load_fonts()
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
                           f"{record['losses']}L")
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
        self._labels = []  # Track UILabels for cleanup
        self._gd_fonts = None  # Lazy-init layout fonts
        self._pbp = None       # PlayByPlayPanel for the GAME LOG overlay
        self._log_open = False

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

        # One-shot resume hint: restore the saved phase verbatim and skip
        # re-derivation so an already-simulated opponent half (whose events are
        # already in the restored log) isn't replayed a second time.
        resume_phase = self.game._resuming_gameday_phase
        self.game._resuming_gameday_phase = None

        if resume_phase in ("SHOW_SCORE", "SIMULATING"):
            self.phase = resume_phase
        elif gameday_mgr.game_over or gameday_mgr.is_walkoff:
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

        # Persist (or clear) the resumable session at this half-inning boundary.
        # FINAL games move to history (and clear their active session in
        # _save_result_once); every other boundary is a clean resume point.
        if self.phase == "FINAL":
            self.game.clear_gameday_session(gameday_mgr.session_uuid)
        else:
            self.game.autosave_gameday_session(self.phase)

        # Ensure gameplay UI stays hidden (redundant safety)
        self.game.ui_manager.scoreboard.hide()
        self.game.ui_manager.pitch_result.hide()

    def exit(self):
        """Called when exiting this state."""
        self.game.ui_manager.hide_box_score()
        self._clear_labels()
        self._log_open = False

    def update(self, time_delta: float):
        """Update transition logic."""
        pass

    def _save_result_once(self):
        """Save game result exactly once when entering FINAL phase.

        Called from several call sites; gm._result_saved is the authoritative
        per-game flag (reset in GameDayManager.__init__), so honor it here to
        guarantee the DB close and profile save also run only once.
        """
        gm = self.game.gameday_manager
        if gm._result_saved:
            return

        # Grab the open pitch-DB ids BEFORE end_game closes them so we can
        # write them into gameday_history.json as foreign keys.
        from data.pitch_database import PitchDatabaseService
        svc = PitchDatabaseService.get_instance()
        game_id = svc.current_game_id
        session_id = svc.session_id

        gm.save_game_result(game_id=game_id, session_id=session_id)

        # Game is now in history — drop any resumable session for it so it can't
        # be resumed after completion (backstops the FINAL branch in enter()).
        self.game.clear_gameday_session(gm.session_uuid)

        # Close the pitch-DB games row with the final score and result.
        if gm.player_score > gm.opponent_score:
            result_str = "WIN"
        elif gm.player_score < gm.opponent_score:
            result_str = "LOSS"
        else:
            result_str = "TIE"
        self.game._db_end_game_if_open(
            player_score=gm.player_score,
            opponent_score=gm.opponent_score,
            result=result_str,
        )
        # Persist the BatterProfile we built up over this game.
        self.game._save_batter_profile_for_current_bucket()

    def handle_event(self, event):
        """Handle events - button clicks for continuing."""
        self.game.ui_manager.process_events(event)

        if event.type == pygame.QUIT:
            return False

        # The GAME LOG overlay is modal: it owns input until it's closed.
        if self._log_open:
            if self._pbp is not None and self._pbp.handle_event(event):
                return True
            close = (event.type == pygame.KEYDOWN and
                     event.key in (pygame.K_ESCAPE, pygame.K_RETURN))
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                close = close or not self._LOG_RECT.collidepoint(event.pos)
            if close:
                self._close_game_log()
            return True

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
        """Switch the active opponent pitcher after a relief substitution.

        The AI is deliberately *not* reloaded here: PitcherManager already
        attached each pitcher's validated AI (with its pitcher-specific tunnel
        pairs) at startup. Re-reading the pickle mid-game would drop those
        tunnel pairs and throw away every Q-update the reliever had learned so
        far this session — which `save_all_ai()` would then persist over the
        good model on the way back to the menu.
        """
        # Clear fatigue from old pitcher
        self.game.current_pitcher.clear_fatigue_stats()

        # A name the roster doesn't know would silently no-op in
        # set_current_pitcher, leaving the old arm on the mound. Say so rather
        # than letting the sprite and the box score disagree in silence.
        if self.game.pitcher_manager.get_pitcher(pitcher_name) is None:
            print(f"Warning: relief pitcher '{pitcher_name}' is not on the "
                  f"roster; keeping the current sprite on the mound")
        else:
            self.game.pitcher_manager.set_current_pitcher(pitcher_name)
            self.game.current_pitcher = self.game.pitcher_manager.get_current_pitcher()

        # Re-link fatigue tracking to whichever arm the manager now has active,
        # so pitch counts land on the right PitcherStats row either way.
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

    # GAME LOG overlay geometry (panel + its framed backdrop).
    _LOG_RECT = pygame.Rect(90, 70, gdt.SCREEN_W - 180, gdt.SCREEN_H - 190)
    _LOG_PITCHERS_H = 76  # strip under the panel for both bullpens

    def _show_game_log(self):
        """Open the scrollable play-by-play overlay for the live game."""
        gameday_mgr = self.game.gameday_manager
        if self._pbp is None:
            self._pbp = PlayByPlayPanel(self._ensure_fonts())
        self._pbp.set_plays([e.to_dict() for e in gameday_mgr.event_log])
        # Open on the latest action rather than the first inning.
        self._pbp.scroll_to_end()
        self._log_open = True
        # Modal: hide the phase buttons so they can't be clicked through the veil.
        self.game.ui_manager.set_visibility_state('pitching')

    def _close_game_log(self):
        self._log_open = False
        self._setup_phase_ui()

    def _render_game_log_overlay(self, screen):
        """Dim the screen and draw the play-by-play panel on top."""
        f = self._ensure_fonts()
        veil = pygame.Surface((gdt.SCREEN_W, gdt.SCREEN_H), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 215))
        screen.blit(veil, (0, 0))

        rect = self._LOG_RECT
        pygame.draw.rect(screen, gdt.BG, rect)
        pygame.draw.rect(screen, gdt.FG, rect, 1)

        gm = self.game.gameday_manager
        title = (f"GAME LOG   ·   YOU {gm.player_score}"
                 f" - {gm.opponent_score} OPP")
        self._blit_text(screen, title, f['small'],
                        (rect.left, rect.top - 26), gdt.FG)
        self._blit_text(screen, "ESC  ·  CLOSE", f['micro'],
                        (rect.right, rect.top - 22), gdt.DIM, align='right')

        panel_rect = pygame.Rect(rect.left + 10, rect.top + 10,
                                 rect.width - 20, rect.height - 20 - self._LOG_PITCHERS_H)
        self._pbp.draw(screen, panel_rect)
        self._render_log_pitchers(screen, f, panel_rect.bottom + 10, panel_rect)

        self._blit_text(screen, "WHEEL / UP-DOWN  SCROLL      TAB  FILTER",
                        f['micro'], (gdt.SCREEN_W // 2, rect.bottom + 16),
                        gdt.DIM_SOFT, align='center')

    def _render_log_pitchers(self, screen, f, y, panel_rect):
        """Two-column pitching lines (yours / opponent's) under the log."""
        gm = self.game.gameday_manager
        col_w = panel_rect.width // 2
        columns = (
            ("YOUR PITCHERS", gm.get_player_pitcher_stats(), panel_rect.left),
            ("OPPONENT PITCHERS", gm.get_opponent_pitcher_stats(),
             panel_rect.left + col_w),
        )
        for label, stats, x in columns:
            self._blit_text(screen, label, f['micro'], (x, y), gdt.DIM)
            ry = y + 20
            for ps in stats[-2:]:  # most recent two arms per side
                line = (f"{ps.name.upper()}  {ps.get_ip_display()} IP  "
                        f"{ps.hits_allowed} H  {ps.runs_allowed} R  "
                        f"{ps.strikeouts} K  {ps.pitch_count} P")
                self._blit_text(screen, line, f['micro'], (x, ry), gdt.FG)
                ry += 18

    def _return_to_menu(self):
        """Return to main menu."""
        self.game.current_pitcher.clear_fatigue_stats()
        self.game.in_gameday_mode = False
        self.game.gameday_manager = None
        self.game.set_menu_state(0)

    # ============================================================
    # Refreshed GameDay layout — monochrome retro/CRT aesthetic.
    # All screens share these constants and helpers.
    # Palette / fonts / chrome / linescore live in ui/gameday_theme.py so the
    # setup, transition, final, resume, and history screens stay identical.
    # ============================================================
    _SCREEN_W = gdt.SCREEN_W
    _SCREEN_H = gdt.SCREEN_H
    _MARGIN_X = gdt.MARGIN_X

    # Palette — strict black / white / gray, matches BroadcastHUD.
    _BG = gdt.BG
    _FG = gdt.FG
    _DIM = gdt.DIM
    _DIM_SOFT = gdt.DIM_SOFT
    _DIVIDER = gdt.DIVIDER
    _HIGHLIGHT_BG = gdt.HIGHLIGHT_BG
    _HIGHLIGHT_FG = gdt.HIGHLIGHT_FG

    # Hit / out classification reused across screens.
    _HIT_RESULTS = ('SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN')
    _OUT_RESULTS = ('STRIKEOUT', 'FLYOUT', 'GROUNDOUT', 'LINEOUT', 'POP_UP')
    # Compact labels for notable-play display.
    _HIT_ABBREV = {
        'SINGLE': '1B', 'DOUBLE': '2B', 'TRIPLE': '3B', 'HOME RUN': 'HR',
    }

    def _ensure_fonts(self):
        """Lazily build the shared GameDay pixel font set."""
        if self._gd_fonts is None:
            self._gd_fonts = gdt.load_fonts()
        return self._gd_fonts

    # ---- Generic drawing helpers (delegate to shared theme) -----

    def _blit_text(self, screen, text, font, pos, color, align='left'):
        """Render text once and blit it. Returns the blit rect."""
        return gdt.blit_text(screen, text, font, pos, color, align)

    def _draw_top_chrome(self, screen, header_text):
        """Draw the shared header: '=== TITLE ===' top-left, brand top-right,
        plus a thin divider underneath."""
        gdt.draw_top_chrome(screen, header_text, self._ensure_fonts())

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

    def _draw_linescore(self, screen, x, y, current_inning=None):
        """Draw the live game's inning-by-inning linescore with R / H / E.
        Thin adapter over the shared array-fed renderer (ui/gameday_theme).
        Returns the y position just below the table."""
        gm = self.game.gameday_manager
        box = gm.get_box_score_lines()
        # Each side's hits = hits allowed by the pitchers they batted against.
        plr_hits = sum(ps.hits_allowed for ps in gm.get_opponent_pitcher_stats())
        opp_hits = sum(ps.hits_allowed for ps in gm.get_player_pitcher_stats())
        return gdt.draw_linescore_from_arrays(
            screen, x, y, self._ensure_fonts(),
            box['opponent'], box['player'],
            box['opponent_total'], box['player_total'],
            opp_hits=opp_hits, plr_hits=plr_hits,
            current_inning=current_inning)

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

        if self._log_open and self._pbp is not None:
            self._render_game_log_overlay(screen)


def _fmt_iso(iso, fmt):
    """Format an ISO timestamp, tolerating a missing/garbage value."""
    try:
        return datetime.fromisoformat(iso).strftime(fmt)
    except (ValueError, TypeError):
        return '—'


class _GameDayListState(GameState):
    """Shared scaffolding for the paginated GameDay list screens (Resume,
    History).

    Owns fonts, paging, layout, hover/click hit-testing and the shared retro
    chrome. Subclasses supply the items, header/empty text, a per-row content
    renderer, and the activation handler. Page nav + back are pygame_gui
    buttons (``gd_page_prev`` / ``gd_page_next`` / ``gd_list_back``) plus
    Left/Right/Esc keyboard fallbacks; rows are clicked directly.
    """

    PAGE_SIZE = 7
    _LIST_TOP = 150            # y of the first row
    _ROW_STRIDE = 66          # row top-to-top spacing
    _ROW_H = 54               # drawn row height
    _LIST_X = gdt.MARGIN_X
    _LIST_W = gdt.SCREEN_W - 2 * gdt.MARGIN_X

    HEADER = "=== GAMEDAY ==="
    SUBTITLE = ""
    EMPTY_TEXT = "NOTHING HERE YET"
    ACTION_LABEL = "OPEN ›"
    VISIBILITY_STATE = 'gameday_history'

    def __init__(self, game):
        super().__init__(game)
        self._fonts = None
        self.items = []
        self.page = 0
        self._row_rects = []  # list of (pygame.Rect, item) for hit-testing

    # --- fonts ---
    def _f(self):
        if self._fonts is None:
            self._fonts = gdt.load_fonts()
        return self._fonts

    # --- hooks for subclasses ---
    def _load_items(self):
        return []

    def _render_row_content(self, screen, item, rect, fonts, fg):
        """Draw a row's text. `fg` is the foreground color (dimmed on non-hover)."""
        raise NotImplementedError

    def _on_activate(self, item):
        pass

    def _on_back(self):
        # Default: return to the GameDay setup screen.
        self.game.state_manager.change_state('gameday')

    # --- lifecycle ---
    def enter(self):
        self.items = self._load_items()
        self.page = 0
        self.game.ui_manager.set_visibility_state(self.VISIBILITY_STATE)

    def exit(self):
        pass

    def update(self, time_delta: float):
        pass

    # --- paging ---
    def _page_count(self):
        if not self.items:
            return 1
        return (len(self.items) + self.PAGE_SIZE - 1) // self.PAGE_SIZE

    def _page_items(self):
        start = self.page * self.PAGE_SIZE
        return self.items[start:start + self.PAGE_SIZE]

    def next_page(self):
        if self.page < self._page_count() - 1:
            self.page += 1

    def prev_page(self):
        if self.page > 0:
            self.page -= 1

    # --- events ---
    def handle_event(self, event):
        self.game.ui_manager.process_events(event)
        if event.type == pygame.QUIT:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                self.prev_page()
            elif event.key == pygame.K_RIGHT:
                self.next_page()
            elif event.key == pygame.K_ESCAPE:
                self._on_back()

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, item in self._row_rects:
                if rect.collidepoint(event.pos):
                    self._on_activate(item)
                    break

        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            buttons = self.game.ui_manager.buttons
            if event.ui_element == buttons.get('gd_page_prev'):
                self.prev_page()
            elif event.ui_element == buttons.get('gd_page_next'):
                self.next_page()
            elif event.ui_element == buttons.get('gd_list_back'):
                self._on_back()
        return True

    # --- render ---
    def render(self, screen):
        screen.fill(gdt.BG)
        f = self._f()
        gdt.draw_top_chrome(screen, self.HEADER, f)
        if self.SUBTITLE:
            gdt.blit_text(screen, self.SUBTITLE, f['micro'],
                          (gdt.MARGIN_X, 64), gdt.DIM)

        self._row_rects = []

        if not self.items:
            gdt.blit_text(screen, self.EMPTY_TEXT, f['big'],
                          (gdt.SCREEN_W // 2, 320), gdt.DIM, align='center')
            self._render_footer(screen, f)
            return

        mouse = pygame.mouse.get_pos()
        y = self._LIST_TOP
        for item in self._page_items():
            rect = pygame.Rect(self._LIST_X, y, self._LIST_W, self._ROW_H)
            hover = rect.collidepoint(mouse)
            # Row frame — hover gets a faint fill + bright border + action hint.
            if hover:
                pygame.draw.rect(screen, (18, 18, 18), rect)
            pygame.draw.rect(screen, gdt.FG if hover else gdt.DIVIDER, rect, 1)
            self._render_row_content(screen, item, rect, f,
                                     gdt.FG if hover else gdt.DIM)
            # Action affordance on the right.
            gdt.blit_text(screen, self.ACTION_LABEL, f['small'],
                          (rect.right - 18, rect.centery - 9),
                          gdt.FG if hover else gdt.DIM_SOFT, align='right')
            self._row_rects.append((rect, item))
            y += self._ROW_STRIDE

        self._render_footer(screen, f)

    def _render_footer(self, screen, f):
        page_txt = f"PAGE {self.page + 1} / {self._page_count()}"
        gdt.blit_text(screen, page_txt, f['small'],
                      (gdt.SCREEN_W // 2, gdt.SCREEN_H - 92),
                      gdt.FG, align='center')
        hint = "LEFT / RIGHT  PAGE      CLICK A ROW      ESC  BACK"
        gdt.blit_text(screen, hint, f['micro'],
                      (gdt.SCREEN_W // 2, gdt.SCREEN_H - 64),
                      gdt.DIM_SOFT, align='center')


class GameDayResumeState(_GameDayListState):
    """Paginated list of resumable in-progress GameDay games (most-recent-first)."""

    HEADER = "=== GAMEDAY · RESUME ==="
    SUBTITLE = "PICK UP WHERE YOU LEFT OFF"
    EMPTY_TEXT = "NO SAVED GAMES"
    ACTION_LABEL = "RESUME ›"
    VISIBILITY_STATE = 'gameday_resume'

    def _load_items(self):
        from data import gameday_sessions
        return gameday_sessions.load_sessions()

    def _on_activate(self, item):
        self.game.resume_gameday_session(item.get('session_id'))

    def _render_row_content(self, screen, item, rect, fonts, fg):
        cy = rect.centery - fonts['med'].get_height() // 2
        ly = rect.top + 8

        saved = _fmt_iso(item.get('saved_at'), '%m/%d %H:%M')
        inning = item.get('inning', '?')
        half = (item.get('half') or '').upper()
        diff = (item.get('difficulty') or '').upper()
        starter = (item.get('opponent_starter') or '?').upper()
        score = f"YOU {item.get('player_score', 0)}-{item.get('opponent_score', 0)} OPP"

        # Column labels (micro) + values (med), left to right.
        gdt.blit_text(screen, "SAVED", fonts['micro'], (rect.left + 20, ly), gdt.DIM_SOFT)
        gdt.blit_text(screen, saved, fonts['med'], (rect.left + 20, cy + 6), fg)

        gdt.blit_text(screen, f"INN {inning} · {half}", fonts['med'],
                      (rect.left + 240, cy), fg)
        gdt.blit_text(screen, score, fonts['med'], (rect.left + 440, cy), fg)
        gdt.blit_text(screen, diff, fonts['small'],
                      (rect.left + 720, cy + 2), gdt.DIM)
        gdt.blit_text(screen, f"vs {starter}", fonts['small'],
                      (rect.left + 930, cy + 2), gdt.DIM)


class GameDayHistoryState(_GameDayListState):
    """Paginated list of completed GameDay games (most-recent-first) with a
    per-game inning-by-inning detail view."""

    HEADER = "=== GAMEDAY · HISTORY ==="
    SUBTITLE = "YOUR COMPLETED GAMES"
    EMPTY_TEXT = "NO GAMES YET"
    ACTION_LABEL = "VIEW ›"
    VISIBILITY_STATE = 'gameday_history'

    # Detail-view layout: the play-by-play panel fills the space between the
    # linescore and the BACK button (which lives at y=640).
    _PBP_RECT = pygame.Rect(gdt.MARGIN_X, 322,
                            gdt.SCREEN_W - 2 * gdt.MARGIN_X, 302)

    def __init__(self, game):
        super().__init__(game)
        self.selected = None      # a game dict when viewing detail
        self._pbp = None          # lazily-built PlayByPlayPanel
        self._detail_plays = []   # play log for `selected` (resolved once)

    def _load_items(self):
        return GameDayManager.get_history_games()

    @staticmethod
    def _history_hit_totals(item):
        """Return (player_hits, opponent_hits) for a completed game record.

        New records store hit totals directly. Older records can be recovered
        from the pitch database when game/session foreign keys are present.
        """
        player_hits = item.get('player_hits')
        opponent_hits = item.get('opponent_hits')
        if player_hits is not None and opponent_hits is not None:
            return player_hits, opponent_hits

        game_id = item.get('game_id')
        session_id = item.get('session_id')
        if not game_id or not session_id:
            return 0, 0

        try:
            import sqlite3
            db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'strikefactor.db')
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT is_hit, is_top_inning
                FROM pitches
                WHERE game_id = ? AND session_id = ? AND is_hit = 1
                """,
                (game_id, session_id),
            ).fetchall()
        except Exception:
            return 0, 0
        finally:
            try:
                conn.close()
            except Exception:
                pass

        player_hits = sum(1 for row in rows if not row['is_top_inning'])
        opponent_hits = sum(1 for row in rows if row['is_top_inning'])
        return player_hits, opponent_hits

    @staticmethod
    def _play_log_from_game(item):
        log = item.get('play_log') or []
        if log:
            return list(log)

        game_id = item.get('game_id')
        session_id = item.get('session_id')
        if not game_id or not session_id:
            return []

        try:
            import sqlite3
            db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'strikefactor.db')
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    a.ab_id,
                    a.final_outcome,
                    a.pitcher_name,
                    p.inning,
                    p.is_top_inning,
                    MIN(a.created_at) AS ab_created_at,
                    MIN(p.created_at) AS first_pitch_created_at,
                    MAX(p.runs_scored_on_pitch) AS runs_scored_on_pitch
                FROM at_bats a
                JOIN pitches p ON p.ab_id = a.ab_id
                WHERE a.game_id = ? AND a.session_id = ?
                GROUP BY a.ab_id, a.final_outcome, a.pitcher_name, p.inning, p.is_top_inning
                ORDER BY ab_created_at, first_pitch_created_at, a.ab_id
                """,
                (game_id, session_id),
            ).fetchall()
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

        play_log = []
        for index, row in enumerate(rows, start=1):
            play_log.append({
                'play_index': index,
                'inning': row['inning'],
                'is_top': bool(row['is_top_inning']),
                'batter_name': 'Opponent' if row['is_top_inning'] else 'Player',
                'pitcher_name': row['pitcher_name'] or 'Unknown pitcher',
                'result': row['final_outcome'] or 'UNKNOWN',
                'runs_scored': int(row['runs_scored_on_pitch'] or 0),
            })
        return play_log

    def enter(self):
        self.selected = None
        super().enter()

    @staticmethod
    def _glance_stats(play_log):
        """Per-side counting stats derived from the play log, for the
        'AT A GLANCE' block beside the linescore."""
        hits = {'SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN'}
        xbh = {'DOUBLE', 'TRIPLE', 'HOME RUN'}
        stats = {side: dict(ab=0, hr=0, xbh=0, k=0, bb=0)
                 for side in ('you', 'opp')}
        for entry in play_log or []:
            result = str(entry.get('result') or '').replace('_', ' ').upper()
            if result.startswith('MOUND VISIT') or result.startswith('PITCHING CHANGE'):
                continue
            s = stats['opp' if entry.get('is_top') else 'you']
            s['ab'] += 1
            if result in hits:
                if result in xbh:
                    s['xbh'] += 1
                if result == 'HOME RUN':
                    s['hr'] += 1
            elif result == 'STRIKEOUT':
                s['k'] += 1
            elif result in ('WALK', 'HIT BY PITCH'):
                s['bb'] += 1
        return stats

    def _render_glance(self, screen, f, play_log, x, y):
        """Compact YOU/OPP stat table drawn to the right of the linescore."""
        stats = self._glance_stats(play_log)
        you_x, opp_x = x + 210, x + 300

        gdt.blit_text(screen, "AT A GLANCE", f['micro'], (x, y), gdt.DIM)
        gdt.blit_text(screen, "YOU", f['tiny'], (you_x, y + 24), gdt.DIM, align='right')
        gdt.blit_text(screen, "OPP", f['tiny'], (opp_x, y + 24), gdt.DIM, align='right')
        pygame.draw.line(screen, gdt.DIVIDER,
                         (x, y + 46), (opp_x, y + 46), 1)

        rows = (("HOME RUNS", 'hr'), ("EXTRA-BASE HITS", 'xbh'),
                ("STRIKEOUTS", 'k'), ("PLATE APPEARANCES", 'ab'))
        ry = y + 54
        for label, key in rows:
            gdt.blit_text(screen, label, f['tiny'], (x, ry), gdt.DIM)
            gdt.blit_text(screen, str(stats['you'][key]), f['tiny'],
                          (you_x, ry), gdt.FG, align='right')
            gdt.blit_text(screen, str(stats['opp'][key]), f['tiny'],
                          (opp_x, ry), gdt.DIM, align='right')
            ry += 24

    def _panel(self):
        if self._pbp is None:
            self._pbp = PlayByPlayPanel(self._f())
        return self._pbp

    def _on_activate(self, item):
        self.selected = item
        # Resolved once here (it can hit the pitch DB) rather than per frame.
        self._detail_plays = self._play_log_from_game(item)
        self._panel().set_plays(self._detail_plays)
        self.game.ui_manager.set_visibility_state('gameday_history_detail')

    # --- result chip + row ---
    @staticmethod
    def _result_of(item):
        r = (item.get('result') or '').upper()
        return r if r in ('WIN', 'LOSS', 'TIE') else '—'

    def _render_row_content(self, screen, item, rect, fonts, fg):
        cy = rect.centery - fonts['med'].get_height() // 2
        date = _fmt_iso(item.get('date'), '%m/%d/%y')
        result = self._result_of(item)
        score = f"YOU {item.get('player_score', 0)}-{item.get('opponent_score', 0)} OPP"
        diff = (item.get('difficulty') or '').upper()
        starter = (item.get('opponent_starter') or '?').upper()

        gdt.blit_text(screen, date, fonts['med'], (rect.left + 20, cy), fg)
        self._draw_result_chip(screen, fonts, result, rect.left + 170, rect.centery)
        gdt.blit_text(screen, score, fonts['med'], (rect.left + 310, cy), fg)
        gdt.blit_text(screen, diff, fonts['small'],
                      (rect.left + 600, cy + 2), gdt.DIM)
        gdt.blit_text(screen, f"vs {starter}", fonts['small'],
                      (rect.left + 860, cy + 2), gdt.DIM)

    def _draw_result_chip(self, screen, fonts, result, x, cy):
        """WIN renders as an inverted chip; LOSS/TIE as dim text."""
        font = fonts['small']
        if result == 'WIN':
            surf = font.render(result, True, gdt.HIGHLIGHT_FG)
            pad = 8
            chip = pygame.Rect(x - pad, cy - surf.get_height() // 2 - 4,
                               surf.get_width() + 2 * pad, surf.get_height() + 8)
            pygame.draw.rect(screen, gdt.HIGHLIGHT_BG, chip)
            screen.blit(surf, (x, cy - surf.get_height() // 2))
        else:
            gdt.blit_text(screen, result, font, (x, cy - font.get_height() // 2),
                          gdt.DIM)

    # --- detail view overrides ---
    def handle_event(self, event):
        if self.selected is None:
            return super().handle_event(event)

        # Detail view: the play-by-play panel owns scroll/filter input; the
        # only other action is "back" (returns to the list).
        self.game.ui_manager.process_events(event)
        if event.type == pygame.QUIT:
            return False
        if self._panel().handle_event(event):
            return True
        back = (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE)
        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            back = back or (event.ui_element ==
                            self.game.ui_manager.buttons.get('gd_list_back'))
        if back:
            self.selected = None
            self.game.ui_manager.set_visibility_state('gameday_history')
        return True

    def render(self, screen):
        if self.selected is None:
            super().render(screen)
        else:
            self._render_detail(screen, self.selected)

    def _render_detail(self, screen, game):
        screen.fill(gdt.BG)
        f = self._f()
        gdt.draw_top_chrome(screen, "=== GAMEDAY · HISTORY ===", f)

        date = _fmt_iso(game.get('date'), '%B %d, %Y · %H:%M')
        result = self._result_of(game)
        p = game.get('player_score', 0)
        o = game.get('opponent_score', 0)

        # Compact summary block — kept short so the play-by-play gets the space.
        gdt.blit_text(screen, date, f['micro'], (gdt.MARGIN_X, 56), gdt.DIM)
        head = "WIN" if result == 'WIN' else ("LOSS" if result == 'LOSS' else "TIE")
        gdt.blit_text(screen, head, f['huge'], (gdt.MARGIN_X, 72), gdt.FG)
        gdt.blit_text(screen, "FINAL", f['micro'],
                      (gdt.SCREEN_W - gdt.MARGIN_X, 56), gdt.DIM, align='right')
        gdt.blit_text(screen, f"{p}-{o}", f['huge'],
                      (gdt.SCREEN_W - gdt.MARGIN_X, 72), gdt.FG, align='right')

        diff = (game.get('difficulty') or '').upper()
        starter = (game.get('opponent_starter') or '?').upper()
        gdt.blit_text(screen, f"{diff}   ·   OPPONENT STARTER: {starter}",
                      f['small'], (gdt.MARGIN_X, 146), gdt.DIM)

        player_hits, opponent_hits = self._history_hit_totals(game)

        opp = game.get('opponent_inning_scores', []) or []
        plr = game.get('player_inning_scores', []) or []
        # Pad to equal length (history rows can differ if a half was skipped).
        n = max(9, len(opp), len(plr))
        opp = list(opp) + [0] * (n - len(opp))
        plr = list(plr) + [0] * (n - len(plr))
        gdt.draw_linescore_from_arrays(
            screen, gdt.MARGIN_X, 178, f, opp, plr, sum(opp), sum(plr),
            opp_hits=opponent_hits, plr_hits=player_hits,
        )

        if self._detail_plays:
            self._render_glance(screen, f, self._detail_plays, 940, 176)

        self._panel().draw(screen, self._PBP_RECT)

        hint = ("WHEEL / UP-DOWN  SCROLL      TAB  FILTER      "
                "ESC  ·  BACK TO LIST")
        gdt.blit_text(screen, hint, f['micro'],
                      (gdt.SCREEN_W // 2, gdt.SCREEN_H - 64),
                      gdt.DIM_SOFT, align='center')
