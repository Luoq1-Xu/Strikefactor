# BasedBall : A baseball batting simulator
import pygame
import pygame.gfxdraw
import pygame_gui
import random

import pygame_gui.core.ui_container
import pygame_gui.elements.ui_window
import button
import sys
import os
import pandas as pd
import numpy as np
import pickle
from sklearn.svm import SVC
from Pitchers_Test.Sale import Sale
from Pitchers_Test.Degrom import Degrom
from Pitchers_Test.Yamamoto import Yamamoto
from Pitchers_Test.Sasaki import Sasaki
from db_helper import update_info, get_pitcher_stats
from AI_2 import ERAI
import numpy as np
from pygame_gui.ui_manager import UIManager
from pygame_gui.elements.ui_window import UIWindow
from pygame_gui.elements.ui_image import UIImage

#Setup for Conversion into EXE
def resource_path(relative_path):
    try:
    # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

pygame.mixer.pre_init(44100, 16, 2, 4096)
pygame.init()
    

# Circular PCI cursor
surf2 = pygame.Surface((100, 40), pygame.SRCALPHA)
pygame.gfxdraw.aacircle(surf2, 50, 20, 15, (255,255,255))
pygame.gfxdraw.aacircle(surf2, 50, 20, 30, (255,255,255))
pygame.gfxdraw.aacircle(surf2, 50, 20, 31, (255,255,255))
pygame.gfxdraw.aacircle(surf2, 50, 20, 32, (255,255,255))
crosshair = pygame.cursors.Cursor((40,15), surf2)
pygame.mouse.set_cursor(crosshair)

# Load a saved model
model = pickle.load(open("AI/ai_umpire.pkl", "rb"))

# Directory containing AI models
AI_DIR = "AI_2"

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

    def get_score(self):
        return self.score

    def reset(self):
        self.runners = []
        self.bases = ['white', 'white', 'white']
        self.basesfilled = {1: 0, 2: 0, 3: 0}
        self.score = 0

    def get_runners_on_base(self):
        return len(self.runners)

PONG_WINDOW_SELECTED = pygame.event.custom_type()

class StatSwing(UIWindow):


    def __init__(self, position, ui_manager):
        super().__init__(pygame.Rect(position, (520, 340)), ui_manager,
                         window_display_title='StatSwing',
                         object_id='#view_window')

        game_surface_size = self.get_container().get_size()
        self.game_surface_element = UIImage(pygame.Rect((0, 0),
                                                        game_surface_size),
                                            pygame.Surface(game_surface_size).convert(),
                                            manager=ui_manager,
                                            container=self,
                                            parent_element=self)
        self.is_active = False


