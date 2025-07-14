import pygame
import random
import math
from pygame_gui.elements.ui_window import UIWindow
from pygame_gui.elements.ui_image import UIImage
from pygame_gui.elements.ui_window import UIWindow
from pygame_gui.elements.ui_image import UIImage
from pygame_gui.elements.ui_button import UIButton
from pygame_gui.core import ObjectID
from pygame_gui.elements.ui_horizontal_slider import UIHorizontalSlider
import pandas as pd

# Button class
class Button():
    def __init__(self, x, y, image, scale):
        width = image.get_width()
        height = image.get_height()
        self.image = pygame.transform.scale(image, (int(width * scale), int(height * scale)))
        self.rect = self.image.get_rect()
        self.rect.topleft = (x,y)
        self.clicked = False

    def draw(self, screen):
        action = False
        mousepos = pygame.mouse.get_pos()
        
        if self.rect.collidepoint(mousepos):
            if pygame.mouse.get_pressed()[0] == 1 and self.clicked == False:
                self.clicked = True
                action = True
            
        if pygame.mouse.get_pressed()[0] == 0:
            self.clicked = False

        screen.blit(self.image, (self.rect.x, self.rect.y))

        return action
    
# Runner class
class Runner:

    # 0 = Home plate, 1 = First base, 2 = Second base, 3 = Third base
    onBase = False
    base = 0

    def __init__(self, hit_type):
        self.base = hit_type
        if hit_type == 4:
            self.onBase = False
            self.scored = True
        else:
            self.onBase = True
            self.scored = False
        self.speed = random.randint(1, 3)

    def walk(self):
        self.base += 1
        if self.base > 3:
            self.scored = True
            self.onBase = False

    def advance(self, hit):
        self.base += hit
        if self.base > 3:
            self.scored = True
            self.onBase = False

    def extraBases(self, hit):
        self.base += hit + 1
        if self.base > 3:
            self.scored = True
            self.onBase = False

# Scorekeeper class
class ScoreKeeper:

    def __init__(self):
        self.runners = []
        self.bases = ['white', 'white', 'white']
        self.basesfilled = {1: 0, 2: 0, 3: 0}
        self.score = 0

    # Takes in hit_type, then returns tuple of (bases, score)
    def update_hit_event(self, hit_type):
        batter = Runner(hit_type)
        self.runners.append(batter)
        basesFilled = ['white', 'white', 'white']
        scored = 0
        for runner in self.runners[:]:
            if runner != batter:
                self.basesfilled[runner.base] = 0
                runner.advance(hit_type)
            if runner.scored:
                self.runners.remove(runner)
                scored += 1
            else:
                basesFilled[runner.base - 1] = 'yellow'
                self.basesfilled[runner.base] = runner
        self.score += scored
        self.bases = basesFilled
        self.basesfilled[batter.base] = batter
        return (basesFilled, scored)

    def updateScored(self):
        for runner in self.runners[:]:
            if runner.scored:
                self.runners.remove(runner)
                self.score += 1

    def update_walk_event(self):
        batter = Runner(1)
        self.runners.append(batter)
        prevrunner = batter
        base = 1
        while base < 4 and self.basesfilled[base] != 0 :
            currRunner = self.basesfilled[base]
            self.basesfilled[base].walk()
            self.basesfilled[base] = prevrunner
            prevrunner = currRunner
            base += 1
        self.basesfilled[base] = prevrunner
        self.bases = ['white' if base == 0
                            else 'yellow' for base in self.basesfilled.values()]
        self.updateScored()

    def get_bases(self):
        return self.bases
    
    def isRunnerOnBase(self, base):
        return self.basesfilled[base] != 0

    def get_score(self):
        return self.score

    def reset(self):
        self.runners = []
        self.bases = ['white', 'white', 'white']
        self.basesfilled = {1: 0, 2: 0, 3: 0}
        self.score = 0

    def get_runners_on_base(self):
        return len(self.runners)

