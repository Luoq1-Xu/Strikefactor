# BasedBall : A baseball batting simulator
import pygame
import pygame.gfxdraw
import pygame_gui
from helpers import ScoreKeeper, PitchDataManager
import sys
import os
import pandas as pd
import pickle
from pitchers.Mcclanahan import Mcclanahan
from pitchers.Sale import Sale
from pitchers.Degrom import Degrom
from pitchers.Yamamoto import Yamamoto
from pitchers.Sasaki import Sasaki
from ai.AI_2 import ERAI

from ui.components import create_pci_cursor, create_ui_manager
from utils.physics import collision
from engine.sound_manager import SoundManager
from gameplay.batter import Batter
from config import get_path, resource_path
from gameplay.field_renderer import FieldRenderer
from gameplay.hit_outcome_manager import HitOutcomeManager
from ui.ui_manager import UIManager

pygame.mixer.pre_init(44100, 16, 2, 4096)
pygame.init()
    
crosshair = create_pci_cursor()
pygame.mouse.set_cursor(crosshair)

# Directory containing AI models
AI_DIR = "ai"

# Load a saved model
model = pickle.load(open(get_path("{}/ai_umpire.pkl".format(AI_DIR)), "rb"))

class Game:

    # Update pitcher stats after game ends?
    update = False
    use_new = True

    records = pd.DataFrame
    batradius = 40

    # Pygame setup
    screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
    clock = pygame.time.Clock()
    icon = pygame.image.load(get_path("assets/images/icon.png")).convert_alpha()
    pygame.display.set_icon(icon)
    pygame.display.set_caption('StrikeFactor 0.1')

    # Stuff for the typing effect in main menu and summary self.screen
    dt = 0
    font = pygame.font.Font(resource_path(get_path("ui/font/8bitoperator_jve.ttf")), 40)
    bigfont = pygame.font.Font(resource_path(get_path("ui/font/8bitoperator_jve.ttf")), 70)
    snip = font.render('', True, 'white')
    counter = 0
    speed = 3

    # Load images
    def loadimg(name,number):
        name = get_path(name)
        counter = 1
        storage = []
        while counter <= number:
            storage.append(pygame.image.load(resource_path(f'{name}{counter}.png')).convert_alpha())
            counter += 1
        return storage
    
    def loadimg_experimental(name,number):
        counter = 1
        storage = []
        name = get_path(name)
        while counter <= number:
            image = pygame.image.load(resource_path(f'{name}{counter}.png')).convert_alpha()
            storage.append(pygame.transform.scale_by(image, 118 / image.get_height()))
            counter += 1
        return storage

    def loadball():
        out = []
        ball_dir = get_path('assets/images/ball')
        for filename in os.listdir(ball_dir):
            out.append(pygame.image.load(f'{ball_dir}/{filename}').convert_alpha())
        return out

    ball = [0, 0, 4600]
    ball_list = loadball()
    rhpos = (490, 453)
    rhpos_high = (497, 405)

    def blitball():
        counter = 0
        def blit(self):
            nonlocal counter
            max_distance = 4600
            min_size = 3
            max_size = 11

            dist = self.ball[2] / max_distance

            # Linear interpolation to calculate the size
            size = min_size + (max_size - min_size) * (1 - dist)
            ratio = size / 54

            image = pygame.transform.scale(self.ball_list[counter], (int(ratio * 64), int(ratio * 66)))
            self.screen.blit(image, (self.ball[0] - (29.22 * ratio), self.ball[1] - (32.62 * ratio)))
            counter = (counter + 1) % len(self.ball_list)
        return blit

    blitfunc = blitball()

    # Initialse Pitchers
    sale = Sale(screen, loadimg)
    degrom = Degrom(screen, loadimg)
    yamamoto = Yamamoto(screen, loadimg)
    sasaki = Sasaki(screen, loadimg)
    mcclanahan = Mcclanahan(screen, loadimg_experimental)
    pitchers = [sale, degrom, yamamoto, sasaki]
    current_pitcher = sale
    if use_new:
        sale_ai = ERAI(sale.get_pitch_names())
        degrom_ai = ERAI(degrom.get_pitch_names())
        yamamoto_ai = ERAI(yamamoto.get_pitch_names())
        sasaki_ai = ERAI(sasaki.get_pitch_names())
        mcclanahan_ai = ERAI(mcclanahan.get_pitch_names())
    else:
        sale_ai = pickle.load(open("{}/sale_ai.pkl".format(AI_DIR), "rb"))
        degrom_ai = pickle.load(open("{}/degrom_ai.pkl".format(AI_DIR), "rb"))
        yamamoto_ai = pickle.load(open("{}/yamamoto_ai.pkl".format(AI_DIR), "rb"))
        sasaki_ai = pickle.load(open("{}/sasaki_ai.pkl".format(AI_DIR), "rb"))
    sale.attach_ai(sale_ai)
    degrom.attach_ai(degrom_ai)
    yamamoto.attach_ai(yamamoto_ai)
    sasaki.attach_ai(sasaki_ai)
    mcclanahan.attach_ai(mcclanahan_ai)

    # State = (outs, strikes, balls, runners_on_base, hits_allowed, score)
    current_state = (0, 0, 0, 0, 0, 0)
    pitch_chosen = None

    # Dictionary of value of outcome
    outcome_value = {
        'strike': 0.5,
        'ball': -0.25,
        'foul': 0.3,
        'strikeout': 2,
        'walk': -1,
        'SINGLE': -1.5,
        'DOUBLE': -2,
        'TRIPLE': -2.5,
        'HOME RUN': -3
    }

    fourseamballsize = 11
    strikezonedrawn = 1
    umpsound = True

    # Global variables for menu and resetting
    menu_state = 0
    just_refreshed = 0
    textfinished = 0

    # Metrics
    strikes = 0
    balls = 0
    current_pitches = 0
    pitchnumber = 0
    currentballs = 0
    currentstrikes = 0
    currentouts = 0
    currentstrikeouts = 0
    currentwalks = 0
    homeruns_allowed = 0
    swing_started = 0
    hits = 0
    last_pitch_type_thrown = None
    first_pitch_thrown = False

    current_gamemode = 0
    pitches_display = []
    pitch_trajectories = []
    last_pitch_information = []

    def __init__(self):
        self.batter = Batter(self.screen)
        self.batter.set_handedness("R")
        self.sound_manager = SoundManager(sound_dir="assets/sounds")
        self.field_renderer = FieldRenderer(self.screen)
        self.scoreKeeper = ScoreKeeper()
        self.pitchDataManager = PitchDataManager()
        self.hit_outcome_manager = HitOutcomeManager(self.scoreKeeper, self.sound_manager)
        self.ui_manager = UIManager(self.screen, (1280, 720), theme_path=get_path("assets/theme.json"))


        # Register button callbacks (click on main menu button -> enter respective game mode)
        self.ui_manager.register_button_callback('sale', lambda: self.enter_gamemode('Sale', self.sale))
        self.ui_manager.register_button_callback('degrom', lambda: self.enter_gamemode('Degrom', self.degrom))
        self.ui_manager.register_button_callback('sasaki', lambda: self.enter_gamemode('Sasaki', self.sasaki))
        self.ui_manager.register_button_callback('yamamoto', lambda: self.enter_gamemode('Yamamoto', self.yamamoto))
        self.ui_manager.register_button_callback('mcclanahan', lambda: self.enter_gamemode('Experimental', self.mcclanahan))
        self.ui_manager.register_button_callback('main_menu', lambda: self.set_menu_state(0)) # If main menu button is clicked, set menu_state to 0

        self.ui_manager.register_button_callback('back_to_main_menu', lambda: self.set_menu_state(0)) # If back to main menu button is clicked, set menu_state to 0
        self.ui_manager.register_button_callback('visualise', lambda: self.set_menu_state('visualise')) # If visualise button is clicked, set menu_state to 'visualise'
        self.ui_manager.register_button_callback('return_to_game', lambda: self.exit_view_pitches()) # If return to game button is clicked, set menu_state to current_gamemode
        self.ui_manager.register_button_callback('view_pitches', lambda: self.enter_view_pitches()) # If view pitches button is clicked, set menu_state to 'view_pitches'
        self.ui_manager.register_button_callback('strikezone', lambda: self.field_renderer.toggle_strikezone_mode()) # If strikezone button is clicked, toggle strikezone mode
        self.ui_manager.register_button_callback('toggle_ump_sound', lambda: self.toggle_ump_sound()) # If toggle ump sound button is clicked, toggle ump sound
        self.ui_manager.register_button_callback('toggle_batter', lambda: self.batter.toggle_handedness()) # If toggle batter button is clicked, toggle batter visibility

        self.run()

    # Draw static components (strikezone, home plate, bases)
    def draw_static(self):
        self.field_renderer.draw_strikezone()
        self.field_renderer.draw_field(self.scoreKeeper.get_bases())
        return
    
    def toggle_ump_sound(self):
        self.umpsound = not self.umpsound

    # Simple function to check self.menu_state and update the display accordingly.
    def check_menu(self):
        if self.currentouts == 3:
            for event in pygame.event.get():
                if event.type == pygame_gui.UI_TEXT_EFFECT_FINISHED:
                    self.textfinished += 1
            if self.textfinished == 3:
                pygame.time.delay(500)
                self.menu_state = 100
        return

    # GAME LOOP FOR END/SUMMARY SCREEN
    def draw_inning_summary(self):

        print("\n <--- INNING SUMMARY ---> \n")
        print(self.current_pitcher.name + " stats")
        self.current_pitcher.update_stats({
            'strikeouts': self.currentstrikeouts,
            'walks': self.currentwalks,
            'hits_allowed': self.hits,
            'outs': self.currentouts,
            'runs': self.scoreKeeper.get_score(),
            'pitch_count': self.current_pitches
        })
        self.current_pitcher.update_basic_stats({
            'strikes': self.strikes,
            'balls': self.balls,
            'strikeouts': self.currentstrikeouts,
            'walks': self.currentwalks,
            'hits_allowed': self.hits,
            'outs': self.currentouts,
            'runs_allowed': self.scoreKeeper.get_score(),
            'home_runs_allowed': self.homeruns_allowed,
            'pitch_count': self.current_pitches
        })
        self.current_pitcher.print_stats()
        print("\n <--- Accumulated Stats ---> \n")
        self.current_pitcher.print_basic_stats()
        print()

        self.textfinished = 0
        done = False
        counter = 0
        textoffset = 0
        messages_finished = 0
        runs_scored = self.scoreKeeper.get_score()
        messages = ["INNING OVER",
                    "HITS : {}".format(self.hits),
                    "WALKS: {}".format(self.currentwalks),
                    "STRIKEOUTS : {}".format(self.currentstrikeouts),
                    "RUNS SCORED : {}".format(runs_scored)]
        active_message = 0
        message = messages[active_message]
        running = True
        self.scoreKeeper.reset()

        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
            mousepos = pygame.mouse.get_pos()
            if pygame.Rect((540,530), (192,29)).collidepoint(mousepos):
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND)
            else:
                pygame.mouse.set_cursor(crosshair)
            full_message = 0
            self.screen.fill("black")
            if self.mainmenubutton.draw(self.screen):
                self.menu_state = 0
                self.first_pitch_thrown = False
                self.just_refreshed = 1
                self.currentballs = 0
                self.currentstrikes = 0
                self.pitchnumber = 0
                self.currentstrikeouts = 0
                self.currentwalks = 0
                self.currentouts = 0
                self.runs_scored = 0
                self.runners = 0
                self.hits = 0
                return
            self.clock.tick(60)/1000.0
            pygame.draw.rect(self.screen, 'white', [(440, 160), (400,300,)], 3)
            if counter < self.speed * len(message):
                counter += 1
            elif counter >= self.speed * len(message):
                done = True
            if (active_message < len(messages) - 1 ) and done:
                pygame.time.delay(500)
                active_message += 1
                done = False
                message = messages[active_message]
                textoffset += 50
                counter = 0
                messages_finished += 1
            if messages_finished > 0:
                offset = 0
                while full_message < messages_finished:
                    oldmessage = self.font.render(messages[full_message], True, 'white')
                    self.screen.blit(oldmessage, (450, 170 + offset))
                    offset += 50
                    full_message += 1
            snip = self.font.render(message[0:counter//self.speed], True, 'white')
            self.screen.blit(snip, (450, 170 + textoffset))
            pygame.display.flip()

        return
    
    def end_of_inning_experimental(self):
        """
        This function is called at the end of an inning in the experimental game mode.
        It displays a summary of the inning and allows the user to return to the main menu.
        """
        print("\n <--- INNING SUMMARY ---> \n")
        print(self.current_pitcher.name + " stats")
        self.current_pitcher.update_stats({
            'strikeouts': self.currentstrikeouts,
            'walks': self.currentwalks,
            'hits_allowed': self.hits,
            'outs': self.currentouts,
            'runs': self.scoreKeeper.get_score(),
            'pitch_count': self.current_pitches
        })
        self.current_pitcher.update_basic_stats({
            'strikes': self.strikes,
            'balls': self.balls,
            'strikeouts': self.currentstrikeouts,
            'walks': self.currentwalks,
            'hits_allowed': self.hits,
            'outs': self.currentouts,
            'runs_allowed': self.scoreKeeper.get_score(),
            'home_runs_allowed': self.homeruns_allowed,
            'pitch_count': self.current_pitches
        })
        self.current_pitcher.print_stats()
        print("\n <--- Accumulated Stats ---> \n")
        self.current_pitcher.print_basic_stats()
        print()

        self.textfinished = 0
        done = False
        counter = 0
        textoffset = 0
        messages_finished = 0
        runs_scored = self.scoreKeeper.get_score()
        messages = [
            "INNING OVER",
            "HITS : {}".format(self.hits),
            "WALKS: {}".format(self.currentwalks),
            "STRIKEOUTS : {}".format(self.currentstrikeouts),
            "RUNS SCORED : {}".format(runs_scored)
        ]
        active_message = 0
        message = messages[active_message]
        running = True
        self.scoreKeeper.reset()

        # Show only the return to main menu button
        self.ui_manager.set_button_visibility('summary')

        while running:
            if self.menu_state != 100:
                # If the game mode has changed, exit the summary
                return

            for event in pygame.event.get():
                self.ui_manager.process_events(event)
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()

            self.screen.fill("black")

            # Typing effect for summary text
            if counter < self.speed * len(message):
                counter += 1
            elif counter >= self.speed * len(message):
                done = True

            # Handle message progression
            if (active_message < len(messages) - 1) and done:
                pygame.time.delay(500)
                active_message += 1
                done = False
                message = messages[active_message]
                textoffset += 70  # Adjust vertical spacing as needed
                counter = 0
                messages_finished += 1

            # Draw completed messages
            if messages_finished > 0:
                offset = 0
                for i in range(messages_finished):
                    self.ui_manager.draw_completed_message(messages[i], (350, 170 + offset), use_big_font=False)
                    offset += 70

            # Draw current message with typing effect
            self.ui_manager.draw_typing_effect(message, counter, self.speed, (350, 170 + textoffset), use_big_font=False)

            # Draw main menu button (if you want to keep the clickable area)
            # If you want to use your UIManager's button, you don't need to draw it manually

            # Update and draw UI elements
            time_delta = self.clock.tick(60) / 1000.0
            self.ui_manager.update(time_delta)
            self.ui_manager.draw()

            pygame.display.flip()

        # Cleanup if needed
        self.cleanUp()

    def enter_gamemode(self, gamemode, pitcher):
        self.menu_state = gamemode
        self.first_pitch_thrown = False
        self.just_refreshed = 1
        self.currentballs = 0
        self.currentstrikes = 0
        self.pitchnumber = 0
        self.currentstrikeouts = 0
        self.currentwalks = 0
        self.currentouts = 0
        self.runs_scored = 0
        self.runners = 0
        self.hits = 0
        self.strikes = 0
        self.balls = 0
        self.current_pitches = 0
        self.homeruns_allowed = 0
        self.current_state = (0, 0, 0, 0, 0, 0)
        self.pitches_display = []
        pygame.mouse.set_cursor(crosshair)
        self.current_pitcher = pitcher
        self.ui_manager.set_button_visibility('in_game')
        return

    def set_menu_state(self, state):
        """
        Set the current menu state.
        This is used to switch between different game modes or return to the main menu.
        """
        self.menu_state = state
        return
    
    def exit_view_pitches(self):
        """
        Exit the view pitches mode and return to the main game.
        This function is called when the user clicks the 'return to game' button.
        """
        self.ui_manager.hide_view_window()
        self.ui_manager.set_button_visibility('in_game')
        self.menu_state = self.current_gamemode
        return
    
    def enter_view_pitches(self):
        """
        Enter the view pitches mode.
        This function is called when the user clicks the 'view pitches' button.
        It updates the UI to show the pitch trajectories and last pitch information.
        """
        self.ui_manager.set_button_visibility('view_pitches')
        self.ui_manager.update_pitch_info(self.pitch_trajectories, self.last_pitch_information)
        self.ui_manager.show_view_window()
        self.menu_state = 'view_pitches'
        return

    def main_menu_experimental(self):
        self.ui_manager.hide_banner()
        self.scoreKeeper.reset()
        running = True
        done = False
        counter = 0
        textoffset = 0
        messages_finished = 0
        self.textfinished = 0
        self.pitch_trajectories = []
        self.last_pitch_information = []

        messages = ["StrikeFactor", "A Baseball At-Bat Simulator"]
        active_message = 0
        message = messages[active_message]

        self.ui_manager.set_button_visibility('main_menu')

        while running:
            if self.menu_state != 0:
                # If the game mode has changed, exit the main menu
                return

            for event in pygame.event.get():
                # Process events through UI manager
                self.ui_manager.process_events(event)
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
    
            # Draw UI
            self.screen.fill("black")

            # Update typing effect for menu text
            if counter < self.speed * len(message):
                counter += 1
            elif counter >= self.speed * len(message):
                done = True
                
            # Handle message progression    
            if (active_message < len(messages) - 1) and done:
                pygame.time.delay(500)
                active_message += 1
                done = False
                message = messages[active_message]
                textoffset += 100
                counter = 0
                messages_finished += 1

            # Draw completed messages
            if messages_finished > 0:
                offset = 0
                for i in range(messages_finished):
                    self.ui_manager.draw_completed_message(messages[i], (300, 170 + offset), use_big_font=True)
                    offset += 100

            # Draw current message with typing effect
            self.ui_manager.draw_typing_effect(message, counter, self.speed, (300, 170 + textoffset), use_big_font=True)

            # Update and draw UI elements
            time_delta = self.clock.tick(60) / 1000.0
            self.ui_manager.update(time_delta)
            self.ui_manager.draw()

            pygame.display.flip()
        
        # Cleanup after if exit the game
        self.cleanUp()

    # GAME LOOP FOR AT-BAT SIMULATION
    def main_simulation(self, release_point, pitchername, ax, ay, vx, vy, traveltime, pitchtype):
        """
            The main simulation function.
            Params:
            release_point
            x axis acceleration
            y axis acceleration
            x axis initial velocity
            y axis initial velocity
            Traveltime
            Pitchtype
        """
        self.ui_manager.hide_banner()
        self.ui_manager.set_button_visibility('pitching')
        running = True
        self.first_pitch_thrown = True
        self.swing_started = 0
        self.ball = [release_point[0], release_point[1], 4600]
        result = None
        soundplayed = 0
        sizz = False
        on_time = 0
        made_contact = "no_swing"
        contact_time = 0
        swing_type = 0
        pitch_results_done = False
        is_strike = False
        is_hit = False
        previous_state = self.current_state
        loops = 0
        recording_state = 0
        new_entry = {
            'Pitcher':pitchername,
            'PitchType':pitchtype,
            'FirstX':0,
            'FirstY':0,
            'SecondX':0,
            'SecondY':0,
            'FinalX':0,
            'FinalY':0,
            'isHit':"false",
            'called_strike':False,
            'foul': False,
            'swinging_strike': False,
            'ball': False,
            'in_zone': False
        }

        new_data_entry = {
            'Pitcher': pitchername,
            'PrevPitch': self.last_pitch_type_thrown,
            'Strikes': self.currentstrikes,
            'Balls': self.currentballs,
            'Outs': self.currentouts,
            'Handedness': self.batter.get_handedness(),
            'RunnerFirst': self.scoreKeeper.isRunnerOnBase(1),
            'RunnerSecond': self.scoreKeeper.isRunnerOnBase(2),
            'RunnerThird': self.scoreKeeper.isRunnerOnBase(3),
            'PitchResult': pitchtype,
        }

        self.last_pitch_information = []
        starttime = pygame.time.get_ticks()
        current_time = starttime
        last_time = starttime
        dist = self.ball[2]/300
        windup = self.current_pitcher.get_windup()
        arrival_time = starttime + windup + traveltime
        ax = ax
        ay = ay
        vx = vx
        vy = vy

        def draw_batter():
            if self.swing_started:
                if self.swing_started == 1:
                    self.batter.swing_start(current_time, swing_starttime)
                else:
                    self.batter.high_swing_start(current_time, swing_starttime)
            elif self.swing_started == 0:
                self.batter.leg_kick(current_time, starttime + windup - 300)

        def update_ball_pos_and_draw():
            nonlocal vx, vy, ax, ay, dist
            dist = self.ball[2]/300
            if dist > 1:
                self.blitfunc()
                self.ball[1] += vy * (1/dist)
                self.ball[2] -= (4300 * 1000)/(60 * traveltime)
                self.ball[0] += vx * (1/dist)
                vy += (ay*300) * (1/dist)
                vx += (ax*300) * (1/dist)

        while running:
            self.sound_manager.update()
            self.screen.fill("black")
            time_delta = self.clock.tick_busy_loop(60)/1000.0
            self.ui_manager.draw()
            self.ui_manager.update(time_delta)
            current_time = pygame.time.get_ticks()
            elapsed_time = current_time - last_time
            self.current_pitcher.draw_pitcher(starttime, current_time)
            if starttime + windup < current_time < arrival_time:
                loops += 1


            # RECORD PITCH TRAJECTORY INFORMATION
            if elapsed_time >= 10 and current_time - starttime > windup or (current_time - starttime > windup and not pitch_results_done):
                last_time = current_time
                if current_time > starttime + traveltime + windup and is_hit:
                    entry = [self.ball[0], self.ball[1], self.fourseamballsize, (71, 204, 252),"hit"]
                elif current_time > starttime + traveltime + windup  and pitch_results_done and is_strike:
                    entry = [self.ball[0], self.ball[1], self.fourseamballsize, (227, 75, 80),"strike"]
                elif current_time > starttime + traveltime + windup  and pitch_results_done and not is_strike:
                    entry = [self.ball[0], self.ball[1], self.fourseamballsize, (75, 227, 148),"ball"]
                else:
                    entry = [self.ball[0], self.ball[1], min(max(11/dist, 4), 11), (255,255,255),""]
                self.last_pitch_information.append(entry)
            if recording_state == 0 and windup < (current_time - starttime) < windup + 200:
                    recording_state += 1
                    new_entry['FirstX'] = self.ball[0]
                    new_entry['FirstY'] = self.ball[1]
            if recording_state == 1 and (current_time - starttime) > 1500:
                    recording_state += 1
                    new_entry['SecondX'] = self.ball[0]
                    new_entry['SecondY'] = self.ball[1]

            # Pitcher Windup
            if current_time <= starttime + windup:
                self.batter.leg_kick(current_time, starttime + windup - 300)
                self.draw_static()
                pygame.display.flip()

            # From time self.ball leaves the hand until self.ball finishes traveling (no contact made yet)
            if ((current_time > starttime + windup
                and current_time < arrival_time
                # Did not swing OR swung and missed
                and (on_time == 0 or (on_time > 0 and made_contact == "swung_and_miss")))
                or (on_time > 0 and current_time <= contact_time and made_contact == "no_swing")):
                if not sizz:
                    sizz = True
                    self.sound_manager.play('sizzle')
                for event in pygame.event.get():
                    if event.type == pygame.KEYDOWN:
                        if current_time < arrival_time - 100:
                            swing_button_pressed_time = current_time
                            #CONTACT SWING
                            if event.key == pygame.K_w and self.swing_started == 0:
                                swing_type = 1
                                mousepos = pygame.mouse.get_pos()
                                #LOW SWING
                                swing_starttime = pygame.time.get_ticks()
                                contact_time = swing_starttime + 150
                                on_time = self.hit_outcome_manager.contact_timing_quality(swing_starttime,starttime,traveltime, windup)
                                if mousepos[1] > 500:
                                    self.swing_started = 1
                                #HIGH SWING
                                else:
                                    self.swing_started = 2
                            #POWER SWING
                            elif event.key == pygame.K_e and self.swing_started == 0:
                                swing_type = 2
                                mousepos = pygame.mouse.get_pos()
                                #LOW SWING
                                swing_starttime = pygame.time.get_ticks()
                                contact_time = swing_starttime + 150
                                on_time = self.hit_outcome_manager.power_timing_quality(swing_starttime,starttime,traveltime, windup)
                                if mousepos[1] > 500:
                                    self.swing_started = 1
                                #HIGH SWING
                                else:
                                    self.swing_started = 2
                draw_batter()
                update_ball_pos_and_draw()
                self.draw_static()
                pygame.display.flip()

                # Ball reach glove
                if (current_time > (arrival_time - 30)
                    and soundplayed == 0 and on_time == 0) or (current_time > contact_time and soundplayed == 0 and (on_time > 0 and made_contact == "swung_and_miss")):
                    self.sound_manager.glovepop()
                    soundplayed += 1

            # CONTACT TIME REACHED, TIMING NOT COMPLETELY OFF, CHECK FOR OUTCOME
            elif (on_time > 0
                  and current_time > contact_time
                  and current_time <= arrival_time + 700
                  and made_contact != "swung_and_miss"):
                draw_batter()
                self.draw_static()
                pygame.gfxdraw.aacircle(self.screen, int(self.ball[0]), int(self.ball[1]), self.fourseamballsize, (255,255,255))
                pygame.display.flip()
                # FOUL BALL TIMING
                if (on_time == 1 and pitch_results_done == False):
                    outcome = self.hit_outcome_manager.get_ball_to_bat_contact_outcome(mousepos, (self.ball[0], self.ball[1]), swing_type, batter_handedness=self.batter.get_handedness())
                    if outcome == 'miss':
                        #TIMING ON BUT SWING PATH OFF (SWING OVER OR UNDER BALL) - MISS
                        made_contact = "swung_and_miss"
                    # TIMING ON AND PATH ON - FOUL BALL
                    else:
                        outcome = 'foul'
                        self.strikes += 1
                        is_strike = True
                        new_entry['foul'] = True
                        made_contact = "fouled"
                        pitch_results_done = True
                        self.pitchnumber += 1
                        if self.currentstrikes < 2:
                            self.currentstrikes += 1 
                        self.ui_manager.clear_pitch_result()
                        string = "<font size=5>PITCH {}: {}<br>FOUL<br>COUNT IS {} - {}</font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                        result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                    self.currentstrikeouts,
                                                                                                                                                    self.currentwalks,
                                                                                                                                                    self.hits,
                                                                                                                                                    self.scoreKeeper.get_score())
                        self.ui_manager.update_pitch_result(string)
                        self.ui_manager.update_scoreboard(result)

                # PERFECT TIMING
                elif (on_time == 2 and pitch_results_done == False):
                        outcome = self.hit_outcome_manager.get_ball_to_bat_contact_outcome(mousepos, (self.ball[0], self.ball[1]), swing_type, batter_handedness=self.batter.get_handedness())
                        # PERFECT TIMING AND LOCATION MISS - MISS
                        if outcome == 'miss':
                            made_contact = "swung_and_miss"
                        # PERFECT TIMING AND SWING PATH ON - SUCCESSFUL HIT
                        else:
                            self.strikes += 1
                            is_hit = True
                            made_contact = "hit"
                            pitch_results_done = True
                            self.pitchnumber += 1
                            self.hits += 1
                            self.pitchnumber = 0
                            self.currentstrikes = 0
                            self.currentballs = 0
                            if swing_type == 1:
                                hit_string = self.hit_outcome_manager.get_power_hit_outcome()
                            elif swing_type == 2:
                                hit_string = self.hit_outcome_manager.get_contact_hit_outcome()
                            if self.hit_outcome_manager.get_homerun_text() != '':
                                self.ui_manager.show_banner("{}".format(self.hit_outcome_manager.get_homerun_text()))
                                self.homeruns_allowed += 1
                            else:
                                self.ui_manager.show_banner("{}".format(hit_string))
                            string = "<font size=5>PITCH {}: {}<br>HIT - {}<br>COUNT IS {} - {}</font>".format(self.pitchnumber, pitchtype, hit_string, self.currentballs, self.currentstrikes)
                            
                            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                    self.currentstrikeouts,
                                                                                                                                                    self.currentwalks,
                                                                                                                                                    self.hits,
                                                                                                                                                    self.scoreKeeper.get_score())
                            self.ui_manager.clear_pitch_result()
                            self.ui_manager.update_pitch_result(string)
                            self.ui_manager.update_scoreboard(result)
                            new_entry['isHit'] = hit_string
                            outcome = hit_string
                # Play Bat Contact Sounds
                if (current_time > contact_time and soundplayed == 0 and pitch_results_done == True):
                    if on_time == 1:
                        self.sound_manager.play('foul')
                        soundplayed += 1
                    elif on_time == 2:
                        self.hit_outcome_manager.play_hit_sound()
                        soundplayed += 1

            # FOLLOW THROUGH IF NO CONTACT MADE (No more swings allowed to start)
            elif (current_time > arrival_time 
                  and current_time <= arrival_time + 700
                  and (on_time == 0 or (on_time > 0 and made_contact == "swung_and_miss"))):
                if (current_time > contact_time and soundplayed == 0 and (on_time > 0 and made_contact == "swung_and_miss")):
                    self.sound_manager.glovepop()
                    soundplayed += 1
                draw_batter()
                self.draw_static()
                pygame.gfxdraw.aacircle(self.screen, int(self.ball[0]), int(self.ball[1]), self.fourseamballsize, (255,255,255))
                pygame.display.flip()
                if pitch_results_done == False:
                    pitch_results_done = True
                    # BALL OUTSIDE THE ZONE AND NOT SWUNG AT - BALL
                    if not model.predict(pd.DataFrame([[self.ball[0], self.ball[1]]], columns=['finalx', 'finaly'])) and self.swing_started == 0:
                        self.balls += 1
                        new_entry['ball'] = True
                        if self.umpsound:
                            self.sound_manager.schedule_sound('ball', delay=200)
                        self.currentballs += 1
                        self.pitchnumber += 1
                        # WALK OCCURS
                        if self.currentballs == 4:
                            outcome = 'walk'
                            self.currentwalks += 1

                            string = "<font size=5>PITCH {}: {}<br>BALL<br>COUNT IS {} - {}<br><b>WALK</b></font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                    self.currentstrikeouts,
                                                                                                                                                    self.currentwalks,
                                                                                                                                                    self.hits,
                                                                                                                                                    self.scoreKeeper.get_score())
                            self.ui_manager.clear_pitch_result()
                            self.ui_manager.update_pitch_result(string)
                            self.ui_manager.update_scoreboard(result)
                            self.ui_manager.show_banner("WALK")
                           

                            # Reset counts after printing result
                            self.currentstrikes = 0
                            self.currentballs = 0
                            self.pitchnumber = 0
                            self.scoreKeeper.update_walk_event()
                            
                        #Normal Ball
                        else:
                            outcome = 'ball'

                            string = "<font size=5>PITCH {}: {}<br>BALL<br>COUNT IS {} - {}</font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                     self.currentstrikeouts,
                                                                                                                                                     self.currentwalks,
                                                                                                                                                     self.hits,
                                                                                                                                                     self.scoreKeeper.get_score())
                            self.ui_manager.clear_pitch_result()
                            self.ui_manager.update_pitch_result(string)
                            self.ui_manager.update_scoreboard(result)
                    # CALLED STRIKE OR SWINGING STRIKE
                    else:
                        self.strikes += 1
                        is_strike = True
                        if collision(self.ball[0], self.ball[1], 11, 630, 482.5, 130, 150):
                            new_entry['in_zone'] = True
                        self.pitchnumber += 1
                        self.currentstrikes += 1
                        # Play Sounds
                        if self.swing_started == 0 and self.currentstrikes == 3 and self.umpsound:
                            self.sound_manager.schedule_sound('strike3', delay=200)
                        elif self.swing_started == 0 and self.currentstrikes != 3 and self.umpsound:
                            self.sound_manager.schedule_sound('strike', delay=200)
                        # STRIKEOUT OCCURS
                        if self.currentstrikes == 3:
                            outcome = 'strikeout'
                            self.currentstrikeouts += 1
                            self.currentouts += 1

                            if self.swing_started == 0:
                                new_entry['called_strike'] = True
                                string = "<font size=5>PITCH {}: {}<br>CALLED STRIKE<br>COUNT IS {} - {}<br><b>STRIKEOUT</b></font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                            else:
                                new_entry['swinging_strike'] = True
                                string = "<font size=5>PITCH {}: {}<br>SWINGING STRIKE<br>COUNT IS {} - {}<br><b>STRIKEOUT</b></font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                    self.currentstrikeouts,
                                                                                                                                                    self.currentwalks,
                                                                                                                                                    self.hits,
                                                                                                                                                    self.scoreKeeper.get_score())

                            self.ui_manager.clear_pitch_result()
                            self.ui_manager.update_pitch_result(string)
                            self.ui_manager.update_scoreboard(result)
                            self.ui_manager.show_banner("STRIKEOUT")

                            # Reset counts after printing result
                            self.pitchnumber = 0
                            self.currentstrikes = 0
                            self.currentballs = 0

                        # Normal Strike
                        else:
                            outcome = 'strike'
                            if self.swing_started == 0:
                                new_entry['called_strike'] = True
                                string = "<font size=5>PITCH {}: {}<br>CALLED STRIKE<br>COUNT IS {} - {}<br></font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                            else:
                                new_entry['swinging_strike'] = True
                                string = "<font size=5>PITCH {}: {}<br>SWINGING STRIKE<br>COUNT IS {} - {}<br></font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                     self.currentstrikeouts,
                                                                                                                                                     self.currentwalks,
                                                                                                                                                     self.hits,
                                                                                                                                                     self.scoreKeeper.get_score())
                            
                            self.ui_manager.clear_pitch_result()
                            self.ui_manager.update_pitch_result(string)
                            self.ui_manager.update_scoreboard(result)


            # END LOOP (END OF PITCH)
            elif current_time > arrival_time + 700:
                running = False
                self.ui_manager.set_button_visibility('in_game')
                pygame.mouse.set_cursor(crosshair)
                new_entry['FinalX'] = self.ball[0]
                new_entry['FinalY'] = self.ball[1]
                if self.records.empty:
                    self.records = pd.DataFrame([new_entry])
                else:
                    self.records = pd.concat([self.records, pd.DataFrame([new_entry])], ignore_index = True)
        
        calculated_loops = traveltime / (0.016 * 1000)

        last_ball = self.last_pitch_information[-1]
        for pitch in self.last_pitch_information:
            if pitch[0] == last_ball[0] and pitch[1] == last_ball[1]:
                pitch[3] = last_ball[3]



        self.last_pitch_type_thrown = pitchtype
        self.pitchDataManager.insert_row(new_data_entry)


        new_state = (self.currentouts, self.currentstrikes, self.currentballs,self.scoreKeeper.get_runners_on_base(), self.hits, self.scoreKeeper.get_score())
        self.current_pitcher.get_ai().update(previous_state, self.pitch_chosen, new_state, self.outcome_value[outcome])
        self.current_state = new_state
        self.pitch_trajectories.append(self.last_pitch_information)
        self.pitches_display.append((self.ball[0], self.ball[1]))
        self.current_pitches += 1
        return (self.ball[0], self.ball[1])

    def visualise_lasttwo_pitch(self):
        current_time = pygame.time.get_ticks()
        last_time = current_time
        if not self.last_pitch_information:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return False
        
        x = 0
        while x <= len(self.last_pitch_information) - 1:
            self.screen.fill("black")
            time_delta = self.clock.tick_busy_loop(60)/1000.0
            self.ui_manager.update(time_delta)
            current_time = pygame.time.get_ticks()
            if x <= len(self.last_pitch_information) - 1:
                for pitch in self.pitch_trajectories:
                    for i in range(x):
                        if i < len(pitch):
                            pygame.draw.ellipse(self.screen,
                                                pitch[i][3],
                                                (int(pitch[i][0]),
                                                int(pitch[i][1]),
                                                int(pitch[i][2]),
                                                int(pitch[i][2])))
                        else:
                            pygame.draw.ellipse(self.screen,
                                                pitch[-1][3],
                                                (int(pitch[-1][0]),
                                                int(pitch[-1][1]),
                                                int(pitch[-1][2]),
                                                int(pitch[-1][2])))
            time_elapsed = current_time - last_time
            if time_elapsed > 25:
                x += 1
                last_time = current_time
            self.draw_static()
            self.batter.draw_stance(1)
            self.process_events()
            self.ui_manager.draw()
            pygame.display.flip()
        return True

    def process_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    self.first_pitch_thrown = True
                    selection = self.current_pitcher.ai.choose_action(self.current_state)
                    self.pitch_chosen = selection
                    self.current_pitcher.pitch(self.main_simulation, selection)
            self.ui_manager.process_events(event)
        return True

    def cleanUp(self):
        # self.pitchDataManager.append_to_file("pitchPredict/data.csv")
        print("DONE")

    # Main Game Loop
    def run(self):
        running = True
        while running:
            time_delta = self.clock.tick(60)/1000.0
            self.ui_manager.update(time_delta)

            self.check_menu()
            if self.menu_state == 0:
                self.main_menu_experimental()
            elif self.menu_state == 100:
                self.end_of_inning_experimental()
            elif self.menu_state == 'visualise':
                self.ui_manager.set_button_visibility('visualise')
                running = self.visualise_lasttwo_pitch()
                self.screen.fill("black")

            # Normal pitcher faceoff mode
            else:
                running = self.process_events()
                self.screen.fill("black")
                self.current_pitcher.draw_pitcher(0,0)
                if self.menu_state == 'view_pitches':
                    self.ui_manager.set_button_visibility('view_pitches')
                    for pitch_pos in self.pitches_display:
                        pygame.gfxdraw.aacircle(self.screen, int(pitch_pos[0]), int(pitch_pos[1]), self.fourseamballsize, (255,255,255))
                if self.just_refreshed == 1:
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts, self.currentstrikeouts, self.currentwalks, self.hits, self.scoreKeeper.get_score())
                    string = "<font size=5><br>COUNT IS {} - {}</font>".format(self.pitchnumber, self.currentballs, self.currentstrikes)
                    self.ui_manager.update_scoreboard(result)
                    self.ui_manager.update_pitch_result(string)
                    self.ui_manager.hide_banner()
                    self.ui_manager.set_button_visibility('in_game')
                    self.just_refreshed = 0
                    self.current_gamemode = self.menu_state
                self.draw_static()
                self.batter.draw_stance(1)
                if self.first_pitch_thrown:
                    pygame.gfxdraw.aacircle(self.screen, int(self.ball[0]), int(self.ball[1]), self.fourseamballsize, (255,255,255))
                self.ui_manager.update(time_delta)
                self.ui_manager.draw()

                pygame.display.flip()

        # Quit cleanup
        self.cleanUp()
        

def main():
    Game()
    pygame.quit()

if __name__ == "__main__":
    main()