class Game:

    # Update pitcher stats after game ends?
    update = False
    use_new = True

    records = pd.DataFrame
    batradius = 40

    # Pygame setup
    screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
    clock = pygame.time.Clock()
    icon = pygame.image.load(resource_path('Images/icon.png')).convert_alpha()
    pygame.display.set_icon(icon)
    pygame.display.set_caption('Basedball Experimental Build')

    # Stuff for the typing effect in main menu and summary self.screen
    dt = 0
    font = pygame.font.Font(resource_path("8bitoperator_jve.ttf"), 40)
    bigfont = pygame.font.Font(resource_path("8bitoperator_jve.ttf"), 70)
    snip = font.render('', True, 'white')
    counter = 0
    speed = 3

    # Load Sounds
    pop1 = pygame.mixer.Sound(resource_path("Sounds/POPSFX.mp3"))
    pop2 = pygame.mixer.Sound(resource_path("Sounds/POP2.mp3"))
    pop3 = pygame.mixer.Sound(resource_path("Sounds/POP3.mp3"))
    pop4 = pygame.mixer.Sound(resource_path("Sounds/POP4.mp3"))
    pop5 = pygame.mixer.Sound(resource_path("Sounds/POP5.mp3"))
    pop6 = pygame.mixer.Sound(resource_path("Sounds/POP6.mp3"))
    strikecall = pygame.mixer.Sound(resource_path("Sounds/STRIKECALL.mp3"))
    ballcall = pygame.mixer.Sound(resource_path("Sounds/BALLCALL.mp3"))
    foulball = pygame.mixer.Sound(resource_path("Sounds/FOULBALL.mp3"))
    single = pygame.mixer.Sound(resource_path("Sounds/SINGLE.mp3"))
    double = pygame.mixer.Sound(resource_path("Sounds/DOUBLE.mp3"))
    triple = pygame.mixer.Sound(resource_path("Sounds/TRIPLE.mp3"))
    homer = pygame.mixer.Sound(resource_path("Sounds/HOMERUN.mp3"))
    called_strike_3 = pygame.mixer.Sound(resource_path("Sounds/strike3.mp3"))
    sizzle = pygame.mixer.Sound(resource_path("Sounds/sss.mp3"))

    # Load images
    def loadimg(name,number):
        counter = 1
        storage = []
        while counter <= number:
            storage.append(pygame.image.load(resource_path(f'{name}{counter}.png')).convert_alpha())
            counter += 1
        return storage

    def loadball():
        out = []
        for filename in os.listdir('ball'):
            out.append(pygame.image.load(f'ball/{filename}').convert_alpha())
        return out

    batter = loadimg('Images/TROUT', 15)
    batterhigh = loadimg('Images/HIGHSWING', 7)
    batterleft = loadimg('Images/TROUTLEFT', 15)
    batterlefthigh = loadimg('Images/HIGHSWINGLEFT', 7)
    ball = [0, 0, 4600]
    ball_list = loadball()

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

    # Buttons for main menu
    salebutton = pygame.image.load(resource_path('Images/salebutton.png')).convert_alpha()
    degrombutton = pygame.image.load(resource_path('Images/degrombutton.png')).convert_alpha()
    sasakibutton = pygame.image.load(resource_path('Images/sasakibutton.png')).convert_alpha()
    yamamotobutton = pygame.image.load(resource_path('Images/yamamotobutton.png')).convert_alpha()
    menu = pygame.image.load(resource_path('Images/MAINMENU.png')).convert_alpha()
    experimental = pygame.image.load(resource_path('Images/experimental.png')).convert_alpha()
    experimentalbutton = button.Button(1050, 650, experimental, 0.5)
    faceoffsasaki = button.Button(600,500,sasakibutton, 0.5)
    faceoffsale = button.Button(400,500, salebutton, 0.5)
    faceoffdegrom = button.Button(400,600, degrombutton, 0.5)
    faceoffyamamoto = button.Button(600,600, yamamotobutton, 0.5)
    mainmenubutton = button.Button(540, 530, menu, 0.6)

    # Initialse Pitchers
    sale = Sale(screen, loadimg)
    degrom = Degrom(screen, loadimg)
    yamamoto = Yamamoto(screen, loadimg)
    sasaki = Sasaki(screen, loadimg)
    pitchers = [sale, degrom, yamamoto, sasaki]
    current_pitcher = sale
    if use_new:
        sale_ai = ERAI(sale.get_pitch_names())
        degrom_ai = ERAI(degrom.get_pitch_names())
        yamamoto_ai = ERAI(yamamoto.get_pitch_names())
        sasaki_ai = ERAI(sasaki.get_pitch_names())
    else:
        sale_ai = pickle.load(open("{}/sale_ai.pkl".format(AI_DIR), "rb"))
        degrom_ai = pickle.load(open("{}/degrom_ai.pkl".format(AI_DIR), "rb"))
        yamamoto_ai = pickle.load(open("{}/yamamoto_ai.pkl".format(AI_DIR), "rb"))
        sasaki_ai = pickle.load(open("{}/sasaki_ai.pkl".format(AI_DIR), "rb"))

    sale.attach_ai(sale_ai)
    degrom.attach_ai(degrom_ai)
    yamamoto.attach_ai(yamamoto_ai)
    sasaki.attach_ai(sasaki_ai)

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

    # Some more setup
    manager = pygame_gui.UIManager((1280, 720), 'theme.json')
    manager.preload_fonts([{'name': 'noto_sans', 'point_size': 18, 'style': 'regular', 'antialiased': '1'},
                           {'name': 'noto_sans', 'point_size': 18, 'style': 'bold', 'antialiased': '1'}])
    player_pos = pygame.Vector2(screen.get_width() / 2, screen.get_height() / 2)
    left_player_pos = pygame.Vector2(screen.get_width() / 2, screen.get_height() / 2)
    strikezone = pygame.Rect((565, 410), (130, 150))
    fourseamballsize = 11
    strikezonedrawn = 1
    umpsound = True
    batter_hand = "R"

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
    scoreKeeper = ScoreKeeper()
    swing_started = 0
    hits = 0
    ishomerun = ''
    first_pitch_thrown = False

    current_gamemode = 0
    pitches_display = []
    pitch_trajectories = []
    last_pitch_information = []

    # POSITION FOR RIGHT BATTER
    x = 330
    y = 190

    # Pygame_gui elements (Buttons, textboxes)
    strikezonetoggle = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((0,100), (200,100)),
                                            text = 'STRIKEZONE',
                                            manager=manager)
    salepitch = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((0, 0), (200,100)),
                                                text = 'PITCH',
                                                manager=manager)
    degrompitch = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((0, 0), (200,100)),
                                                text = 'PITCH',
                                                manager=manager)
    sasakipitch = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((0, 0), (200,100)),
                                                text = 'PITCH',
                                                manager=manager)
    yamamotopitch = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((0, 0), (200,100)),
                                                text = 'PITCH',
                                                manager=manager)
    backtomainmenu = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((0, 620), (200,100)),
                                                text = 'MAIN MENU',
                                                manager=manager)
    toggleumpsound = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((0, 200), (200,100)),
                                                text = 'TOGGLEUMP',
                                                manager=manager)
    seepitches = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((0, 300), (200,100)),
                                                text = 'VIEW PITCHES',
                                                manager=manager)
    return_to_game = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((0, 300), (200,100)),
                                                text = 'RETURN',
                                                manager=manager)
    togglebatter = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((0, 400), (200,100)),
                                                text = 'BATTER',
                                                manager=manager)
    visualise = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((0, 500), (200,100)),
                                                text = 'visualise',
                                                manager=manager)
    container = pygame_gui.core.UIContainer(relative_rect=pygame.Rect((0, 0), (1280,720)),manager=manager, is_window_root_container=False)
    banner = pygame_gui.elements.UILabel(relative_rect=pygame.Rect((340, 0), (600,100)), manager=manager, text="")
    window = pygame_gui.core.ui_container.UIContainer(relative_rect=pygame.Rect((0, 0), (1280,720)),manager=manager, is_window_root_container=True)
    view_window = StatSwing((25, 25), manager)


    def __init__(self):
        self.run()

    def pitchresult(self,input):
        return pygame_gui.elements.UITextBox(input,relative_rect=pygame.Rect((1000, 250), (250,200)),
                                        manager=self.manager)

    def drawscoreboard(self,results):
        return pygame_gui.elements.UITextBox(results,relative_rect=pygame.Rect((1000, 50), (250,200)),
                                            manager=self.manager)

    # Container to house the scoreboard and textbox - to allow for previous instances to be deleted when new ones are created
    def containerupdate(self, textbox, scoreboard):
        self.container.add_element(textbox)
        self.container.add_element(scoreboard)
        return

    # Function to draw bases graphic
    def draw_bases(self):
        bases = self.scoreKeeper.get_bases()
        pygame.draw.polygon(self.screen, bases[0], ((1115, 585), (1140, 610), (1115,635), (1090,610)), 0 if bases[0] == 'yellow' else 1)
        pygame.draw.polygon(self.screen, bases[1], ((1080, 550), (1105, 575), (1080,600), (1055,575)),0 if bases[1] == 'yellow' else 1)
        pygame.draw.polygon(self.screen, bases[2], ((1045, 585), (1070, 610), (1045,635), (1020,610)),0 if bases[2] == 'yellow' else 1)
        return

    def homeplate(self):
        x = 565
        y = 660
        pygame.draw.polygon(self.screen, "white", ((x, y), (x + 130, y), (x + 130, y + 10), (x + 65, y + 25), (x, y + 10)), 0)

    # Draw static components (strikezone, home plate, bases)
    def draw_static(self):
        if self.strikezonedrawn == 2:
            pygame.draw.rect(self.screen, "white", self.strikezone, 1)
        if self.strikezonedrawn == 3:
            pygame.draw.rect(self.screen, "white", self.strikezone, 1)
            pygame.draw.line(self.screen, "white", (565,410 + (150/3)), (694, 410 + (150/3)))
            pygame.draw.line(self.screen, "white", (565,410 + 2*(150/3)), (694, 410 + 2*(150/3)))
            pygame.draw.line(self.screen, "white", (565 + (130/3), 410), (565 + (130/3), 559))
            pygame.draw.line(self.screen, "white", (565 + 2*(130/3), 410), (565 + 2*(130/3), 559))
        self.homeplate()
        self.draw_bases()
        return

    # Simple function to check self.menu_state and update the display accordingly.
    def check_menu(self):
        if self.currentouts == 3:
            for event in pygame.event.get():
                self.manager.process_events(event)
                if event.type == pygame_gui.UI_TEXT_EFFECT_FINISHED:
                    self.textfinished += 1
            if self.textfinished == 3:
                pygame.time.delay(500)
                self.menu_state = 100
        return

    def glovepop(self):
        rand = random.randint(2,5)
        if rand == 2:
            self.pop2.play()
        elif rand == 3:
            self.pop6.play()
        else:
            self.pop5.play()
        return

    def RightBatter(self, number, xoffset=0, yoffset=0):
        self.screen.blit(self.batter[number - 1], (self.x + xoffset, self.y + yoffset))

    def LeftBatter(self, number, xoffset=0, yoffset=0):
        self.screen.blit(self.batterleft[number - 1], (self.x + xoffset,self.y + yoffset))

    def HighSwing(self, number, xoffset=0, yoffset=0):
        self.screen.blit(self.batterhigh[number - 1], (self.x + xoffset, self.y + yoffset))

    def LeftHighSwing(self, number, xoffset=0, yoffset=0):
        self.screen.blit(self.batterlefthigh[number - 1], (self.x + xoffset, self.y + yoffset))

    #Outcomes for a successful contact hit
    def contact_hit_outcome(self):
        rand = random.uniform(0,10)
        if rand > 0 and rand <= 8:
            self.hit_type = 1
            self.update_runners_and_score(1)
            return "SINGLE"
        elif rand > 8 and rand <= 9:
            self.hit_type = 2
            self.update_runners_and_score(2)
            return "DOUBLE"
        elif rand > 9 and rand <= 9.3:
            self.hit_type = 3
            self.update_runners_and_score(3)
            return "TRIPLE"
        elif rand > 9.3 and rand <= 10:
            self.hit_type = 4
            self.update_runners_and_score(4)
            return "HOME RUN"

    #Outcomes for a successful power hit
    def power_hit_outcome(self):
        rand = random.uniform(0,10)
        if rand > 0 and rand <= 3:
            self.hit_type = 1
            self.update_runners_and_score(1)
            return "SINGLE"
        elif rand > 3 and rand <= 6.5:
            self.hit_type = 2
            self.update_runners_and_score(2)
            return "DOUBLE"
        elif rand > 6.5 and rand <= 7.5:
            self.hit_type = 3
            self.update_runners_and_score(3)
            return "TRIPLE"
        elif rand > 7.5 and rand <= 10:
            self.hit_type = 4
            self.update_runners_and_score(4)
            return "HOME RUN"

    #LOGIC FOR UPDATING BASERUNNERS AFTER A HIT
    def update_runners_and_score(self, hit_type):
        self.ishomerun = ''

        scored = self.scoreKeeper.update_hit_event(hit_type)[1]

        if hit_type == 4:
            if scored == 1:
                self.ishomerun = 'SOLO HOME RUN'
            elif scored == 2:
                self.ishomerun = 'TWO-RUN HOME RUN'
            elif scored == 3:
                self.ishomerun = 'THREE-RUN HOME RUN'
            else:
                self.ishomerun = 'GRAND SLAM'

    #Function to check quality of timing
    def powertiming(self, swing_starttime, starttime, traveltime):
        if abs((swing_starttime + 150) - (starttime + traveltime + 1150)) > 15 and abs((swing_starttime + 150) - (starttime + traveltime + 1150)) < 30:
            return 1
        elif abs((swing_starttime + 150) - (starttime + traveltime + 1150)) <= 15:
            return 2
        else:
            return 0

    def contacttiming(self, swing_starttime, starttime, traveltime):
        if abs((swing_starttime + 150) - (starttime + traveltime + 1150)) > 30 and abs((swing_starttime + 150) - (starttime + traveltime + 1150)) < 60:
            return 1
        elif abs((swing_starttime + 150) - (starttime + traveltime + 1150)) <= 30:
            return 2
        else:
            return 0

    # Check for contact based on mouse cursor position when self.ball impacts bat
    def loc_check(self, batpos, ballpos, ballsize=11):
        lol = 1 if self.batter_hand == "R" else -1
        if self.collision(ballpos[0], ballpos[1], ballsize, (batpos[0] - (30 * lol)), (batpos[1]), 120, self.batradius):
            outcome = "hit"
        else:
            outcome = "miss"
        return outcome

    # CREDIT TO e-James -> https://stackoverflow.com/questions/401847/circle-rectangle-self.collision-detection-intersection
    def collision(self, circlex, circley, radius, rectmiddlex, rectmiddley, rectwidth, rectheight):
        circleDistancex = abs(circlex - rectmiddlex)
        circleDistancey = abs(circley - rectmiddley)
        if (circleDistancex > (rectwidth/2 + radius)):
            return False
        if (circleDistancey > (rectheight/2 + radius)):
            return False
        if (circleDistancex <= (rectwidth/2)):
            return True
        if (circleDistancey <= (rectheight/2)):
            return True
        cornerDistance_sq = ((circleDistancex - rectwidth/2)**2) + ((circleDistancey - rectheight/2)**2)
        return (cornerDistance_sq <= ((radius)**2))

    #Low swing animation
    def swing_start(self, timenow, swing_startime):
        if timenow <= swing_startime + 110:
            self.RightBatter(6, 21, 25) if self.batter_hand == 'R' else self.LeftBatter(6, 1,25)
        elif timenow > swing_startime + 110 and timenow <= swing_startime + 150:
            self.RightBatter(7, 7, 84) if self.batter_hand == 'R' else self.LeftBatter(7, -70, 84)
        elif timenow > swing_startime + 150 and timenow <= swing_startime + 200:
            self.RightBatter(8, 12, 84) if self.batter_hand == 'R' else self.LeftBatter(8, -83, 84)
        elif timenow > swing_startime + 200 and timenow <= swing_startime + 210:
            self.RightBatter(9, 12, 84) if self.batter_hand == 'R' else self.LeftBatter(9, 18, 84)
        elif timenow > swing_startime + 210 and timenow <= swing_startime + 225:
            self.RightBatter(10, -150, 84) if self.batter_hand == 'R' else self.LeftBatter(10, 4, 84)
        elif timenow > swing_startime + 225 and timenow <= swing_startime + 240:
            self.RightBatter(11, -177, -69) if self.batter_hand == 'R' else self.LeftBatter(11, 7, -69)
        elif timenow > swing_startime + 240:
            self.RightBatter(12, 28, 48) if self.batter_hand == 'R' else self.LeftBatter(12, -90, 48)
        return

    #Default stance if no swing
    def leg_kick(self, currenttime, start_time):
        if currenttime <= start_time + 50:
            self.RightBatter(1, 0, 0) if self.batter_hand == 'R' else self.LeftBatter(1, 0, 0)
        elif currenttime > start_time + 50 and currenttime <= start_time + 200:
            self.RightBatter(2, 11, -5) if self.batter_hand == 'R' else self.LeftBatter(2, 10, -5)
        elif currenttime > start_time + 200 and currenttime <= start_time + 300:
            self.RightBatter(3, 7, -10) if self.batter_hand == 'R' else self.LeftBatter(3, 8, -10)
        elif currenttime > start_time + 300 and currenttime <= start_time + 475:
            self.RightBatter(4, -21, 11) if self.batter_hand == 'R' else self.LeftBatter(4, -7, 11)
        elif currenttime > start_time + 475 and currenttime <= start_time + 550:
            self.RightBatter(5, -20, 21) if self.batter_hand == 'R' else self.LeftBatter(5, 10, 21)
        elif currenttime > start_time + 550 and currenttime <= start_time + 940:
            self.RightBatter(6, 21, 25) if self.batter_hand == 'R' else self.LeftBatter(6, 1, 25)
        elif currenttime > start_time + 940 and currenttime <= start_time + 1000:
            self.RightBatter(13, 12, 27) if self.batter_hand == 'R' else self.LeftBatter(13, -12, 27)
        elif currenttime > start_time + 1000 and currenttime <= start_time + 1100:
            self.RightBatter(14, 8, 29) if self.batter_hand == 'R' else self.LeftBatter(14, -8, 29)
        elif currenttime > start_time + 1100:
            self.RightBatter(15, 6, 24) if self.batter_hand == 'R' else self.LeftBatter(15, -6, 24)
        return

    #High swing animation
    def high_swing_start(self, timenow, swing_startime):
        if timenow <= swing_startime + 110:
            self.HighSwing(1, 15, 0) if self.batter_hand == 'R' else self.LeftHighSwing(1, -15,0)
        elif timenow > swing_startime + 110 and timenow <= swing_startime + 150:
            self.HighSwing(2, 14, 70) if self.batter_hand == 'R' else self.LeftHighSwing(2, -101, 70)
        elif timenow > swing_startime + 150 and timenow <= swing_startime + 200:
            self.HighSwing(3, 19, 70) if self.batter_hand == 'R' else self.LeftHighSwing(3, -108, 70)
        elif timenow > swing_startime + 200 and timenow <= swing_startime + 210:
            self.HighSwing(4, 14, 70) if self.batter_hand == 'R' else self.LeftHighSwing(4, 22, 70)
        elif timenow > swing_startime + 210 and timenow <= swing_startime + 225:
            self.HighSwing(5, -116, 70) if self.batter_hand == 'R' else self.LeftHighSwing(5, 17, 70)
        elif timenow > swing_startime + 225 and timenow <= swing_startime + 240:
            self.HighSwing(6, -168, -1) if self.batter_hand == 'R' else self.LeftHighSwing(6, -11, -1)
        elif timenow > swing_startime + 240:
            self.HighSwing(7, 31, 70) if self.batter_hand == 'R' else self.LeftHighSwing(7, -176, 70)
        return

    #GAME LOOP FOR END/SUMMARY SCREEN
    def draw_inning_summary(self):

        print()
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
        print("\n <--- Basic Stats ---> \n")
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

    def enter_gamemode(self, gamemode, pitcher):
        self.banner.hide()
        self.container.clear()
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
        self.balls =0
        self.current_pitches = 0
        self.homeruns_allowed = 0
        self.current_state = (0, 0, 0, 0, 0, 0)
        self.pitches_display = []
        pygame.mouse.set_cursor(crosshair)
        self.current_pitcher = pitcher
        return

    #GAME LOOP FOR MAIN MENU
    def main_menu(self):

        self.banner.hide()
        self.scoreKeeper.reset()
        running = True
        done = False
        counter = 0
        textoffset = 0
        messages_finished = 0
        self.textfinished = 0
        self.pitch_trajectories = []
        self.last_pitch_information = []

        messages = ["StrikeFactor",
                    "A Baseball At-Bat Simulator"]

        active_message = 0
        message = messages[active_message]

        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
            mousepos = pygame.mouse.get_pos()
            if (pygame.Rect((400,500), (174,24)).collidepoint(mousepos) or
            pygame.Rect((400,600), (112, 24)).collidepoint(mousepos) or
            pygame.Rect((600,500), (191, 24)).collidepoint(mousepos) or
            pygame.Rect((600,600), (191, 24)).collidepoint(mousepos)):
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND)
            else:
                pygame.mouse.set_cursor(crosshair)
            self.screen.fill("black")
            full_message = 0
            if self.faceoffsale.draw(self.screen):
                self.enter_gamemode('Sale', self.sale)
                return
            elif self.faceoffdegrom.draw(self.screen):
                self.enter_gamemode('Degrom', self.degrom)
                return
            elif self.faceoffsasaki.draw(self.screen):
                self.enter_gamemode('Sasaki', self.sasaki)
                return
            elif self.faceoffyamamoto.draw(self.screen):
                self.enter_gamemode('Yamamoto', self.yamamoto)
                return
            if counter < self.speed * len(message):
                counter += 1
            elif counter >= self.speed * len(message):
                done = True
            if (active_message < len(messages) - 1) and done:
                pygame.time.delay(500)
                active_message += 1
                done = False
                message = messages[active_message]
                textoffset += 100
                counter = 0
                messages_finished += 1
            if messages_finished > 0:
                offset = 0
                while full_message < messages_finished:
                    oldmessage = self.bigfont.render(messages[full_message], True, 'white')
                    self.screen.blit(oldmessage, (300, 170 + offset))
                    offset += 100
                    full_message += 1
            snip = self.bigfont.render(message[0:counter//self.speed], True, 'white')
            self.screen.blit(snip, (300, 170 + textoffset))
            pygame.display.flip()
            self.clock.tick(60)/1000.0

    #GAME LOOP FOR AT-BAT SIMULATION
    def main_simulation(self, release_point, pitchername, ax, ay, vx, vy, traveltime, pitchtype):
        running = True
        self.first_pitch_thrown = True
        self.swing_started = 0
        self.ball = [release_point[0], release_point[1], 4600]
        result = None
        self.hide_buttons()
        soundplayed = 0
        sizz = False
        on_time = 0
        made_contact = 0
        contact_time = 0
        swing_type = 0
        pitch_results_done = False
        is_strike = False
        is_hit = False
        previous_state = self.current_state

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

        self.last_pitch_information = []
        starttime = pygame.time.get_ticks()
        current_time = starttime
        last_time = starttime
        dist = self.ball[2]/300

        while running:
            self.screen.fill("black")
            time_delta = self.clock.tick_busy_loop(60)/1000.0
            current_time = pygame.time.get_ticks()
            elapsed_time = current_time - last_time
            self.current_pitcher.draw_pitcher(starttime, current_time)

            # RECORD PITCH TRAJECTORY INFORMATION
            if elapsed_time >= 10 and current_time - starttime > 1100 or (current_time - starttime > 1100 and not pitch_results_done):
                last_time = current_time
                if current_time > starttime + traveltime + 1100 and is_hit:
                    entry = [self.ball[0], self.ball[1], self.fourseamballsize, (71, 204, 252),"hit"]
                elif current_time > starttime + traveltime + 1100  and pitch_results_done and is_strike:
                    entry = [self.ball[0], self.ball[1], self.fourseamballsize, (227, 75, 80),"strike"]
                elif current_time > starttime + traveltime + 1100  and pitch_results_done and not is_strike:
                    entry = [self.ball[0], self.ball[1], self.fourseamballsize, (75, 227, 148),"ball"]
                else:
                    entry = [self.ball[0], self.ball[1], min(max(11/dist, 4), 11), (255,255,255),""]
                self.last_pitch_information.append(entry)

            if recording_state == 0 and 1100 < (current_time - starttime) < 1300:
                    recording_state += 1
                    new_entry['FirstX'] = self.ball[0]
                    new_entry['FirstY'] = self.ball[1]
            if recording_state == 1 and (current_time - starttime) > 1500:
                    recording_state += 1
                    new_entry['SecondX'] = self.ball[0]
                    new_entry['SecondY'] = self.ball[1]

            #Pitcher Windup
            if current_time <= starttime + 1100:
                self.leg_kick(current_time, starttime + 700)
                self.draw_static()
                self.manager.update(time_delta)
                self.manager.draw_ui(self.screen)
                pygame.display.flip()

            # From time self.ball leaves the hand until self.ball finishes traveling
            if ((current_time > starttime + 1100
                and current_time < starttime + traveltime + 1100
                and (on_time == 0 or (on_time > 0 and made_contact == 1)))
                or (on_time > 0 and current_time <= contact_time and made_contact == 0)):
                if not sizz:
                    sizz = True
                    self.sizzle.play()
                for event in pygame.event.get():
                    if event.type == pygame.KEYDOWN:
                        #CONTACT SWING
                        if event.key == pygame.K_w and self.swing_started == 0:
                            swing_type = 1
                            mousepos = pygame.mouse.get_pos()
                            #LOW SWING
                            if mousepos[1] > 500:
                                swing_starttime = pygame.time.get_ticks()
                                self.swing_started = 1
                                contact_time = swing_starttime + 150
                                on_time = self.contacttiming(swing_starttime,starttime,traveltime)
                            #HIGH SWING
                            elif mousepos[1] < 500:
                                swing_starttime = pygame.time.get_ticks()
                                self.swing_started = 2
                                contact_time = swing_starttime + 150
                                on_time = self.contacttiming(swing_starttime,starttime,traveltime)
                        #POWER SWING
                        elif event.key == pygame.K_e and self.swing_started == 0:
                            swing_type = 2
                            mousepos = pygame.mouse.get_pos()
                            #LOW SWING
                            if mousepos[1] > 500:
                                swing_starttime = pygame.time.get_ticks()
                                self.swing_started = 1
                                contact_time = swing_starttime + 150
                                on_time = self.powertiming(swing_starttime,starttime,traveltime)
                            #HIGH SWING
                            elif mousepos[1] < 500:
                                swing_starttime = pygame.time.get_ticks()
                                self.swing_started = 2
                                contact_time = swing_starttime + 150
                                on_time = self.powertiming(swing_starttime,starttime,traveltime)
                if self.swing_started > 0:
                    timenow = current_time
                    if self.swing_started == 1:
                        self.swing_start(timenow, swing_starttime)
                    else:
                        self.high_swing_start(timenow, swing_starttime)
                elif self.swing_started == 0:
                    self.leg_kick(current_time, starttime + 700)
                dist = self.ball[2]/300
                if dist > 1:
                    self.blitfunc()
                    self.ball[1] += vy * (1/dist)
                    self.ball[2] -= (4300 * 1000)/(60 * traveltime)
                    self.ball[0] += vx * (1/dist)
                    vy += (ay*301) * (1/dist)
                    vx += (ax*301) * (1/dist)
                self.draw_static()
                self.manager.update(time_delta)
                self.manager.draw_ui(self.screen)
                pygame.display.flip()

                # Ball reach glove
                if (current_time > (starttime + traveltime + 1050)
                    and soundplayed == 0 and on_time == 0) or (current_time > contact_time and soundplayed == 0 and (on_time > 0 and made_contact == 1)):
                    self.glovepop()
                    soundplayed += 1

            # BALL HAS CONTACTED BAT
            elif (on_time > 0
                  and current_time > contact_time
                  and current_time <= starttime + traveltime + 1800
                  and made_contact != 1):
                if self.swing_started > 0:
                    timenow = current_time
                    if self.swing_started == 1:
                        self.swing_start(timenow, swing_starttime)
                    else:
                        self.high_swing_start(timenow, swing_starttime)
                elif self.swing_started == 0:
                    self.leg_kick(current_time, starttime + 700)
                pygame.gfxdraw.aacircle(self.screen, int(self.ball[0]), int(self.ball[1]), self.fourseamballsize, (255,255,255))
                self.draw_static()
                self.manager.update(time_delta)
                self.manager.draw_ui(self.screen)
                pygame.display.flip()
                if (made_contact == 0):
                    # FOUL BALL TIMING
                    if (on_time == 1 and pitch_results_done == False):
                        outcome = self.loc_check(mousepos, (self.ball[0], self.ball[1]))
                        if outcome == 'miss':
                            #TIMING ON BUT SWING PATH OFF (SWING OVER OR UNDER BALL) - MISS
                            made_contact = 1
                        #TIMING ON AND PATH ON - FOUL BALL
                        else:
                            outcome = 'foul'
                            self.strikes += 1
                            is_strike = True
                            new_entry['foul'] = True
                            made_contact = 2
                            pitch_results_done = True
                            self.pitchnumber += 1
                            if self.currentstrikes == 2:
                                self.container.clear()
                                string = "<font size=5>PITCH {}: {}<br>FOUL<br>COUNT IS {} - {}</font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                                textbox = self.pitchresult(string)
                                textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                                result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                         self.currentstrikeouts,
                                                                                                                                                         self.currentwalks,
                                                                                                                                                         self.hits,
                                                                                                                                                         self.scoreKeeper.get_score())
                                scoreboard = self.drawscoreboard(result)
                                self.containerupdate(textbox,scoreboard)
                            else:
                                self.currentstrikes += 1
                                self.container.clear()
                                string = "<font size=5>PITCH {}: {}<br>FOUL<br>COUNT IS {} - {}</font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                                textbox = self.pitchresult(string)
                                textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                                result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                         self.currentstrikeouts,
                                                                                                                                                         self.currentwalks,
                                                                                                                                                         self.hits,
                                                                                                                                                         self.scoreKeeper.get_score())
                                scoreboard = self.drawscoreboard(result)
                                self.containerupdate(textbox,scoreboard)
                    # PERFECT TIMING
                    elif (on_time == 2 and pitch_results_done == False):
                        outcome = self.loc_check(mousepos, (self.ball[0], self.ball[1]))
                        #PERFECT TIMING AND LOCATION MISS - MISS
                        if outcome == 'miss':
                            made_contact = 1
                        #PERFECT TIMING AND SWING PATH ON - SUCCESSFUL HIT
                        else:
                            self.strikes += 1
                            is_hit = True
                            self.container.clear()
                            made_contact = 2
                            pitch_results_done = True
                            self.pitchnumber += 1
                            if swing_type == 1:
                                hit_string = self.contact_hit_outcome()
                            elif swing_type == 2:
                                hit_string = self.power_hit_outcome()
                            if self.ishomerun != '':
                                self.banner.set_text("{}".format(self.ishomerun))
                                self.homeruns_allowed += 1
                            else:
                                self.banner.set_text("{}".format(hit_string))
                            self.banner.show()
                            self.banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR,{'time_per_letter': 0.1})
                            string = "<font size=5>PITCH {}: {}<br>HIT - {}<br>COUNT IS {} - {}</font>".format(self.pitchnumber, pitchtype, hit_string, self.currentballs, self.currentstrikes)
                            textbox = self.pitchresult(string)
                            self.hits += 1
                            textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                    self.currentstrikeouts,
                                                                                                                                                    self.currentwalks,
                                                                                                                                                    self.hits,
                                                                                                                                                    self.scoreKeeper.get_score())
                            scoreboard = self.drawscoreboard(result)
                            scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
                            self.containerupdate(textbox, scoreboard)
                            self.pitchnumber = 0
                            self.currentstrikes = 0
                            self.currentballs = 0
                            new_entry['isHit'] = hit_string
                            outcome = hit_string
                # FOLLOW THROUGH - PLAY REST OF SWING ANIMATION
                elif (on_time > 0
                      and made_contact == 2
                      and pitch_results_done == True):
                    #Play sounds
                    if soundplayed == 0 and on_time == 1:
                        self.foulball.play()
                        soundplayed += 1
                    elif soundplayed == 0 and on_time == 2:
                        if self.hit_type == 1:
                            self.single.play()
                        elif self.hit_type == 2:
                            self.double.play()
                        elif self.hit_type == 3:
                            self.triple.play()
                        elif self.hit_type == 4:
                            self.homer.play()
                        soundplayed += 1

            # FOLLOW THROUGH IF NO CONTACT MADE
            elif (current_time > starttime + traveltime + 1100
                  and current_time <= starttime + traveltime + 1800
                  and (on_time == 0 or (on_time > 0 and made_contact == 1))):
                if (current_time > contact_time and soundplayed == 0 and (on_time > 0 and made_contact == 1)):
                    self.glovepop()
                    soundplayed += 1
                if self.swing_started > 0:
                    timenow = current_time
                    if self.swing_started == 1:
                        self.swing_start(timenow, swing_starttime)
                    else:
                        self.high_swing_start(timenow, swing_starttime)
                elif self.swing_started == 0:
                    self.leg_kick(current_time, starttime + 700)
                pygame.gfxdraw.aacircle(self.screen, int(self.ball[0]), int(self.ball[1]), self.fourseamballsize, (255,255,255))
                self.draw_static()
                self.manager.update(time_delta)
                self.manager.draw_ui(self.screen)
                pygame.display.flip()
                if pitch_results_done == False:
                    pitch_results_done = True
                    #BALL OUTSIDE THE ZONE AND NOT SWUNG AT - BALL
                    if not model.predict(pd.DataFrame([[self.ball[0], self.ball[1]]], columns=['finalx', 'finaly'])) and self.swing_started == 0:
                        self.balls += 1
                        new_entry['ball'] = True
                        if self.umpsound:
                            self.ballcall.play()
                        self.currentballs += 1
                        self.pitchnumber += 1
                        #WALK OCCURS
                        if self.currentballs == 4:
                            outcome = 'walk'
                            self.container.clear()
                            string = "<font size=5>PITCH {}: {}<br>BALL<br>COUNT IS {} - {}<br><b>WALK</b></font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                            textbox = self.pitchresult(string)
                            textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                            self.currentwalks += 1
                            self.pitchnumber = 0
                            self.currentstrikes = 0
                            self.currentballs = 0
                            self.scoreKeeper.update_walk_event()
                            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                    self.currentstrikeouts,
                                                                                                                                                    self.currentwalks,
                                                                                                                                                    self.hits,
                                                                                                                                                    self.scoreKeeper.get_score())
                            scoreboard = self.drawscoreboard(result)
                            scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
                            self.containerupdate(textbox,scoreboard)
                            self.banner.set_text("WALK")
                            self.banner.show()
                            self.banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR,{'time_per_letter': 0.1})
                        #Normal Ball
                        else:
                            outcome = 'ball'
                            self.container.clear()
                            string = "<font size=5>PITCH {}: {}<br>BALL<br>COUNT IS {} - {}</font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                            textbox = self.pitchresult(string)
                            textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                     self.currentstrikeouts,
                                                                                                                                                     self.currentwalks,
                                                                                                                                                     self.hits,
                                                                                                                                                     self.scoreKeeper.get_score())
                            scoreboard = self.drawscoreboard(result)
                            self.containerupdate(textbox,scoreboard)
                    #CALLED STRIKE OR SWINGING STRIKE
                    else:
                        self.strikes += 1
                        is_strike = True
                        if self.collision(self.ball[0], self.ball[1], 11, 630, 482.5, 130, 150):
                            new_entry['in_zone'] = True
                        self.pitchnumber += 1
                        self.currentstrikes += 1
                        #Play Sounds
                        if self.swing_started == 0 and self.currentstrikes == 3 and self.umpsound:
                            self.called_strike_3.play()
                        elif self.swing_started == 0 and self.currentstrikes != 3 and self.umpsound:
                            self.strikecall.play()
                        #STRIKEOUT OCCURS
                        if self.currentstrikes == 3:
                            outcome = 'strikeout'
                            self.container.clear()
                            if self.swing_started == 0:
                                new_entry['called_strike'] = True
                                string = "<font size=5>PITCH {}: {}<br>CALLED STRIKE<br>COUNT IS {} - {}<br><b>STRIKEOUT</b></font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                            else:
                                new_entry['swinging_strike'] = True
                                string = "<font size=5>PITCH {}: {}<br>SWINGING STRIKE<br>COUNT IS {} - {}<br><b>STRIKEOUT</b></font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                            textbox = self.pitchresult(string)
                            textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                            self.currentstrikeouts += 1
                            self.currentouts +=1
                            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                    self.currentstrikeouts,
                                                                                                                                                    self.currentwalks,
                                                                                                                                                    self.hits,
                                                                                                                                                    self.scoreKeeper.get_score())
                            scoreboard = self.drawscoreboard(result)
                            scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
                            self.banner.set_text("STRIKEOUT")
                            self.banner.show()
                            self.banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR,{'time_per_letter': 0.1})
                            self.containerupdate(textbox,scoreboard)
                            self.pitchnumber = 0
                            self.currentstrikes = 0
                            self.currentballs = 0
                        # Normal Strike
                        else:
                            outcome = 'strike'
                            self.container.clear()
                            if self.swing_started == 0:
                                new_entry['called_strike'] = True
                                string = "<font size=5>PITCH {}: {}<br>CALLED STRIKE<br>COUNT IS {} - {}<br></font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                            else:
                                new_entry['swinging_strike'] = True
                                string = "<font size=5>PITCH {}: {}<br>SWINGING STRIKE<br>COUNT IS {} - {}<br></font>".format(self.pitchnumber, pitchtype, self.currentballs, self.currentstrikes)
                            textbox = self.pitchresult(string)
                            textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts,
                                                                                                                                                     self.currentstrikeouts,
                                                                                                                                                     self.currentwalks,
                                                                                                                                                     self.hits,
                                                                                                                                                     self.scoreKeeper.get_score())
                            scoreboard = self.drawscoreboard(result)
                            self.containerupdate(textbox,scoreboard)

            # END LOOP (END OF PITCH)
            elif current_time > starttime + traveltime + 1800:
                running = False
                self.show_buttons()
                pygame.mouse.set_cursor(crosshair)
                new_entry['FinalX'] = self.ball[0]
                new_entry['FinalY'] = self.ball[1]
                if self.records.empty:
                    self.records = pd.DataFrame([new_entry])
                else:
                    self.records = pd.concat([self.records, pd.DataFrame([new_entry])], ignore_index = True)

        last_ball = self.last_pitch_information[-1]
        for pitch in self.last_pitch_information:
            if pitch[0] == last_ball[0] and pitch[1] == last_ball[1]:
                pitch[3] = last_ball[3]

        new_state = (self.currentouts, self.currentstrikes, self.currentballs,self.scoreKeeper.get_runners_on_base(), self.hits, self.scoreKeeper.get_score())
        self.current_pitcher.get_ai().update(previous_state, self.pitch_chosen, new_state, self.outcome_value[outcome])
        self.current_state = new_state
        self.pitch_trajectories.append(self.last_pitch_information)
        self.pitches_display.append((self.ball[0], self.ball[1]))
        self.current_pitches += 1
        return (self.ball[0], self.ball[1])

    def hide_buttons(self):
        self.salepitch.hide()
        self.strikezonetoggle.hide()
        self.backtomainmenu.hide()
        self.sasakipitch.hide()
        self.yamamotopitch.hide()
        self.degrompitch.hide()
        self.toggleumpsound.hide()
        self.seepitches.hide()
        self.togglebatter.hide()
        self.visualise.hide()
        self.banner.hide()

    def show_buttons(self):
        self.salepitch.show()
        self.strikezonetoggle.show()
        self.backtomainmenu.show()
        self.sasakipitch.show()
        self.yamamotopitch.show()
        self.degrompitch.show()
        self.toggleumpsound.show()
        self.seepitches.show()
        self.togglebatter.show()
        self.visualise.show()

    def draw_buttons(self, pitcherbutton):
        self.degrompitch.hide()
        self.sasakipitch.hide()
        self.yamamotopitch.hide()
        self.salepitch.show()
        pitcherbutton.show()

    def gameButtons(self, toHide):
        self.degrompitch.hide()
        self.sasakipitch.hide()
        self.yamamotopitch.hide()
        self.salepitch.hide()
        self.return_to_game.hide()
        self.backtomainmenu.show()
        self.strikezonetoggle.show()
        self.toggleumpsound.show()
        self.seepitches.show()
        toHide.show()

    def visualise_last_pitch(self):
        time_delta = self.clock.tick_busy_loop(60)/1000.0
        current_time = pygame.time.get_ticks()
        last_time = current_time
        x = 0
        while x <= len(self.last_pitch_information) - 1:
            for event in pygame.event.get():
                    self.manager.process_events(event)
                    if event.type == pygame.QUIT:
                        running = False
                    if event.type == pygame_gui.UI_BUTTON_PRESSED:
                        if event.ui_element == self.strikezonetoggle:
                            if self.strikezonedrawn == 1:
                                self.strikezonedrawn = 2
                            elif self.strikezonedrawn == 2:
                                self.strikezonedrawn = 3
                            elif self.strikezonedrawn == 3:
                                self.strikezonedrawn = 1
                        elif event.ui_element == self.toggleumpsound:
                            if self.umpsound == True:
                                self.umpsound = False
                            elif self.umpsound == False:
                                self.umpsound = True
                        elif event.ui_element == self.salepitch:
                            self.Sale_AI()
                        elif event.ui_element == self.degrompitch:
                            self.Degrom_AI()
                        elif event.ui_element == self.sasakipitch:
                            self.Sasaki_AI()
                        elif event.ui_element == self.yamamotopitch:
                            self.Yamamoto_AI()
                        elif event.ui_element == self.backtomainmenu:
                            self.menu_state = 0
                        elif event.ui_element == self.seepitches:
                            self.menu_state = 200
                        elif event.ui_element == self.visualise:
                            self.menu_state = self.current_gamemode
                        elif event.ui_element == self.return_to_game:
                            self.menu_state = self.current_gamemode
                        elif event.ui_element == self.togglebatter:
                            if self.batter_hand == 'L':
                                self.batter_hand = 'R'
                                self.x = 330
                            elif self.batter_hand == 'R':
                                self.batter_hand = 'L'
                                self.x = 735
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_q:
                            if self.menu_state == 'Sale':
                                self.Sale_AI()
                            elif self.menu_state == 'Degrom':
                                self.Degrom_AI()
                            elif self.menu_state == 'Sasaki':
                                self.Sasaki_AI()
                            elif self.menu_state == 'Yamamoto':
                                self.Yamamoto_AI()
            time_delta = self.clock.tick_busy_loop(60)/1000.0
            self.manager.update(time_delta)
            self.screen.fill("black")
            current_time = pygame.time.get_ticks()
            if x <= len(self.last_pitch_information) - 1:
                pygame.draw.ellipse(self.screen,
                                    (255,255,255),
                                    (int(self.last_pitch_information[x][0]),
                                    int(self.last_pitch_information[x][1]),
                                    int(self.last_pitch_information[x][2]),
                                    int(self.last_pitch_information[x][2])))
            time_elapsed = current_time - last_time
            if time_elapsed > 20:
                x += 1
                last_time = current_time
            self.draw_static()
            self.RightBatter(1) if self.batter_hand == 'R' else self.LeftBatter(1)
            self.manager.draw_ui(self.screen)
            pygame.display.flip()
        return

    def visualise_lasttwo_pitch(self):
        time_delta = self.clock.tick_busy_loop(60)/1000.0
        current_time = pygame.time.get_ticks()
        last_time = current_time
        x = 0
        if not self.last_pitch_information:
            for event in pygame.event.get():
                self.manager.process_events(event)
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame_gui.UI_BUTTON_PRESSED:
                    if event.ui_element == self.strikezonetoggle:
                        if self.strikezonedrawn == 1:
                            self.strikezonedrawn = 2
                        elif self.strikezonedrawn == 2:
                            self.strikezonedrawn = 3
                        elif self.strikezonedrawn == 3:
                            self.strikezonedrawn = 1
                    elif event.ui_element == self.toggleumpsound:
                        if self.umpsound == True:
                            self.umpsound = False
                        elif self.umpsound == False:
                            self.umpsound = True
                    elif event.ui_element == self.backtomainmenu:
                        self.menu_state = 0
                    elif event.ui_element == self.seepitches:
                        self.menu_state = 200
                    elif event.ui_element == self.visualise:
                        self.menu_state = self.current_gamemode
                    elif event.ui_element == self.return_to_game:
                        self.menu_state = self.current_gamemode
                    elif event.ui_element == self.togglebatter:
                        if self.batter_hand == 'L':
                            self.batter_hand = 'R'
                            self.x = 330
                        elif self.batter_hand == 'R':
                            self.batter_hand = 'L'
                            self.x = 735
        while x <= len(self.last_pitch_information) - 1:
            for event in pygame.event.get():
                self.manager.process_events(event)
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame_gui.UI_BUTTON_PRESSED:
                    if event.ui_element == self.strikezonetoggle:
                        if self.strikezonedrawn == 1:
                            self.strikezonedrawn = 2
                        elif self.strikezonedrawn == 2:
                            self.strikezonedrawn = 3
                        elif self.strikezonedrawn == 3:
                            self.strikezonedrawn = 1
                    elif event.ui_element == self.toggleumpsound:
                        if self.umpsound == True:
                            self.umpsound = False
                        elif self.umpsound == False:
                            self.umpsound = True
                    elif event.ui_element == self.salepitch:
                        self.Sale_AI()
                    elif event.ui_element == self.degrompitch:
                        self.Degrom_AI()
                    elif event.ui_element == self.sasakipitch:
                        self.Sasaki_AI()
                    elif event.ui_element == self.yamamotopitch:
                        self.Yamamoto_AI()
                    elif event.ui_element == self.backtomainmenu:
                        self.menu_state = 0
                    elif event.ui_element == self.seepitches:
                        self.menu_state = 200
                    elif event.ui_element == self.visualise:
                        self.menu_state = self.current_gamemode
                    elif event.ui_element == self.return_to_game:
                        self.menu_state = self.current_gamemode
                    elif event.ui_element == self.togglebatter:
                        if self.batter_hand == 'L':
                            self.batter_hand = 'R'
                            self.x = 330
                        elif self.batter_hand == 'R':
                            self.batter_hand = 'L'
                            self.x = 735
            time_delta = self.clock.tick_busy_loop(60)/1000.0
            self.manager.update(time_delta)
            self.screen.fill("black")
            current_time = pygame.time.get_ticks()
            if x <= len(self.last_pitch_information) - 1:
                for pitch in self.pitch_trajectories:
                    if x in range(len(pitch)):
                        pygame.draw.ellipse(self.screen,
                                            pitch[x][3],
                                            (int(pitch[x][0]),
                                            int(pitch[x][1]),
                                            int(pitch[x][2]),
                                            int(pitch[x][2])))
                    else:
                        pygame.draw.ellipse(self.screen,
                                            pitch[-1][3],
                                            (int(pitch[-1][0]),
                                            int(pitch[-1][1]),
                                            int(pitch[-1][2]),
                                            int(pitch[-1][2])))
            time_elapsed = current_time - last_time
            if time_elapsed > 20:
                x += 1
                last_time = current_time
            self.draw_static()
            self.RightBatter(1) if self.batter_hand == 'R' else self.LeftBatter(1)
            self.manager.draw_ui(self.screen)
            pygame.display.flip()
        return

    def process_events(self):
        pitch_buttons = [self.salepitch, self.degrompitch, self.sasakipitch, self.yamamotopitch]
        for event in pygame.event.get():
            self.manager.process_events(event)
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == self.strikezonetoggle:
                    self.strikezonedrawn = self.strikezonedrawn + 1 if self.strikezonedrawn < 3 else 1
                elif event.ui_element == self.toggleumpsound:
                    self.umpsound = not self.umpsound
                elif event.ui_element in pitch_buttons:
                    selection = self.current_pitcher.ai.choose_action(self.current_state)
                    self.pitch_chosen = selection
                    self.current_pitcher.pitch(self.main_simulation, selection)
                elif event.ui_element == self.backtomainmenu:
                    self.menu_state = 0
                elif event.ui_element == self.seepitches:
                    self.menu_state = 200
                elif event.ui_element == self.visualise:
                    self.menu_state = 'visualise'
                    self.visualised = False
                elif event.ui_element == self.return_to_game:
                    self.menu_state = self.current_gamemode
                elif event.ui_element == self.togglebatter:
                    if self.batter_hand == 'L':
                        self.batter_hand = 'R'
                        self.x = 330
                    elif self.batter_hand == 'R':
                        self.batter_hand = 'L'
                        self.x = 735
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    selection = self.current_pitcher.ai.choose_action(self.current_state)
                    self.pitch_chosen = selection
                    self.current_pitcher.pitch(self.main_simulation, selection)
        return True

    # Main Game Loop
    def run(self):
        running = True
        while running:
            time_delta = self.clock.tick(60)/1000.0
            self.check_menu()
            if self.menu_state == 0:
                self.main_menu()
            elif self.menu_state == 100:
                self.draw_inning_summary()
            elif self.menu_state == 'visualise':
                running = self.process_events()
                if not self.visualised:
                    self.visualise_lasttwo_pitch()
                self.manager.update(time_delta)
                self.screen.fill("black")

            # Normal pitcher faceoff mode
            else:
                running = self.process_events()
                self.manager.update(time_delta)
                self.screen.fill("black")
                self.current_pitcher.draw_pitcher(0,0)
                if self.menu_state == 'Sale':
                    self.gameButtons(self.salepitch)
                elif self.menu_state == 'Degrom':
                    self.gameButtons(self.degrompitch)
                elif self.menu_state == 'Sasaki':
                    self.gameButtons(self.sasakipitch)
                elif self.menu_state == 'Yamamoto':
                    self.gameButtons(self.yamamotopitch)
                elif self.menu_state == 200:
                    self.salepitch.hide()
                    self.degrompitch.hide()
                    self.sasakipitch.hide()
                    self.yamamotopitch.hide()
                    self.seepitches.hide()
                    self.return_to_game.show()
                    self.backtomainmenu.show()
                    self.strikezonetoggle.show()
                    for pitch_pos in self.pitches_display:
                        pygame.gfxdraw.aacircle(self.screen, int(pitch_pos[0]), int(pitch_pos[1]), self.fourseamballsize, (255,255,255))
                if self.just_refreshed == 1:
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(self.currentouts, self.currentstrikeouts, self.currentwalks, self.hits, self.scoreKeeper.get_score())
                    scoreboard = self.drawscoreboard(result)
                    scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
                    string = "<font size=5><br>COUNT IS {} - {}</font>".format(self.pitchnumber, self.currentballs, self.currentstrikes)
                    textbox = self.pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
                    self.containerupdate(textbox, scoreboard)
                    self.just_refreshed = 0
                    self.current_gamemode = self.menu_state
                self.draw_static()
                self.RightBatter(1) if self.batter_hand == 'R' else self.LeftBatter(1)
                if self.first_pitch_thrown:
                    pygame.gfxdraw.aacircle(self.screen, int(self.ball[0]), int(self.ball[1]), self.fourseamballsize, (255,255,255))
                self.manager.draw_ui(self.screen)

                pygame.display.flip()

        # Quit cleanup
        print(self.records)

def main():
    Game()
    pygame.quit()

if __name__ == "__main__":
    main()