# BasedBall : A baseball batting simulator
import pygame
import pygame.gfxdraw
import pygame_gui
import random
import math
import json

import pygame_gui.core.ui_container

from helpers import Button, ScoreKeeper, StatSwing, pitchDataManager
import sys
import os
import pandas as pd
import pickle
from Pitchers_Test.Mcclanahan import Mcclanahan
from Pitchers_Test.Sale import Sale
from Pitchers_Test.Degrom import Degrom
from Pitchers_Test.Yamamoto import Yamamoto
from Pitchers_Test.Sasaki import Sasaki
from AI_2 import ERAI

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def get_path(orig_path):
    return os.path.join(SCRIPT_DIR, orig_path)

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
model = pickle.load(open(get_path("AI/ai_umpire.pkl"), "rb"))

# Directory containing AI models
AI_DIR = "AI_2"

class Game:

    # Update pitcher stats after game ends?
    update = False
    use_new = True

    records = pd.DataFrame
    batradius = 40

    # Pygame setup
    screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
    clock = pygame.time.Clock()
    icon = pygame.image.load(get_path("Images/icon.png")).convert_alpha()
    pygame.display.set_icon(icon)
    pygame.display.set_caption('StrikeFactor 0.1')

    # Stuff for the typing effect in main menu and summary self.screen
    dt = 0
    font = pygame.font.Font(resource_path(get_path("8bitoperator_jve.ttf")), 40)
    bigfont = pygame.font.Font(resource_path(get_path("8bitoperator_jve.ttf")), 70)
    snip = font.render('', True, 'white')
    counter = 0
    speed = 3

    # Load Sounds
    pop1 = pygame.mixer.Sound(resource_path(get_path("Sounds/POPSFX.mp3")))
    pop2 = pygame.mixer.Sound(resource_path(get_path("Sounds/POP2.mp3")))
    pop3 = pygame.mixer.Sound(resource_path(get_path("Sounds/POP3.mp3")))
    pop4 = pygame.mixer.Sound(resource_path(get_path("Sounds/POP4.mp3")))
    pop5 = pygame.mixer.Sound(resource_path(get_path("Sounds/POP5.mp3")))
    pop6 = pygame.mixer.Sound(resource_path(get_path("Sounds/POP6.mp3")))
    strikecall = pygame.mixer.Sound(resource_path(get_path("Sounds/STRIKECALL.mp3")))
    ballcall = pygame.mixer.Sound(resource_path(get_path("Sounds/BALLCALL.mp3")))
    foulball = pygame.mixer.Sound(resource_path(get_path("Sounds/FOULBALL.mp3")))
    single = pygame.mixer.Sound(resource_path(get_path("Sounds/SINGLE.mp3")))
    double = pygame.mixer.Sound(resource_path(get_path("Sounds/DOUBLE.mp3")))
    triple = pygame.mixer.Sound(resource_path(get_path("Sounds/TRIPLE.mp3")))
    homer = pygame.mixer.Sound(resource_path(get_path("Sounds/HOMERUN.mp3")))
    called_strike_3 = pygame.mixer.Sound(resource_path(get_path("Sounds/CALLEDSTRIKE3.mp3")))
    sizzle = pygame.mixer.Sound(resource_path(get_path("Sounds/sss.mp3")))

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
        ball_dir = get_path('ball')
        for filename in os.listdir(ball_dir):
            out.append(pygame.image.load(f'{ball_dir}/{filename}').convert_alpha())
        return out

    batter = loadimg('Images/TROUT', 15)
    batterhigh = loadimg('Images/HIGHSWING', 7)
    batterleft = loadimg('Images/TROUTLEFT', 15)
    batterlefthigh = loadimg('Images/HIGHSWINGLEFT', 7)
    ball = [0, 0, 4600]
    ball_list = loadball()
    rhpos = (490, 453)
    rhpos_high = (497, 405)

    def blitball():
        counter = 0
        def blit(self, size_override=None):
            nonlocal counter
            # Get the appropriate ball image
            image = self.ball_list[counter]
            
            # Calculate ball size based on distance
            dist = self.ball[2] / 4600
            
            # Non-linear scaling for more dramatic perspective effect
            size = size_override if size_override else min(max(3 + 9 * (1 - dist**1.2), 3), 14)
            
            # Adjust size ratio
            ratio = size / 54
            
            # Scale and position image
            scaled_image = pygame.transform.scale(image, (int(ratio * 64), int(ratio * 66)))
            self.screen.blit(scaled_image, (self.ball[0] - (scaled_image.get_width()/2), 
                                            self.ball[1] - (scaled_image.get_height()/2)))
            
            # Increment counter for ball rotation effect
            counter = (counter + 1) % len(self.ball_list)
        
        return blit

    blitfunc = blitball()

    # Buttons for main menu
    salebutton = pygame.image.load(resource_path(get_path("Images/salebutton.png"))).convert_alpha()
    degrombutton = pygame.image.load(resource_path(get_path("Images/degrombutton.png"))).convert_alpha()
    sasakibutton = pygame.image.load(resource_path(get_path("Images/sasakibutton.png"))).convert_alpha()
    yamamotobutton = pygame.image.load(resource_path(get_path("Images/yamamotobutton.png"))).convert_alpha()
    menu = pygame.image.load(resource_path(get_path("Images/MAINMENU.png"))).convert_alpha()
    experimental = pygame.image.load(resource_path(get_path("Images/experimental.png"))).convert_alpha()
    experimentalbutton = Button(1050, 650, experimental, 0.5)
    faceoffsasaki = Button(600,500,sasakibutton, 0.5)
    faceoffsale = Button(400,500, salebutton, 0.5)
    faceoffdegrom = Button(400,600, degrombutton, 0.5)
    faceoffyamamoto = Button(600,600, yamamotobutton, 0.5)
    mainmenubutton = Button(540, 530, menu, 0.6)

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

    # Preprocess dynamic font paths for theme dictionary
    theme_file = get_path('theme.json')
    with open(theme_file, 'r') as f:
        theme_data = json.load(f)
    dynamic_font_path = resource_path(get_path('8bitoperator_jve.ttf'))
    theme_data["label"]["font"]["regular_path"] = dynamic_font_path
    theme_data["button"]["font"]["regular_path"] = dynamic_font_path


    manager = pygame_gui.UIManager((1280, 720), theme_data)
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
    pitchDataManager = pitchDataManager()
    swing_started = 0
    hits = 0
    ishomerun = ''
    last_pitch_type_thrown = None
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
    pitch_button = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((0, 0), (200,100)),
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
    view_window = StatSwing((25,25), manager, pitch_trajectories, last_pitch_information)
    view_window.hide()

    def __init__(self):
        self.pending_sounds = []
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
    def powertiming(self, swing_starttime, starttime, traveltime, windup_time):
        diff = abs((swing_starttime + 150) - (starttime + windup_time + traveltime))
        if 20 < diff < 35:
            return 1
        elif diff <= 20:
            return 2
        else:
            return 0

    def contacttiming(self, swing_starttime, starttime, traveltime, windup_time):
        diff = abs((swing_starttime + 150) - (starttime + windup_time + traveltime))
        if 30 < diff < 60:
            return 1
        elif diff <= 30:
            return 2
        else:
            return 0

    # Check for contact based on mouse cursor position when self.ball impacts bat
    def loc_check(self, batpos, ballpos, swing_type, ballsize=11):
        lol = 1 if self.batter_hand == "R" else -1
        angle = math.atan2(batpos[1] - self.rhpos[1], batpos[0] - self.rhpos[0])
        contact_zone_height = 50 if swing_type == 1 else 25
        if self.collision_angled(ballpos[0], ballpos[1], ballsize, (batpos[0] - (30 * lol)), batpos[1], 120, contact_zone_height, angle):
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
    
    # CREDIT TO e-James -> https://stackoverflow.com/questions/401847/circle-rectangle-self.collision-detection-intersection
    def collision_angled(self, circlex, circley, radius, rectmiddlex, rectmiddley, rectwidth, rectheight, angle):
        # Rotate circle's center point back
        unrotated_circlex = math.cos(angle) * (circlex - rectmiddlex) - math.sin(angle) * (circley - rectmiddley) + rectmiddlex
        unrotated_circley = math.sin(angle) * (circlex - rectmiddlex) + math.cos(angle) * (circley - rectmiddley) + rectmiddley

        # Axis-aligned bounding box check
        circleDistancex = abs(unrotated_circlex - rectmiddlex)
        circleDistancey = abs(unrotated_circley - rectmiddley)

        if (circleDistancex > (rectwidth / 2 + radius)):
            return False
        if (circleDistancey > (rectheight / 2 + radius)):
            return False
        if (circleDistancex <= (rectwidth / 2)):
            return True
        if (circleDistancey <= (rectheight / 2)):
            return True

        cornerDistance_sq = ((circleDistancex - rectwidth / 2) ** 2) + ((circleDistancey - rectheight / 2) ** 2)
        return (cornerDistance_sq <= (radius ** 2))

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
            elif self.experimentalbutton.draw(self.screen):
                self.enter_gamemode('Experimental', self.mcclanahan)
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
        self.cleanUp()

    def schedule_sound(self, sound, delay=1000):
        """Schedule sound.play() to happen delay ms in the future."""
        play_time = pygame.time.get_ticks() + delay
        self.pending_sounds.append((play_time, sound))

    def _process_scheduled_sounds(self, current_time):
        """Call .play() on any sounds whose time has come."""
        for play_time, sound in list(self.pending_sounds):
            if current_time >= play_time:
                sound.play()
                self.pending_sounds.remove((play_time, sound))


    # GAME LOOP FOR AT-BAT SIMULATION
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
    def main_simulation(self, release_point, pitchername, ax, ay, vx, vy, traveltime, pitchtype):
        self.hide_buttons()
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
            'Handedness': self.batter_hand,
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

        def draw_ball_shadow():
            # Calculate shadow position based on ball height and perspective
            shadow_y = 560  # Ground level
            
            # Distance from ground affects shadow size and opacity
            height_ratio = (self.ball[1] - 400) / 160  # Normalized y-position (higher = smaller shadow)
            shadow_size = max(4, 10 * (1 - height_ratio/2) * (1 - self.ball[2]/4600))
            shadow_opacity = max(30, 180 - int(self.ball[2]/20))
            
            # Offset shadow based on ball height (higher ball = shadow more offset)
            shadow_x = self.ball[0] + (height_ratio * 15)
            
            # Draw shadow as a dark ellipse
            shadow_surface = pygame.Surface((shadow_size*2, shadow_size), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow_surface, (0, 0, 0, shadow_opacity), (0, 0, shadow_size*2, shadow_size))
            self.screen.blit(shadow_surface, (shadow_x - shadow_size, shadow_y - shadow_size/2))

        def apply_pitch_motion_effects(pitch_type):
            # For fastballs, add motion blur when ball is close
            if pitch_type.lower() in ["fastball", "four-seam", "heater"] and self.ball[2] < 2000:
                # Create a subtle motion trail
                for i in range(1, 4):
                    trail_opacity = 100 - (i * 30)
                    trail_size = max(3, (12 - i*2) * (1 - self.ball[2]/4600))
                    
                    # Calculate previous positions based on velocity
                    trail_z = min(4600, self.ball[2] + (i * 120))
                    trail_dist = trail_z / 300
                    trail_x = self.ball[0] - (vx * (1/trail_dist) * i * 0.3)
                    trail_y = self.ball[1] - (vy * (1/trail_dist) * i * 0.3)
                    
                    # Draw motion blur trail
                    trail_surface = pygame.Surface((trail_size*2, trail_size*2), pygame.SRCALPHA)
                    pygame.draw.circle(trail_surface, (255, 255, 255, trail_opacity), 
                                    (trail_size, trail_size), trail_size)
                    self.screen.blit(trail_surface, (trail_x - trail_size, trail_y - trail_size))

        def draw_enhanced_ball():
            # Calculate realistic size scaling based on distance
            z_progress = 1 - (self.ball[2] / 4600)  # 0 when far, 1 when close
            
            # Non-linear scaling for more dramatic perspective effect
            size_factor = 0.5 + (z_progress ** 1.5) * 1.5
            ball_size = max(3, min(14, 11 * size_factor))
            
            # Select image and apply rotation
            current_frame = int(pygame.time.get_ticks() / 30) % len(self.ball_list)
            
            # Rotation speed varies by pitch type
            rotation_factor = 2
            if pitchtype.lower() in ["curveball", "slider"]:
                rotation_factor = 4
            elif pitchtype.lower() in ["fastball", "four-seam"]:
                rotation_factor = 3
                
            # Choose appropriate image based on index
            image = self.ball_list[current_frame]
            
            # Scale image based on distance
            ratio = ball_size / 54
            scaled_size = (int(ratio * 64), int(ratio * 66))
            
            # For breaking balls, apply slight rotation for visual effect
            if pitchtype.lower() in ["curveball", "slider", "changeup"]:
                angle = (pygame.time.get_ticks() // 20) % 360
                image = pygame.transform.rotate(image, angle * rotation_factor * 0.1)
            
            scaled_image = pygame.transform.scale(image, scaled_size)
            self.screen.blit(scaled_image, (self.ball[0] - scaled_size[0]/2, self.ball[1] - scaled_size[1]/2))

        def draw_batter():
            if self.swing_started:
                if self.swing_started == 1:
                    self.swing_start(current_time, swing_starttime)
                else:
                    self.high_swing_start(current_time, swing_starttime)
            elif self.swing_started == 0:
                self.leg_kick(current_time, starttime + windup - 300)

        def update_ball_pos_and_draw():
            nonlocal vx, vy, ax, ay, dist
            
            # Calculate a more realistic perspective scaling factor
            dist = self.ball[2]/300
            if dist > 1:
                # Draw ball shadow first (appears under the ball)
                draw_ball_shadow()
                
                # Apply pitch-type specific motion effects
                apply_pitch_motion_effects(pitchtype)
                
                # Draw the ball with enhanced visual effects
                draw_enhanced_ball()
                
                # Update ball position with improved physics
                # Z-movement: non-linear to appear more realistic
                z_progress = (4600 - self.ball[2]) / 4600  # 0 to 1 as ball approaches
                z_speed_factor = 0.8 + 0.4 * z_progress  # Ball appears to speed up as it gets closer
                
                self.ball[2] -= (4300 * 1000)/(60 * traveltime) * z_speed_factor
                
                # Apply perspective to X/Y movement (appears to move more as gets closer)
                perspective_factor = 1 + (z_progress * 0.6)  # Increases movement effect as ball approaches
                self.ball[1] += vy * (1/dist) * perspective_factor
                self.ball[0] += vx * (1/dist) * perspective_factor
                
                # Apply acceleration with more realistic physics
                gravity_effect = 1 + (z_progress * 0.5)  # Gravity appears stronger as ball approaches
                vy += (ay*300) * (1/dist) * gravity_effect
                vx += (ax*300) * (1/dist)

        while running:
            self._process_scheduled_sounds(current_time)
            self.screen.fill("black")
            time_delta = self.clock.tick_busy_loop(60)/1000.0
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
                self.leg_kick(current_time, starttime + windup - 300)
                self.draw_static()
                self.manager.update(time_delta)
                self.manager.draw_ui(self.screen)
                pygame.display.flip()

            # From time self.ball leaves the hand until self.ball finishes traveling (no contact made yet)
            if ((current_time > starttime + windup
                and current_time < arrival_time
                # Did not swing OR swung and missed
                and (on_time == 0 or (on_time > 0 and made_contact == "swung_and_miss")))
                or (on_time > 0 and current_time <= contact_time and made_contact == "no_swing")):
                if not sizz:
                    sizz = True
                    self.sizzle.play()
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
                                on_time = self.contacttiming(swing_starttime,starttime,traveltime, windup)
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
                                on_time = self.powertiming(swing_starttime,starttime,traveltime, windup)
                                if mousepos[1] > 500:
                                    self.swing_started = 1
                                #HIGH SWING
                                else:
                                    self.swing_started = 2
                draw_batter()
                update_ball_pos_and_draw()
                self.draw_static()
                self.manager.update(time_delta)
                self.manager.draw_ui(self.screen)
                pygame.display.flip()

                # Ball reach glove
                if (current_time > (arrival_time - 30)
                    and soundplayed == 0 and on_time == 0) or (current_time > contact_time and soundplayed == 0 and (on_time > 0 and made_contact == "swung_and_miss")):
                    self.glovepop()
                    soundplayed += 1

            # CONTACT TIME REACHED, TIMING NOT COMPLETELY OFF, CHECK FOR OUTCOME
            elif (on_time > 0
                  and current_time > contact_time
                  and current_time <= arrival_time + 700
                  and made_contact != "swung_and_miss"):
                draw_batter()
                self.draw_static()
                pygame.gfxdraw.aacircle(self.screen, int(self.ball[0]), int(self.ball[1]), self.fourseamballsize, (255,255,255))
                self.manager.update(time_delta)
                self.manager.draw_ui(self.screen)
                pygame.display.flip()
                # FOUL BALL TIMING
                if (on_time == 1 and pitch_results_done == False):
                    outcome = self.loc_check(mousepos, (self.ball[0], self.ball[1]), swing_type)
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
                        outcome = self.loc_check(mousepos, (self.ball[0], self.ball[1]), swing_type)
                        # PERFECT TIMING AND LOCATION MISS - MISS
                        if outcome == 'miss':
                            made_contact = "swung_and_miss"
                        # PERFECT TIMING AND SWING PATH ON - SUCCESSFUL HIT
                        else:
                            self.strikes += 1
                            is_hit = True
                            self.container.clear()
                            made_contact = "hit"
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
                # Play Bat Contact Sounds
                if (current_time > contact_time and soundplayed == 0 and pitch_results_done == True):
                    if on_time == 1:
                        self.foulball.play()
                        soundplayed += 1
                    elif on_time == 2:
                        if self.hit_type == 1:
                            self.single.play()
                        elif self.hit_type == 2:
                            self.double.play()
                        elif self.hit_type == 3:
                            self.triple.play()
                        elif self.hit_type == 4:
                            self.homer.play()
                        soundplayed += 1

            # FOLLOW THROUGH IF NO CONTACT MADE (No more swings allowed to start)
            elif (current_time > arrival_time 
                  and current_time <= arrival_time + 700
                  and (on_time == 0 or (on_time > 0 and made_contact == "swung_and_miss"))):
                if (current_time > contact_time and soundplayed == 0 and (on_time > 0 and made_contact == "swung_and_miss")):
                    self.glovepop()
                    soundplayed += 1
                draw_batter()
                self.draw_static()
                pygame.gfxdraw.aacircle(self.screen, int(self.ball[0]), int(self.ball[1]), self.fourseamballsize, (255,255,255))
                self.manager.update(time_delta)
                self.manager.draw_ui(self.screen)
                pygame.display.flip()
                if pitch_results_done == False:
                    pitch_results_done = True
                    # BALL OUTSIDE THE ZONE AND NOT SWUNG AT - BALL
                    if not model.predict(pd.DataFrame([[self.ball[0], self.ball[1]]], columns=['finalx', 'finaly'])) and self.swing_started == 0:
                        self.balls += 1
                        new_entry['ball'] = True
                        if self.umpsound:
                            self.schedule_sound(self.ballcall, delay=200)
                        self.currentballs += 1
                        self.pitchnumber += 1
                        # WALK OCCURS
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
                            self.schedule_sound(self.called_strike_3, delay=200)
                        elif self.swing_started == 0 and self.currentstrikes != 3 and self.umpsound:
                            self.schedule_sound(self.strikecall, delay=200)
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
            elif current_time > arrival_time + 700:
                running = False
                self.show_buttons()
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

    def hide_buttons(self):
        self.pitch_button.hide()
        self.strikezonetoggle.hide()
        self.backtomainmenu.hide()
        self.toggleumpsound.hide()
        self.seepitches.hide()
        self.togglebatter.hide()
        self.visualise.hide()
        self.banner.hide()

    def show_buttons(self):
        self.strikezonetoggle.show()
        self.backtomainmenu.show()
        self.toggleumpsound.show()
        self.seepitches.show()
        self.togglebatter.show()
        self.visualise.show()

    def draw_buttons(self, pitcherbutton):
        pitcherbutton.show()

    def gameButtons(self):
        self.return_to_game.hide()
        self.backtomainmenu.show()
        self.strikezonetoggle.show()
        self.toggleumpsound.show()
        self.seepitches.show()
        self.pitch_button.show()

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
                    return False
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
        return True

    def process_events(self):
        for event in pygame.event.get():
            self.manager.process_events(event)
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == self.strikezonetoggle:
                    self.strikezonedrawn = self.strikezonedrawn + 1 if self.strikezonedrawn < 3 else 1
                elif event.ui_element == self.toggleumpsound:
                    self.umpsound = not self.umpsound
                elif event.ui_element == self.pitch_button:
                    self.first_pitch_thrown = True
                    selection = self.current_pitcher.ai.choose_action(self.current_state)
                    self.pitch_chosen = selection
                    self.current_pitcher.pitch(self.main_simulation, selection)
                elif event.ui_element == self.backtomainmenu:
                    self.menu_state = 0
                elif event.ui_element == self.seepitches:
                    self.view_window.show()
                    self.view_window.update_pitch_info(self.pitch_trajectories, self.last_pitch_information)
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
                    self.first_pitch_thrown = True
                    selection = self.current_pitcher.ai.choose_action(self.current_state)
                    self.pitch_chosen = selection
                    self.current_pitcher.pitch(self.main_simulation, selection)
        return True

    def cleanUp(self):
        # self.pitchDataManager.append_to_file("pitchPredict/data.csv")
        print("DONE")

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
                running = self.visualise_lasttwo_pitch()
                self.manager.update(time_delta)
                self.screen.fill("black")

            # Normal pitcher faceoff mode
            else:
                running = self.process_events()
                self.manager.update(time_delta)
                self.screen.fill("black")
                self.current_pitcher.draw_pitcher(0,0)
                if self.menu_state != 200:
                    self.gameButtons()
                elif self.menu_state == 200:
                    self.pitch_button.hide()
                    self.seepitches.hide()
                    self.return_to_game.show()
                    self.backtomainmenu.show()
                    self.strikezonetoggle.show()
                    self.view_window.update(time_delta)
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
        self.cleanUp()
        

def main():
    Game()
    pygame.quit()

if __name__ == "__main__":
    main()


