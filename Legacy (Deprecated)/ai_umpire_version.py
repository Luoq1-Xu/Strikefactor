# BasedBall : A baseball batting simulator
import pygame
import pygame.gfxdraw
import pygame_gui
import random
import button
import sys
import os
import pandas as pd
import numpy as np
import pickle
from sklearn.svm import SVC

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
model = pickle.load(open("ai_umpire.pkl", "rb"))

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

class Game:

    records = pd.DataFrame(
        columns=[
            'Pitcher',
            'PitchType',
            'FirstX',
            'FirstY',
            'SecondX',
            'SecondY',
            'FinalX',
            'FinalY',
            'isHit',
            'called_strike',
            'foul',
            'swinging_strike',
            'ball',
            'in_zone'
        ]
    )

    # pygame setup
    screen = pygame.display.set_mode((1280, 720))
    clock = pygame.time.Clock()
    icon = pygame.image.load(resource_path('Images/icon.png')).convert_alpha()
    pygame.display.set_icon(icon)
    pygame.display.set_caption('Basedball Experimental Build')

    #Stuff for the typing effect in main menu and summary self.screen
    dt = 0
    font = pygame.font.Font(resource_path("8bitoperator_jve.ttf"), 40)
    bigfont = pygame.font.Font(resource_path("8bitoperator_jve.ttf"), 70)
    snip = font.render('', True, 'white')
    counter = 0
    speed = 3

    #Some more setup
    manager = pygame_gui.UIManager((1280, 720), 'theme.json')
    manager.preload_fonts([{'name': 'fira_code', 'point_size': 18, 'style': 'regular'},
                            {'name': 'fira_code', 'point_size': 18, 'style': 'bold'},
                            {'name': 'fira_code', 'point_size': 18, 'style': 'bold_italic'},
                            {'name': 'noto_sans', 'point_size': 18, 'style': 'bold', 'antialiased': '1'}])
    batter_hand = "R"
    player_pos = pygame.Vector2(screen.get_width() / 2, screen.get_height() / 2)
    left_player_pos = pygame.Vector2(screen.get_width() / 2, screen.get_height() / 2)
    strikezone = pygame.Rect((565, 410), (130, 150))
    fourseamballsize = 11
    strikezonedrawn = 1
    umpsound = True

    #Global variables for menu and resetting
    menu_state = 0
    just_refreshed = 0
    textfinished = 0

    #Global game variables
    pitchnumber = 0
    currentballs = 0
    currentstrikes = 0
    currentouts = 0
    currentstrikeouts = 0
    currentwalks = 0
    scoreKeeper = ScoreKeeper()
    swing_started = 0
    hits = 0
    ishomerun = ''
    first_pitch_thrown = False

    current_gamemode = 0
    pitches_display = []

    #Load Sounds
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


    #Load images
    def loadimg(name,number):
        counter = 1
        storage = []
        while counter <= number:
            storage.append(pygame.image.load(resource_path(f'{name}{counter}.png')).convert_alpha())
            counter += 1
        return storage

    lefty = loadimg('Images/LEFTY', 9)
    righty = loadimg('Images/RIGHTY', 9)
    batter = loadimg('Images/TROUT', 15)
    batterhigh = loadimg('Images/HIGHSWING', 7)
    batterleft = loadimg('Images/TROUTLEFT', 15)
    batterlefthigh = loadimg('Images/HIGHSWINGLEFT', 7)
    sasaki = loadimg('Sasaki/', 15)
    yamamoto = loadimg('Yamamoto/', 14)

    #Buttons for main menu
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

    #righty pitcher position
    c = (screen.get_width() / 2) - 30
    d = (screen.get_height() / 3) + 180

    #POSITION FOR RIGHT BATTER
    x = 330
    y = 190

    j = (screen.get_width() / 2) - 105
    k = (screen.get_height() / 3) - 40

    #Lefty pitcher position
    a = (screen.get_width() / 2) - 40
    b = (screen.get_height() / 3) + 180

    DEGROMRELEASEPOINT = pygame.Vector2((screen.get_width() / 2) - 45, (screen.get_height() / 3) + 187)
    SALERELEASEPOINT = pygame.Vector2((screen.get_width() / 2) + 61, (screen.get_height() / 3) + 209)
    SASAKIRELEASEPOINT = pygame.Vector2((screen.get_width() / 2) - 42, (screen.get_height() / 3) + 164)
    YAMAMOTORELEASEPOINT = pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183)


    #Pygame_gui elements (Buttons, textboxes)
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
    container = pygame_gui.core.UIContainer(relative_rect=pygame.Rect((0, 0), (1280,720)),manager=manager, is_window_root_container=False)
    banner = pygame_gui.elements.UILabel(relative_rect=pygame.Rect((340, 0), (600,100)), manager=manager, text="")

    def __init__(self):
        self.run()

    def pitchresult(self,input):
        return pygame_gui.elements.UITextBox(input,relative_rect=pygame.Rect((1000, 250), (250,200)),
                                        manager=self.manager)

    def drawscoreboard(self,results):
        return pygame_gui.elements.UITextBox(results,relative_rect=pygame.Rect((1000, 50), (250,200)),
                                            manager=self.manager)

    #Container to house the scoreboard and textbox - to allow for previous instances to be deleted when new ones are created
    def containerupdate(self, textbox, scoreboard):
        self.container.add_element(textbox)
        self.container.add_element(scoreboard)
        return

    #Function to draw bases graphic
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

    #Draw static components (strikezone, home plate, bases)
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

    #Simple function to check self.menu_state and update the display accordingly.
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

    def Sale(self, number, xoffset=0, yoffset=0):
        self.screen.blit(self.lefty[number - 1], (self.a + xoffset, self.b + yoffset))

    def Degrom(self, number, xoffset=0, yoffset=0):
        self.screen.blit(self.righty[number - 1], (self.c + xoffset,self.d + yoffset))

    def Sasaki(self, number, xoffset=0, yoffset=0):
        self.screen.blit(self.sasaki[number - 1], (self.c + xoffset,self.d + yoffset))

    def RightBatter(self, number, xoffset=0, yoffset=0):
        self.screen.blit(self.batter[number - 1], (self.x + xoffset, self.y + yoffset))

    def LeftBatter(self, number, xoffset=0, yoffset=0):
        self.screen.blit(self.batterleft[number - 1], (self.x + xoffset,self.y + yoffset))

    def HighSwing(self, number, xoffset=0, yoffset=0):
        self.screen.blit(self.batterhigh[number - 1], (self.x + xoffset, self.y + yoffset))

    def LeftHighSwing(self, number, xoffset=0, yoffset=0):
        self.screen.blit(self.batterlefthigh[number - 1], (self.x + xoffset, self.y + yoffset))

    def Yamamoto(self, number, xoffset=0, yoffset=0):
        self.screen.blit(self.yamamoto[number - 1], (self.c + xoffset, self.d + yoffset))

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
        if self.collision(ballpos[0], ballpos[1], ballsize, (batpos[0] - (30 * lol)), (batpos[1]), 120, 25):
            outcome = "hit"
        else:
            outcome = "miss"
        if ballpos[1] - batpos[1] > 20:
            print("over")
        elif ballpos[1] - batpos[1] < -20:
            print("under")
        return outcome

    #YAMAMOTO PITCHING AI
    def Yamamoto_AI(self):
        random.choice([self.yamamotoFastball,
                       self.yamamotoCutter,
                       self.yamamotoCurve,
                       self.yamamotoHighFastball,
                       self.yamamotoSplitter])()

    #SASAKI PITCHING AI
    def Sasaki_AI(self):
        self.sasakiFastball3()

    #DEGROM PITCHING AI
    def Degrom_AI(self):
        random.choice([self.deGromChangeup, self.deGromFB1, self.deGromFB2, self.deGromFB3, self.deGromSlider])()

    #SALE PITCHING AI
    def Sale_AI(self):
        random.choice([self.saleUpRightFastball, self.saleUpLeftFastball, self.saleChangeup,
                       self.saleSlider, self.saleDownLeftFastball, self.saleDownRightFastball])()

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

        messages = ["BASED BALL",
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
                self.banner.hide()
                self.container.clear()
                self.menu_state = 'Sale'
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
                self.pitches_display = []
                pygame.mouse.set_cursor(crosshair)
                return
            elif self.faceoffdegrom.draw(self.screen):
                self.banner.hide()
                self.container.clear()
                self.menu_state = 'Degrom'
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
                self.pitches_display = []
                pygame.mouse.set_cursor(crosshair)
                return
            elif self.faceoffsasaki.draw(self.screen):
                self.banner.hide()
                self.container.clear()
                self.menu_state = 'Sasaki'
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
                self.pitches_display = []
                pygame.mouse.set_cursor(crosshair)
                return
            elif self.faceoffyamamoto.draw(self.screen):
                self.banner.hide()
                self.container.clear()
                self.menu_state = 'Yamamoto'
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
                self.pitches_display = []
                pygame.mouse.set_cursor(crosshair)
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
    def test(self, release_point, pitchername, ax, ay, vx, vy, traveltime, pitchtype):
        breaktime = 200
        running = True
        self.first_pitch_thrown = True
        self.swing_started = 0

        self.ball = [release_point[0], release_point[1], 4600]

        self.salepitch.hide()
        self.strikezonetoggle.hide()
        self.degrompitch.hide()
        self.sasakipitch.hide()
        self.yamamotopitch.hide()
        self.backtomainmenu.hide()
        self.banner.hide()
        self.seepitches.hide()
        self.toggleumpsound.hide()
        self.togglebatter.hide()

        soundplayed = 0
        sizz = False
        on_time = 0
        made_contact = 0
        contact_time = 0
        swing_type = 0
        pitch_results_done = False

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

        starttime = pygame.time.get_ticks()
        current_time = starttime
        while running:
            time_delta = self.clock.tick_busy_loop(60)/1000.0
            current_time = pygame.time.get_ticks()

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
                self.screen.fill("black")
                if pitchername == 'chrissale':
                    if current_time <= starttime + 300:
                        self.Sale(1)
                    elif current_time > starttime + 300 and current_time <= starttime + 500:
                        self.Sale(2)
                    elif current_time > starttime + 500 and current_time <= starttime + 700:
                        self.Sale(3)
                    elif current_time > starttime + 700 and current_time <= starttime + 900:
                        self.Sale(4)
                    elif current_time > starttime + 900 and current_time <= starttime + 1000:
                        self.Sale(5, 0, 10)
                    elif current_time > starttime + 1000 and current_time <= starttime + 1100:
                        self.Sale(6, 10, 25)
                elif pitchername == 'jacobdegrom':
                    if current_time <= starttime + 300:
                        self.Degrom(1)
                    elif current_time > starttime + 300 and current_time <= starttime + 500:
                        self.Degrom(2, -10, 0)
                    elif current_time > starttime + 500 and current_time <= starttime + 700:
                        self.Degrom(3, -13, 0)
                    elif current_time > starttime + 700 and current_time <= starttime + 900:
                        self.Degrom(4, -27, 5)
                    elif current_time > starttime + 900 and current_time <= starttime + 1000:
                        self.Degrom(5, -33, 12)
                    elif current_time > starttime + 1000 and current_time <= starttime + 1100:
                        self.Degrom(6, 12, 13)
                elif pitchername == 'rokisasaki':
                    if current_time <= starttime + 250:
                        self.Sasaki(1)
                    elif current_time > starttime + 250 and current_time <= starttime + 350:
                        self.Sasaki(2, -4, -4)
                    elif current_time > starttime + 350 and current_time <= starttime + 400:
                        self.Sasaki(3, -37, -4)
                    elif current_time > starttime + 400 and current_time <= starttime + 550:
                        self.Sasaki(4, -31, -4)
                    elif current_time > starttime + 550 and current_time <= starttime + 700:
                        self.Sasaki(5, -6, -5)
                    elif current_time > starttime + 700 and current_time <= starttime + 800:
                        self.Sasaki(6, 0, -5)
                    elif current_time > starttime + 800 and current_time <= starttime + 900:
                        self.Sasaki(7, -17, -3)
                    elif current_time > starttime + 900 and current_time <= starttime + 975:
                        self.Sasaki(8, -24, 4)
                    elif current_time > starttime + 975 and current_time <= starttime + 1000:
                        self.Sasaki(9, -5, 4)
                    elif current_time > starttime + 1000 and current_time <= starttime + 1050:
                        self.Sasaki(10, 14, -3)
                    elif current_time > starttime + 1050 and current_time <= starttime + 1100:
                        self.Sasaki(11, 2, -5)
                elif pitchername == 'Yamamoto':
                    if current_time <= starttime + 250:
                        self.Yamamoto(1)
                    elif current_time > starttime + 250 and current_time <= starttime + 350:
                        self.Yamamoto(2, -6, 0)
                    elif current_time > starttime + 350 and current_time <= starttime + 400:
                        self.Yamamoto(3, -6, 0)
                    elif current_time > starttime + 400 and current_time <= starttime + 550:
                        self.Yamamoto(4, -13, -1)
                    elif current_time > starttime + 550 and current_time <= starttime + 700:
                        self.Yamamoto(5, -20, 1)
                    elif current_time > starttime + 700 and current_time <= starttime + 800:
                        self.Yamamoto(6, -26, 2)
                    elif current_time > starttime + 800 and current_time <= starttime + 900:
                        self.Yamamoto(7, -11, 3)
                    elif current_time > starttime + 900 and current_time <= starttime + 975:
                        self.Yamamoto(8, -3, 4)
                    elif current_time > starttime + 975 and current_time <= starttime + 1000:
                        self.Yamamoto(9, 8, 4)
                    elif current_time > starttime + 1000 and current_time <= starttime + 1050:
                        self.Yamamoto(10, 5, 4)
                    elif current_time > starttime + 1050 and current_time <= starttime + 1100:
                        self.Yamamoto(11, -8, 11)
                self.leg_kick(current_time, starttime + 700)
                self.draw_static()
                self.manager.update(time_delta)
                self.manager.draw_ui(self.screen)
                pygame.display.flip()

            #From time self.ball leaves the hand until self.ball finishes traveling
            if ((current_time > starttime + 1100
                and current_time < starttime + traveltime + 1100
                and (on_time == 0 or (on_time > 0 and made_contact == 1)))
                or (on_time > 0 and current_time <= contact_time and made_contact == 0)):
                self.screen.fill("black")
                if not sizz:
                    sizz = True
                    self.sizzle.play()
                if current_time > starttime + 1100 and current_time <= starttime + 1100:
                    if pitchername == 'chrissale':
                        self.Sale(7, 8, 22)
                    elif pitchername == 'jacobdegrom':
                        self.Degrom(7, -20, 7)
                    elif pitchername == 'rokisasaki':
                        self.Sasaki(12, -14, -15)
                    elif pitchername == 'Yamamoto':
                        self.Yamamoto(12, -24, 1)
                #Ball continuing to travel because swing was too off timing
                elif current_time > starttime + 1100 and current_time <= starttime + breaktime + 1100 and on_time == 0:
                    if current_time > starttime + 1100 and current_time <= starttime + 1200:
                        if pitchername == 'chrissale':
                            self.Sale(8, -11, 22)
                        elif pitchername == 'jacobdegrom':
                            self.Degrom(8, 0, 27)
                        elif pitchername == 'rokisasaki':
                            self.Sasaki(13, 5, 12)
                        elif pitchername == 'Yamamoto':
                            self.Yamamoto(13, -4, 21)
                    else:
                        if pitchername == 'chrissale':
                            self.Sale(9, 16, 22)
                        elif pitchername == 'jacobdegrom':
                            self.Degrom(9, -11, 25)
                        elif pitchername == 'rokisasaki':
                            self.Sasaki(14, -9, 12)
                        elif pitchername == 'Yamamoto':
                            self.Yamamoto(14, -33, 19)
                elif (current_time > starttime + breaktime + 1100 and current_time <= starttime + traveltime + 1100 and (on_time == 0 or (on_time > 0 and made_contact == 1))) or (on_time > 0 and current_time <= contact_time and made_contact == 0):
                    if pitchername == 'chrissale':
                        self.Sale(9, 16, 22)
                    elif pitchername == 'jacobdegrom':
                        self.Degrom(9, -11, 25)
                    elif pitchername == 'rokisasaki':
                        self.Sasaki(14, -9, 12)
                    elif pitchername == 'Yamamoto':
                        self.Yamamoto(14, -33, 19)
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
                dist = self.ball[2]/301
                if dist > 1:
                    pygame.draw.ellipse(self.screen,(255,255,255),(self.ball[0], self.ball[1],max(11/dist, 3), max(11/dist, 4)))
                    self.ball[1] += vy * (1/dist)
                    self.ball[2] -= (4300 * 1000)/(60 * traveltime)
                    self.ball[0] += vx * (1/dist)
                    vy += (ay*301) * (1/dist)
                    vx += (ax*301) * (1/dist)
                self.draw_static()
                self.manager.update(time_delta)
                self.manager.draw_ui(self.screen)
                pygame.display.flip()


                if (current_time > (starttime + traveltime + 1050)
                    and soundplayed == 0 and on_time == 0) or (current_time > contact_time and soundplayed == 0 and (on_time > 0 and made_contact == 1)):
                    self.glovepop()
                    soundplayed += 1

            # BALL HAS CONTACTED BAT
            elif (on_time > 0
                  and current_time > contact_time
                  and current_time <= starttime + traveltime + 1800
                  and made_contact != 1):
                self.screen.fill("black")
                if pitchername == 'chrissale':
                        self.Sale(9, 16, 22)
                elif pitchername == 'jacobdegrom':
                    self.Degrom(9, -11, 25)
                elif pitchername == 'rokisasaki':
                    self.Sasaki(14, -9, 12)
                elif pitchername == 'Yamamoto':
                    self.Yamamoto(14, -33, 19)
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
                        #TIMING ON BUT SWING PATH OFF (SWING OVER OR UNDER BALL) - MISS
                        outcome = self.loc_check(mousepos, (self.ball[0], self.ball[1]))
                        if outcome == 'miss':
                            made_contact = 1
                        #TIMING ON AND PATH ON - FOUL BALL
                        else:
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
                    #PERFECT TIMING
                    elif (on_time == 2 and pitch_results_done == False):
                        outcome = self.loc_check(mousepos, (self.ball[0], self.ball[1]))
                        #PERFECT TIMING AND LOCATION MISS - MISS
                        if outcome == 'miss':
                            made_contact = 1
                        #PERFECT TIMING AND SWING PATH ON - SUCCESSFUL HIT
                        else:
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
                self.screen.fill("black")
                if pitchername == 'chrissale':
                    self.Sale(9, 16, 22)
                elif pitchername == 'jacobdegrom':
                    self.Degrom(9, -11, 25)
                elif pitchername == 'rokisasaki':
                    self.Sasaki(14, -9, 12)
                elif pitchername == 'Yamamoto':
                    self.Yamamoto(14, -33, 19)
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
                    if not model.predict(np.array([[self.ball[0], self.ball[1]]])) and self.swing_started == 0:
                        new_entry['ball'] = True
                        if self.umpsound:
                            self.ballcall.play()
                        self.currentballs += 1
                        self.pitchnumber += 1
                        #WALK OCCURS
                        if self.currentballs == 4:
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
                        else:
                            #Normal Strike
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

            #END LOOP (END OF PITCH)
            elif current_time > starttime + traveltime + 1800:
                running = False
                self.salepitch.show()
                self.strikezonetoggle.show()
                self.backtomainmenu.show()
                self.sasakipitch.show()
                self.yamamotopitch.show()
                self.degrompitch.show()
                self.toggleumpsound.show()
                self.seepitches.show()
                self.togglebatter.show()
                pygame.mouse.set_cursor(crosshair)
                new_entry['FinalX'] = self.ball[0]
                new_entry['FinalY'] = self.ball[1]
                self.records = pd.concat([self.records, pd.DataFrame([new_entry])], ignore_index = True)


        self.pitches_display.append((self.ball[0], self.ball[1]))
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

    def draw_buttons(self, pitcherbutton):
        self.degrompitch.hide()
        self.sasakipitch.hide()
        self.yamamotopitch.hide()
        self.salepitch.show()
        pitcherbutton.show()

    def deGromFB1(self):
        sampley = random.uniform(0,10)
        samplex = random.uniform(-10,10)
        self.test(self.DEGROMRELEASEPOINT, 'jacobdegrom', -0.015, 0.015, samplex, sampley, 370, 'FF')
    def deGromFB2(self):
        sampley = random.uniform(10,30)
        samplex = random.uniform(15,35)
        self.test(self.DEGROMRELEASEPOINT, 'jacobdegrom', -0.015, 0.0075, samplex, sampley, 370, 'FF')
    def deGromFB3(self):
        sampley = random.uniform(-25,-5)
        samplex = random.uniform(0,20)
        self.test(self.DEGROMRELEASEPOINT, 'jacobdegrom', -0.015, 0.01, samplex, sampley, 370, 'FF')
    def deGromSlider(self):
        sampley = random.uniform(5,-5)
        samplex = random.uniform(-20,20)
        self.test(self.DEGROMRELEASEPOINT, 'jacobdegrom', 0.025, 0.04, samplex, sampley, 410, 'SL')
    def deGromChangeup(self):
        sampley = random.uniform(10,20)
        samplex = random.uniform(-10,30)
        self.test(self.DEGROMRELEASEPOINT, 'jacobdegrom', -0.015, 0.040, samplex, sampley, 400, 'CH')

    def saleSinker(self):
        sampley = random.uniform(0,10)
        samplex = random.uniform(-25,5)
        self.test(self.SALERELEASEPOINT, 'chrissale', 0.015, 0.035, samplex, sampley, 400, 'FF')
    def saleUpLeftFastball(self):
        sampley = random.uniform(0,-25)
        samplex = random.uniform(-45,-15)
        self.test(self.SALERELEASEPOINT, 'chrissale', 0.005, 0.01, samplex, sampley, 400, 'FF')
    def saleDownRightFastball(self):
        sampley = random.uniform(10,30)
        samplex = random.uniform(-20,5)
        self.test(self.SALERELEASEPOINT, 'chrissale', 0.015, 0.01, samplex, sampley, 380, 'FF')
    def saleMiddleMiddleFastball(self):
        sampley = random.uniform(0,20)
        samplex = random.uniform(-10,-30)
        self.test(self.SALERELEASEPOINT, 'chrissale', 0.01, 0.01, samplex, sampley, 380, 'FF')
    def saleDownLeftFastball(self):
        sampley = random.uniform(10,25)
        samplex = random.uniform(-35,-50)
        self.test(self.SALERELEASEPOINT, 'chrissale', 0.01, 0.01, samplex, sampley, 380, 'FF')
    def saleUpRightFastball(self):
        sampley = random.uniform(10, -20)
        samplex = random.uniform(-25,0)
        self.test(self.SALERELEASEPOINT, 'chrissale', 0.015, 0.01, samplex, sampley, 380, 'FF')
    def saleChangeup(self):
        sampley = random.uniform(-10,10)
        samplex = random.uniform(-20,0)
        self.test(self.SALERELEASEPOINT, 'chrissale', 0.01, 0.04, samplex, sampley, 450, 'CH')
    def saleSlider(self):
        sampley = random.uniform(-15,5)
        samplex = random.uniform(-20,25)
        self.test(self.SALERELEASEPOINT, 'chrissale', -0.045, 0.04, samplex, sampley, 500, 'SL')

    def sasakiSplitter(self):
        sampley = random.uniform(-5,20)
        samplex = random.uniform(-10,20)
        horizontalBreak = random.uniform(-0.01, 0.01)
        self.test(self.SASAKIRELEASEPOINT, 'rokisasaki', horizontalBreak, 0.05, samplex, sampley, 450, 'FS')
    def sasakiFastball(self):
        sampley = random.uniform(-5,15)
        samplex = random.uniform(-10,20)
        self.test(self.SASAKIRELEASEPOINT, 'rokisasaki', -0.015, 0.01, samplex, sampley, 370, 'FF')
    def sasakiLowFastball(self):
        sampley = random.uniform(20,35)
        samplex = random.uniform(0,45)
        self.test(self.SASAKIRELEASEPOINT, 'rokisasaki', -0.02, 0.015, samplex, sampley, 370, 'FF')

    def sasakiFastball2(self):
        sampley = random.uniform(-5,5)
        samplex = random.uniform(0, 15)
        self.test(self.SASAKIRELEASEPOINT, 'rokisasaki', -0.005, 0.055, samplex, sampley, 370, 'FF')

    def sasakiFastball3(self):
        sampley = random.uniform(-5,5)
        samplex = random.uniform(-25, 25)
        ivb = random.uniform(0.005, 0.095)
        ihb = random.uniform(-0.005, 0.005)
        self.test(self.SASAKIRELEASEPOINT, 'rokisasaki', ihb, ivb, (ihb*50), (ivb*5), 380, 'SI')

    def yamamotoCurve(self):
        sampley = random.uniform(0,-20)
        samplex = random.uniform(-10,20)
        self.test(self.YAMAMOTORELEASEPOINT, 'Yamamoto', 0, 0.06, samplex, sampley, 450, 'CB')
    def yamamotoHighFastball(self):
        sampley = random.uniform(0,-20)
        samplex = random.uniform(-10,20)
        self.test(self.YAMAMOTORELEASEPOINT, 'Yamamoto', -0.01, 0.01, samplex, sampley, 450, 'FF')
    def yamamotoFastball(self):
        sampley = random.uniform(0, 40)
        samplex = random.uniform(0,40)
        self.test(self.YAMAMOTORELEASEPOINT, 'Yamamoto', -0.015, 0.005, samplex, sampley, 380, 'FF')
    def yamamotoSplitter(self):
        sampley = random.uniform(-5, 10)
        samplex = random.uniform(-10,20)
        self.test(self.YAMAMOTORELEASEPOINT, 'Yamamoto', random.uniform(-0.02, 0), 0.05, samplex, sampley, 450, 'FS')
    def yamamotoCutter(self):
        sampley = random.uniform(-10, 30)
        samplex = random.uniform(-10,30)
        self.test(self.YAMAMOTORELEASEPOINT, 'Yamamoto', 0.0025, 0.015, samplex, sampley, 400, 'FC')


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
            else:
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
                self.manager.update(time_delta)
                self.screen.fill("black")
                if self.menu_state == 'Sale':
                    self.gameButtons(self.salepitch)
                    self.Sale(1)
                elif self.menu_state == 'Degrom':
                    self.gameButtons(self.degrompitch)
                    self.Degrom(1)
                elif self.menu_state == 'Sasaki':
                    self.gameButtons(self.sasakipitch)
                    self.Sasaki(1)
                elif self.menu_state == 'Yamamoto':
                    self.gameButtons(self.yamamotopitch)
                    self.Yamamoto(1)
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


        print(self.records)
        self.records.to_csv('ai_ump_pitch_data.csv', mode='a', header=False, index=False)

def main():
    Game()
    pygame.quit()

if __name__ == "__main__":
    main()