# Data Visualisation Window Class
class StatSwing(UIWindow):

    def __init__(self, 
                 position, 
                 ui_manager, 
                 pitch_trajectories=[], 
                 last_pitch_information=[]):
        super().__init__(pygame.Rect(position, (900, 640)), ui_manager,
                         window_display_title='PitchViz',
                         object_id=ObjectID(object_id='#stat_swing_window'),)

        self.parent_ui_manager = ui_manager
        game_surface_size = self.get_container().get_size()
        self.game_surface_size = game_surface_size
        self.strikezone = pygame.Rect(((game_surface_size[0]/2 - 65), 
                                       (game_surface_size[1]/2 - 75)), 
                                       (130, 150))
        self.game_surface_element = UIImage(pygame.Rect((0, 0),
                                                        game_surface_size),
                                            pygame.Surface(game_surface_size).convert(),
                                            manager=ui_manager,
                                            container=self,
                                            parent_element=self)
        self.add_sliders()
        self.add_button()
        self.draw_static()
        self.pitch_trajectories = pitch_trajectories
        self.last_pitch_information = last_pitch_information

        self.clock = pygame.time.Clock()
        self.x = 0
        self.last_time = pygame.time.get_ticks()

    def on_close_window_button_pressed(self):
        return super().hide()

    def draw_static(self):
        # Get the surface of the game_surface_element
        surface = self.game_surface_element.image

        # Fill the surface with a background color
        surface.fill("black")

        x = (self.game_surface_size[0]/2 - 65)
        y = (self.game_surface_size[1]/2 + 250)
        pygame.draw.polygon(surface, "white", ((x, y), (x + 130, y), (x + 130, y + 10), (x + 65, y + 25), (x, y + 10)), 0)
        pygame.draw.rect(surface, "white", self.strikezone, 1)
        self.game_surface_element.image = surface

    def add_button(self):
        # Create a button and add it to the window's container
        self.button = UIButton(relative_rect=pygame.Rect((10, 10), (100, 50)),
                               text='Toggle',
                               manager=self.ui_manager,
                               container=self)

    def add_sliders(self):
        self.pitch_slider = UIHorizontalSlider(relative_rect=pygame.Rect((10, 490), (300, 50)),
                                         start_value=1,
                                         value_range=(0.0, 1.0),
                                         manager=self.ui_manager,
                                         container=self)
        self.num_slider = UIHorizontalSlider(relative_rect=pygame.Rect((10, 550), (300, 50)),
                                         start_value=1,
                                         value_range=(0.0, 1.0),
                                         manager=self.ui_manager,
                                         container=self)

    def display_pitches(self, x):
        # Get the surface of the game_surface_element
        surface = self.game_surface_element.image

        # Fill the surface with a background color
        surface.fill("black")
        pygame.draw.rect(surface, "white", self.strikezone, 1)

        x_diff = 565 - (self.game_surface_size[0]/2 - 65)
        y_diff = 410 - (self.game_surface_size[1]/2 - 75)

        # Calculate the starting index and number of pitches to display
        total_pitches = len(self.pitch_trajectories)
        start_index = math.ceil(self.pitch_slider.get_current_value() * total_pitches) - 1
        num_of_pitches = math.ceil(self.num_slider.get_current_value() * total_pitches)

        # Ensure start_index is within bounds
        start_index = max(0, min(start_index, total_pitches - 1))

        # Draw selected pitches
        pitches_to_display = self.pitch_trajectories[start_index:start_index + num_of_pitches]
        for pitch in pitches_to_display:
            if x in range(len(pitch)):
                pygame.draw.ellipse(surface,
                                    pitch[x][3],
                                    (int(pitch[x][0]) - x_diff,
                                    int(pitch[x][1]) - y_diff,
                                    int(pitch[x][2]),
                                    int(pitch[x][2])))
            else:
                pygame.draw.ellipse(surface,
                                    pitch[-1][3],
                                    (int(pitch[-1][0]) - x_diff,
                                    int(pitch[-1][1]) - y_diff,
                                    int(pitch[-1][2]),
                                    int(pitch[-1][2])))
        self.game_surface_element.image = surface

    def update_pitch_info(self, pitch_trajectories, last_pitch_information):
        self.pitch_trajectories = pitch_trajectories
        self.last_pitch_information = last_pitch_information

    def update(self, time_delta):
        current_time = pygame.time.get_ticks()
        if len(self.last_pitch_information) > 0:
            if current_time - self.last_time > 20:
                self.x += 1
                self.last_time = current_time
                self.display_pitches(self.x)
            self.x %= len(self.last_pitch_information)
        super().update(time_delta) 

# Asset class to store all assets (images, sounds, etc.)
class AssetEngine:
    def __init__(self):
        self.images = {}
        self.sounds = {}

    def load_image(self, path):
        if path not in self.images:
            self.images[path] = pygame.image.load(path)
        return self.images[path]

    def load_sound(self, path):
        if path not in self.sounds:
            self.sounds[path] = pygame.mixer.Sound(path)
        return self.sounds[path]

class StateEngine:
    def __init__(self):
        self.states = {}

    def add_state(self, name, state):
        self.states[name] = state

    def get_state(self, name):
        return self.states[name]

    def remove_state(self, name):
        del self.states[name]

    def clear_states(self):
        self.states = {}

class GUImanager:
    pass

class PitchDataManager:

    def __init__(self):
        self.records = []

    def insert_row(self, row):
        self.records.append(row)

    def append_to_file(self, file):
        pd.DataFrame(self.records).to_csv(file, mode='a', header=False, index=False)
        print("Data appended to file")

class Ball:
    def __init__(self, images, screen):
        self.true_x = 0
        self.true_y = 0
        self.true_z = 0
        self.size = 0
        self.images = images
        self.screen = screen
        self.projected_x = 0
        self.projected_y = 0
        self.scale = 0

    def set_position(self, x, y, z):
        self.true_x = x
        self.true_y = y
        self.true_z = z
        self.counter = 0

    def set_z(self, z):
        self.true_z = z

    def set_size(self, size):
        self.size = size

    def print_position(self):
        print(f"X: {self.true_x}, Y: {self.true_y}, Z: {self.true_z}")

    def draw(self):
        image = pygame.transform.scale(self.images[self.counter], (self.size, self.size))
        self.screen.blit(image, (self.x, self.y))
        self.counter = (self.counter + 1) % len(self.images)
        return 
    
    def draw_with_pos(self, x, y, size):
        ratio = size / 64
        image = pygame.transform.scale(self.images[self.counter], (int(ratio * 64), int(ratio * 66)))
        self.screen.blit(image, (x  - (29.22 * ratio), y - (32.62 * ratio)))
        self.counter = (self.counter + 1) % len(self.images)
        return
    
    def update_projection_details(self, x, y, scale):
        self.projected_x = x
        self.projected_y = y
        self.scale = scale
    
    def blit_ball_outline(self):
        pygame.gfxdraw.aacircle(self.screen, int(self.projected_x), int(self.projected_y), 11, (255, 255, 255))

    