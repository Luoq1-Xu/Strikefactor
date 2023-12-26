# BasedBall : A baseball batting simulator
import pygame
import pygame_gui
import random
import button
import sys
import os

#Setup for Conversion into EXE
def resource_path(relative_path):
    try:
    # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# pygame setup
pygame.mixer.pre_init(44100, 16, 2, 4096)
pygame.init()
screen = pygame.display.set_mode((1280, 720))
clock = pygame.time.Clock()
icon = pygame.image.load(resource_path('Images/icon.png')).convert_alpha()
pygame.display.set_icon(icon)
pygame.display.set_caption('Basedball')
running = True

#Stuff for the typing effect in main menu and summary screen
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
                          {'name': 'fira_code', 'point_size': 18, 'style': 'bold_italic'}])
player_pos = pygame.Vector2(screen.get_width() / 2, screen.get_height() / 2)
strikezone = pygame.Rect((565, 400), (130, 165))
ball_pos = (0,0)
yes = True
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
runners = 0
runs_scored = 0
swing_started = 0
hits = 0
hit_type = 0
ishomerun = ''
first_pitch_thrown = False

current_gamemode = 0
pitches_display = []

#Load Sounds
pop1 = pygame.mixer.Sound(resource_path("Sounds/POPSFX.mp3"))
pop2 = pygame.mixer.Sound(resource_path("Sounds/POP2.mp3"))
pop3 = pygame.mixer.Sound(resource_path("Sounds/POP3.mp3"))
pop4 = pygame.mixer.Sound(resource_path("Sounds/POP4.mp3"))
strikecall = pygame.mixer.Sound(resource_path("Sounds/STRIKECALL.mp3"))
ballcall = pygame.mixer.Sound(resource_path("Sounds/BALLCALL.mp3"))
foulball = pygame.mixer.Sound(resource_path("Sounds/FOULBALL.mp3"))
single = pygame.mixer.Sound(resource_path("Sounds/SINGLE.mp3"))
double = pygame.mixer.Sound(resource_path("Sounds/DOUBLE.mp3"))
triple = pygame.mixer.Sound(resource_path("Sounds/TRIPLE.mp3"))
homer = pygame.mixer.Sound(resource_path("Sounds/HOMERUN.mp3"))
called_strike_3 = pygame.mixer.Sound(resource_path("Sounds/CALLEDSTRIKE3.mp3"))


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
sasaki = loadimg('Sasaki/', 15)
yamamoto = loadimg('Yamamoto/', 14)


salebutton = pygame.image.load(resource_path('Images/salebutton.png')).convert_alpha()
degrombutton = pygame.image.load(resource_path('Images/degrombutton.png')).convert_alpha()
sasakibutton = pygame.image.load(resource_path('Images/sasakibutton.png')).convert_alpha()
yamamotobutton = pygame.image.load(resource_path('Images/yamamotobutton.png')).convert_alpha()
menu = pygame.image.load(resource_path('Images/MAINMENU.png')).convert_alpha()
faceoffsasaki = button.Button(600,500,sasakibutton, 0.5)
faceoffsale = button.Button(400,500, salebutton, 0.5)
faceoffdegrom = button.Button(400,600, degrombutton, 0.5)
faceoffyamamoto = button.Button(600,600, yamamotobutton, 0.5)
mainmenubutton = button.Button(540, 530, menu, 0.6)


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
container = pygame_gui.core.UIContainer(relative_rect=pygame.Rect((0, 0), (1280,720)),manager=manager, is_window_root_container=False)
banner = pygame_gui.elements.UILabel(relative_rect=pygame.Rect((440, 0), (400,100)), manager=manager, text="")
banner.hide()
def pitchresult(input):
    return pygame_gui.elements.UITextBox(input,relative_rect=pygame.Rect((955, 350), (250,150)),
                                        manager=manager)
def drawscoreboard(results):
    return pygame_gui.elements.UITextBox(results,relative_rect=pygame.Rect((955, 150), (250,200)),
                                        manager=manager)

#Container to house the scoreboard and textbox - to allow for previous instances to be deleted when new ones are created
def containerupdate(textbox, scoreboard):
    global container
    container.add_element(textbox)
    container.add_element(scoreboard)
    return

#Function to draw bases graphic
def draw_bases(base1, base2, base3):
    basepeople = [base1, base2, base3]
    coloured = []
    x = 0
    while x < 3:
        if basepeople[x] == "white":
            coloured.append(3)
        elif basepeople[x]== "yellow":
            coloured.append(0)
        x += 1
    pygame.draw.polygon(screen, base1, ((1115, 585), (1140, 610), (1115,635), (1090,610)),coloured[0])
    pygame.draw.polygon(screen, base2, ((1080, 550), (1105, 575), (1080,600), (1055,575)),coloured[1])
    pygame.draw.polygon(screen, base3, ((1045, 585), (1070, 610), (1045,635), (1020,610)),coloured[2])
    return

def homeplate():
    pygame.draw.polygon(screen, "white", ((565, 650), (695, 650), (695, 660), (630, 675), (565, 660)), 0)

def draw_static():
    global strikezonedrawn
    global runners
    if strikezonedrawn == 2:
        pygame.draw.rect(screen, "white", strikezone, 1)
    if strikezonedrawn == 3:
        pygame.draw.rect(screen, "white", strikezone, 1)
        pygame.draw.line(screen, "white", (565,455), (694, 455))
        pygame.draw.line(screen, "white", (565,510), (694, 510))
        pygame.draw.line(screen, "white", (565 + (130/3), 400), (565 + (130/3), 564))
        pygame.draw.line(screen, "white", (565 + 2*(130/3), 400), (565 + 2*(130/3), 564))
    #BASES EMPTY
    if runners == 0.000:
        draw_bases("white", "white", "white")
    #RUNNER ON FIRST
    elif runners == 0.100:
        draw_bases("yellow","white","white")
    #RUNNER ON FIRST, SECOND
    elif runners == 0.110:
        draw_bases("yellow", "yellow", "white")
    #RUNNER ON FIRST, SECOND, THIRD (BASES LOADED)
    elif runners == 0.111:
        draw_bases("yellow", "yellow", "yellow")
    #RUNNER ON SECOND
    elif runners == 0.010:
        draw_bases("white","yellow","white")
    #RUNNERS ON FIRST, THIRD (RUNNERS AT THE CORNERS)
    elif runners == 0.101:
        draw_bases("yellow","white","yellow")
    #RUNNERS ON SECOND, THIRD
    elif runners == 0.011:
        draw_bases("white","yellow","yellow")
    #RUNNER ON THIRD
    elif runners == 0.001:
        draw_bases("white", "white", "yellow")
    homeplate()
    return

#Simple function to check menu_state and update the display accordingly.
def check_menu():
    global currentouts
    global menu_state
    global textfinished
    if currentouts == 3:
        for event in pygame.event.get():
            if event.type == pygame_gui.UI_TEXT_EFFECT_FINISHED:
                textfinished += 1
        if textfinished == 3:
            pygame.time.delay(500)
            menu_state = 100
    return

def glovepop():
    rand = random.randint(2,4)
    if rand == 2:
        pop2.play()
    elif rand == 3:
        pop3.play()
    else:
        pop4.play()
    return


#righty pitcher position
c = (screen.get_width() / 2) - 30
d = (screen.get_height() / 3) + 180

#POSITION FOR BATTER
x = 330
y = 190


j = (screen.get_width() / 2) - 105
k = (screen.get_height() / 3) - 40


#Lefty pitcher position
a = (screen.get_width() / 2) - 40
b = (screen.get_height() / 3) + 180

def leftyone(a,b):
    screen.blit(lefty[0], (a,b))
def leftytwo(a,b):
    screen.blit(lefty[1], (a,b))
def leftythree(a,b):
    screen.blit(lefty[2], (a,b))
def leftyfour(a,b):
    screen.blit(lefty[3], (a,b))
def leftyfive(a,b):
    screen.blit(lefty[4], (a,b))
def leftysix(a,b):
    screen.blit(lefty[5], (a,b))
def leftyseven(a,b):
    screen.blit(lefty[6], (a,b))
def leftyeight(a,b):
    screen.blit(lefty[7], (a,b))
def leftynine(a,b):
    screen.blit(lefty[8], (a,b))

def rightyone(x,y):
    screen.blit(righty[0], (x,y))
def rightytwo(x,y):
    screen.blit(righty[1], (x - 10,y))
def rightythree(x,y):
    screen.blit(righty[2], (x - 13,y))
def rightyfour(x,y):
    screen.blit(righty[3], (x - 27,y + 5))
def rightyfive(x,y):
    screen.blit(righty[4], (x - 33,y + 12))
def rightysix(x,y):
    screen.blit(righty[5], (x + 12,y + 13))
def rightyseven(x,y):
    screen.blit(righty[6], (x - 20,y + 7))
def rightyeight(x,y):
    screen.blit(righty[7],(x,y + 27))
def rightynine(x,y):
    screen.blit(righty[8],(x - 11,y + 25))

def batterone(x,y):
    screen.blit(batter[0], (x,y))
def battertwo(x,y):
    screen.blit(batter[1], (x,y))
def batterthree(x,y):
    screen.blit(batter[2], (x,y))
def batterfour(x,y):
    screen.blit(batter[3], (x,y))
def batterfive(x,y):
    screen.blit(batter[4], (x,y))
def battersix(x,y):
    screen.blit(batter[5], (x,y))
def batterseven(x,y):
    screen.blit(batter[6], (x,y))
def battereight(x,y):
    screen.blit(batter[7], (x,y))
def batternine(x,y):
    screen.blit(batter[8], (x,y))
def batterten(x,y):
    screen.blit(batter[9], (x,y))
def battereleven(x,y):
    screen.blit(batter[10], (x,y))
def battertwelve(x,y):
    screen.blit(batter[11], (x,y))
def batterthirteen(x,y):
    screen.blit(batter[12], (x + 12,y + 27))
def batterfourteen(x,y):
    screen.blit(batter[13], (x + 8,y + 29))
def batterfifteen(x,y):
    screen.blit(batter[14], (x + 6,y + 24))


def highswingone(x,y):
    screen.blit(batterhigh[0], (x,y))
def highswingtwo(x,y):
    screen.blit(batterhigh[1], (x,y))
def highswingthree(x,y):
    screen.blit(batterhigh[2], (x,y))
def highswingfour(x,y):
    screen.blit(batterhigh[3], (x,y))
def highswingfive(x,y):
    screen.blit(batterhigh[4], (x,y))
def highswingsix(x,y):
    screen.blit(batterhigh[5], (x,y))
def highswingseven(x,y):
    screen.blit(batterhigh[6], (x,y))


def roki1(x,y):
    screen.blit(sasaki[0], (x,y))
def roki2(x,y):
    screen.blit(sasaki[1], (x-4,y-4))
def roki3(x,y):
    screen.blit(sasaki[2], (x-37,y-4))
def roki4(x,y):
    screen.blit(sasaki[3], (x-31,y-4))
def roki5(x,y):
    screen.blit(sasaki[4], (x-6,y-5))
def roki6(x,y):
    screen.blit(sasaki[5], (x,y-5))
def roki7(x,y):
    screen.blit(sasaki[6], (x-17,y-3))
def roki8(x,y):
    screen.blit(sasaki[7], (x-24,y+4))
def roki9(x,y):
    screen.blit(sasaki[8], (x-5,y+4))
def roki10(x,y):
    screen.blit(sasaki[9], (x+14,y-3))
def roki11(x,y):
    screen.blit(sasaki[10], (x+2,y-5))
def roki12(x,y):
    screen.blit(sasaki[11], (x-14,y-15))
def roki13(x,y):
    screen.blit(sasaki[12], (x+5,y+12))
def roki14(x,y):
    screen.blit(sasaki[13], (x-9,y+12))
def roki15(x,y):
    screen.blit(sasaki[14], (x-39,y+9))
def roki16(x,y):
    screen.blit(sasaki[15], (x,y))


def yamamoto1(x,y):
    screen.blit(yamamoto[0], (x,y))
def yamamoto2(x,y):
    screen.blit(yamamoto[1], (x - 6,y))
def yamamoto3(x,y):
    screen.blit(yamamoto[2], (x - 6,y))
def yamamoto4(x,y):
    screen.blit(yamamoto[3], (x - 13,y - 1))
def yamamoto5(x,y):
    screen.blit(yamamoto[4], (x - 20,y + 1))
def yamamoto6(x,y):
    screen.blit(yamamoto[5], (x - 26,y + 2))
def yamamoto7(x,y):
    screen.blit(yamamoto[6], (x - 11,y + 3))
def yamamoto8(x,y):
    screen.blit(yamamoto[7], (x - 3,y + 4))
def yamamoto9(x,y):
    screen.blit(yamamoto[8], (x + 8,y + 4))
def yamamoto10(x,y):
    screen.blit(yamamoto[9], (x + 5,y + 4))
def yamamoto11(x,y):
    screen.blit(yamamoto[10], (x - 8,y + 11))
def yamamoto12(x,y):
    screen.blit(yamamoto[11], (x - 24,y + 1))
def yamamoto13(x,y):
    screen.blit(yamamoto[12], (x - 4, y + 21))
def yamamoto14(x,y):
    screen.blit(yamamoto[13], (x - 33, y + 19))



#Outcomes for a successful contact hit
def contact_hit_outcome():
    global runners
    global runs_scored
    global hit_type
    rand = random.uniform(0,10)
    if rand > 0 and rand <= 8:
        hit_type = 1
        update_runners_and_score(1)
        return "SINGLE"
    elif rand > 8 and rand <= 9:
        hit_type = 2
        update_runners_and_score(2)
        return "DOUBLE"
    elif rand > 9 and rand <= 9.3:
        hit_type = 3
        update_runners_and_score(3)
        return "TRIPLE"
    elif rand > 9.3 and rand <= 10:
        hit_type = 4
        update_runners_and_score(4)
        return "HOME RUN"

#Outcomes for a successful power hit
def power_hit_outcome():
    global runners
    global runs_scored
    global hit_type
    rand = random.uniform(0,10)
    if rand > 0 and rand <= 3:
        hit_type = 1
        update_runners_and_score(1)
        return "SINGLE"
    elif rand > 3 and rand <= 6.5:
        hit_type = 2
        update_runners_and_score(2)
        return "DOUBLE"
    elif rand > 6.5 and rand <= 7.5:
        hit_type = 3
        update_runners_and_score(3)
        return "TRIPLE"
    elif rand > 7.5 and rand <= 10:
        hit_type = 4
        update_runners_and_score(4)
        return "HOME RUN"

#LOGIC FOR UPDATING BASERUNNERS AFTER A HIT
def update_runners_and_score(hit_type):
    global runners
    global runs_scored
    global ishomerun
    ishomerun = ''

    if hit_type == 1:
        if runners == 0.000:
            runners = 0.100
        elif runners == 0.100:
            runners = 0.110
        elif runners == 0.010:
            runners = 0.101
        elif runners == 0.001:
            runners = 0.100
            runs_scored += 1
        elif runners == 0.110:
            runners = 0.111
        elif runners == 0.011:
            runners = 0.101
            runs_scored += 1
        elif runners == 0.111:
            runs_scored += 1
        elif runners == 0.101:
            runners = 0.110
            runs_scored += 1
    elif hit_type == 2:
        if runners == 0.000:
            runners = 0.010
        elif runners == 0.100:
            runners = 0.101
        elif runners == 0.010:
            runs_scored += 1
        elif runners == 0.001:
            runners = 0.010
            runs_scored += 1
        elif runners == 0.110:
            runners = 0.011
            runs_scored += 1
        elif runners == 0.011:
            runners = 0.010
            runs_scored += 2
        elif runners == 0.111:
            runners = 0.011
            runs_scored += 2
        elif runners == 0.101:
            runners = 0.011
            runs_scored += 1
    elif hit_type == 3:
        if runners == 0.000:
            runners = 0.001
        elif runners == 0.100 or runners == 0.010 or runners == 0.001:
            runners = 0.001
            runs_scored += 1
        elif runners == 0.110 or runners == 0.011 or runners == 0.101:
            runners = 0.001
            runs_scored += 2
        elif runners == 0.111:
            runners = 0.001
            runs_scored += 3
    elif hit_type == 4:
        if runners == 0.000:
            runs_scored += 1
            ishomerun = 'SOLO HOME RUN'
        elif runners == 0.100 or runners == 0.010 or runners == 0.001:
            runners = 0.000
            runs_scored += 2
            ishomerun = '2 RUN HOME RUN'
        elif runners == 0.110 or runners == 0.011 or runners == 0.101:
            runners = 0.000
            runs_scored += 3
            ishomerun = '3 RUN HOME RUN'
        elif runners == 0.111:
            runners = 0.000
            runs_scored += 4
            ishomerun = 'GRAND SLAM'
    return

#Function to check quality of timing
def powertiming(swing_starttime, starttime, traveltime):
    if abs((swing_starttime + 150) - (starttime + traveltime + 1150)) > 15 and abs((swing_starttime + 150) - (starttime + traveltime + 1150)) < 30:
        return 1
    elif abs((swing_starttime + 150) - (starttime + traveltime + 1150)) <= 15:
        return 2
    else:
        return 0

def contacttiming(swing_starttime, starttime, traveltime):
    if abs((swing_starttime + 150) - (starttime + traveltime + 1150)) > 30 and abs((swing_starttime + 150) - (starttime + traveltime + 1150)) < 60:
        return 1
    elif abs((swing_starttime + 150) - (starttime + traveltime + 1150)) <= 30:
        return 2
    else:
        return 0
    

def loc_check(batpos, ballpos):
    dist = ((ballpos[0] - batpos[0])**2 + (ballpos[1] - batpos[1])**2)**(1/2)
    if dist > 30:
        outcome = "miss"
    elif 20 < dist < 30:
        outcome = "foul"
    elif 10 < dist < 20:
        outcome = "good"
    else:
        outcome = "perfect"
    print(outcome)
    return outcome



#YAMAMOTO PITCHING AI
def Yamamoto_AI():
    rando = random.uniform(1,10)
    if rando <= 5:
        yamamoto_fastball()
    elif rando <= 7:
        yamamoto_lowsplitter()
    else:
        yamamoto_lowcurveball()
    return

def yamamoto_fastball():
    rand = random.choice([yamamoto_lowinsidefastball,
                          yamamoto_lowoutsidefastball, 
                          yamamoto_highinsidefastball,
                          yamamoto_highmiddlefastball,
                          yamamoto_highoutsidefastball,
                          yamamoto_middlemiddlefastball])
    rand()
    return

#SASAKI PITCHING AI
def Sasaki_AI():
    rando = random.uniform(1,10)
    if rando <= 2:
        sasaki_highinsidefastball()
    elif rando > 2 and rando <= 4:
        sasaki_lowoutsidesplitter()
    elif rando > 4 and rando <= 6:
        sasaki_highoutsidefastball()
    elif rando > 6 and rando <= 8:
        sasaki_lowinsidefastball()
    else:
        sasaki_lowoutsidefastball()
    return


#DEGROM PITCHING AI
def pitch_decision_maker():
    global currentballs
    global currentstrikes
    rando = random.uniform(1,10)
    # 0-0  OR  1 - 1  OR 3 - 2
    if ((currentballs == 0 and currentstrikes == 0) or
        (currentballs == 4) or
        (currentstrikes == 3) or
        (currentballs == 1 and currentstrikes == 1) or
        (currentballs == 3 and currentstrikes == 2)):
        if rando >= 1 and rando <= 5:
            highoutsidefastball()
        elif rando > 5 and rando <= 7.27:
            highinsidefastball()
        elif rando > 7.27:
            lowslider()
    # 1 - 0 OR 2 - 1
    elif (currentballs == 1 and currentstrikes == 0) or (currentballs == 2 and currentstrikes == 1):
        if rando >= 1 and rando <= 4:
            highoutsidefastball()
        elif rando > 4 and rando <= 7.5:
            highinsidefastball()
        elif rando > 7.5 and rando <= 9:
            lowslider()
        else:
            lowchangeup()
    # 0 - 1  OR  2 - 2
    elif (currentballs == 0 and currentstrikes == 1) or (currentballs == 2 and currentstrikes == 2):
        if rando >= 1 and rando <= 2:
            highoutsidefastball()
        elif rando > 2 and rando <= 6:
            highinsidefastball()
        elif rando > 6 and rando <= 9.5:
            lowslider()
        else:
            lowchangeup()
    # 2 - 0  OR  3 - 1  OR  3 - 0
    elif (currentballs == 2 and currentstrikes == 0) or (currentballs == 3 and currentstrikes == 1) or (currentballs == 3 and currentstrikes == 0) :
        if rando >= 1 and rando <= 6:
            highoutsidefastball()
        elif rando > 6 and rando <= 7.5:
            highinsidefastball()
        elif rando > 7.5 and rando <= 9:
            lowslider()
        else:
            lowchangeup()
    # 0 - 2  OR  1 - 2
    elif (currentballs == 0 and currentstrikes == 2) or (currentballs == 1 and currentstrikes == 2):
        if rando >= 1 and rando <= 2:
            highoutsidefastball()
        elif rando > 2 and rando <= 5:
            highinsidefastball()
        elif rando > 5 and rando <= 9:
            lowslider()
        else:
            lowchangeup()
    return


#SALE PITCHING AI
def lefty_pitch_decision_maker():
    global currentballs
    global currentstrikes
    rando = random.uniform(1,10)
    # 0-0  OR  1 - 1  OR 3 - 2
    if ((currentballs == 0 and currentstrikes == 0) or
        (currentballs == 4) or
        (currentstrikes == 3) or
        (currentballs == 1 and currentstrikes == 1) or
        (currentballs == 3 and currentstrikes == 2)):
        if rando >= 1 and rando <= 5.36:
            highlow = random.uniform(1,10)
            if highlow >= 1 and highlow <= 6:
                lowoutsidesinker()
            else:
                sale_fastball()
        elif rando > 5.36 and rando <= 8.87:
            leftyslider()
        else:
            leftychangeup()
    # 1 - 0 OR 2 - 1
    elif (currentballs == 1 and currentstrikes == 0) or (currentballs == 2 and currentstrikes == 1):
        if rando >= 1 and rando <= 6.46:
            highlow = random.uniform(1,10)
            if highlow >= 1 and highlow <= 5:
                lowoutsidesinker()
            else:
                sale_fastball()
        elif rando > 6.46 and rando <= 9.04:
            leftyslider()
        else:
            leftychangeup()
    # 0 - 1  OR  2 - 2
    elif (currentballs == 0 and currentstrikes == 1) or (currentballs == 2 and currentstrikes == 2):
        if rando >= 1 and rando <= 6.39:
            highlow = random.uniform(1,10)
            if highlow >= 1 and highlow <= 4:
                lowoutsidesinker()
            else:
                sale_fastball()
        elif rando > 6.39 and rando <= 8.54:
            leftyslider()
        else:
            leftychangeup()
    # 2 - 0  OR  3 - 1  OR  3 - 0
    elif (currentballs == 2 and currentstrikes == 0) or (currentballs == 3 and currentstrikes == 1) or (currentballs == 3 and currentstrikes == 0) :
        if rando >= 1 and rando <= 7:
            highlow = random.uniform(1,10)
            if highlow >= 1 and highlow <= 8:
                lowoutsidesinker()
            else:
                leftyhighfastball()
        elif rando > 7 and rando <= 9:
            leftyslider()
        else:
            leftychangeup()
    # 0 - 2  OR  1 - 2
    elif (currentballs == 0 and currentstrikes == 2) or (currentballs == 1 and currentstrikes == 2):
        if rando >= 1 and rando <= 4.5:
            highlow = random.uniform(1,10)
            if highlow >= 1 and highlow <= 3:
                lowoutsidesinker()
            else:
                sale_fastball()
        elif rando > 4.5 and rando <= 8.5:
            leftyslider()
        else:
            leftychangeup()
    return


def sale_fastball():
    rand = random.choice([leftyhighfastball,
                          leftylowinsidefastball,
                          leftyhighmiddlefastball])
    rand()
    return


#YAMAMOTO PITCH TYPES
def yamamoto_lowoutsidefastball():
    vertbreakvariable = random.uniform(0,0.25)
    horizontalvariation = random.uniform(0,0.95)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183)
    simulate(True, ball_pos, 0.35 + horizontalvariation, 0.15, 0.075, 0.150 + vertbreakvariable, 4, 380, 0.5 + vertbreakvariable, 0.25, 100, 'Yamamoto', 'FASTBALL')
    return
def yamamoto_lowinsidefastball():
    vertbreakvariable = random.uniform(0,0.20)
    horizontalvariation = random.uniform(-0.25,0.25)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183)
    simulate(True, ball_pos, 0.25, -0.025, -0.05, 0.200 + vertbreakvariable, 4, 380, 0.350 + vertbreakvariable, -0.15 + horizontalvariation, 100, 'Yamamoto', 'FASTBALL')
    return
def yamamoto_lowcurveball():
    vertbreakvariability = random.uniform(0,0.10)
    horizontalbreakvariability = random.uniform(-0.10,0.10)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183)
    simulate(True, ball_pos, 1, 0.150 + horizontalbreakvariability, -0.75, 0.250 + vertbreakvariability, 4, 440, 0.600 + vertbreakvariability, 0.025 + horizontalbreakvariability, 125, 'Yamamoto', 'CURVEBALL')
    return
def yamamoto_lowsplitter():
    vertbreakvariability = random.uniform(0,0.15)
    horizontalbreakvariability = random.uniform(-0.10,0)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183)
    simulate(True, ball_pos, 0.5, -0.0025 + horizontalbreakvariability, 0.05, 0.200 + vertbreakvariability, 4, 420, 0.650 + vertbreakvariability, -0.05 + horizontalbreakvariability, 125, 'Yamamoto', 'SPLITTER')
    return
def yamamoto_highinsidefastball():
    vertbreakvariable = random.uniform(0,0.095)
    horizontalbreakvariable = random.uniform(-0.05,0)
    yoffset = random.uniform(-0.5,0.5)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183)
    simulate(True, ball_pos, -0.25, -0.035 + horizontalbreakvariable, -1.75 + yoffset, 0.05 + vertbreakvariable, 4, 380, 0.10 + vertbreakvariable, -0.1 + horizontalbreakvariable, 150, 'Yamamoto', 'FASTBALL')
    return
def yamamoto_highmiddlefastball():
    vertbreakvariable = random.uniform(0,0.095)
    horizontalbreakvariable = random.uniform(-0.05,0)
    yoffset = random.uniform(-0.5,0.5)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183)
    simulate(True, ball_pos, 0.75, 0.05 + horizontalbreakvariable, -2.0 + yoffset, 0.05 + vertbreakvariable, 4, 380, 0.10 + vertbreakvariable, 0.075 + horizontalbreakvariable, 150, 'Yamamoto', 'FASTBALL')
    return
def yamamoto_highoutsidefastball():
    vertbreakvariable = random.uniform(0,0.095)
    horizontalbreakvariable = random.uniform(-0.05,0)
    yoffset = random.uniform(-0.5,0.5)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183)
    simulate(True, ball_pos, 0.75, 0.175 + horizontalbreakvariable, -1.5 + yoffset, 0.05 + vertbreakvariable, 4, 380, 0.10 + vertbreakvariable, 0.195 + horizontalbreakvariable, 150, 'Yamamoto', 'FASTBALL')
    return
def yamamoto_middlemiddlefastball():
    vertbreakvariable = random.uniform(0,0.095)
    horizontalbreakvariable = random.uniform(0, 0.05)
    yoffset = random.uniform(-0.5,0.5)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183)
    simulate(True, ball_pos, 0.75, 0.05 + horizontalbreakvariable, -0.5 + yoffset, 0.20 + vertbreakvariable, 4, 380, 0.25 + vertbreakvariable, 0.01 + horizontalbreakvariable, 150, 'Yamamoto', 'FASTBALL')
    return


#SASAKI PITCH TYPES
def sasaki_lowoutsidesplitter():
    vertbreakvariability = random.uniform(0,0.15)
    horizontalbreakvariability = random.uniform(-0.05,0.10)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 42, (screen.get_height() / 3) + 164)
    simulate(True, ball_pos, 1, 0.175 + horizontalbreakvariability, -0.25, 0.250 + vertbreakvariability, 4, 410, 0.700 + vertbreakvariability, 0.025 + horizontalbreakvariability, 125, 'rokisasaki', 'SPLITTER')
    return
def sasaki_highinsidefastball():
    vertbreakvariable = random.uniform(0,0.095)
    horizontalbreakvariable = random.uniform(-0.11,0)
    yoffset = random.uniform(-0.5,0.5)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 42, (screen.get_height() / 3) + 164)
    simulate(True, ball_pos, 0.25, -0.1 + horizontalbreakvariable, -1.5 + yoffset, 0.075 + vertbreakvariable, 4, 370, 0.050 + vertbreakvariable, -0.150 + horizontalbreakvariable, 150, 'rokisasaki', 'FASTBALL')
    return
def sasaki_lowinsidefastball():
    vertbreakvariable = random.uniform(0,0.15)
    horizontalbreakvariable = random.uniform(-0.165,0.165)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 42, (screen.get_height() / 3) + 164 )
    simulate(True, ball_pos, 0.5, 0, 0.15, 0.15, 4, 370, 1 + vertbreakvariable, -0.35 + horizontalbreakvariable, 130, 'rokisasaki', 'FASTBALL')
    return
def sasaki_highoutsidefastball():
    vertbreakvariable = random.uniform(0,0.15)
    horizontalbreakvariable = random.uniform(-0.165,0.165)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 42, (screen.get_height() / 3) + 164 )
    simulate(True, ball_pos, 0.5, 0.25, -0.15, 0.10, 4, 370, 0.25 + vertbreakvariable, 0.35 + horizontalbreakvariable, 130, 'rokisasaki', 'FASTBALL')
    return
def sasaki_lowoutsidefastball():
    vertbreakvariable = random.uniform(0,0.15)
    horizontalbreakvariable = random.uniform(-0.165,0.165)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 42, (screen.get_height() / 3) + 164 )
    simulate(True, ball_pos, 0.65, 0.15 , 0.25, 0.15, 4, 370, 1.25 + vertbreakvariable, 0.35 + horizontalbreakvariable, 130, 'rokisasaki', 'FASTBALL')
    return

#DEGROM PITCH TYPES
def highoutsidefastball():
    vertbreakvariability = random.uniform(0,0.10)
    horizontalbreakvariability = random.uniform(0,0.20)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 45, (screen.get_height() / 3) + 187)
    simulate(True, ball_pos, 1, 0.1 + horizontalbreakvariability, -0.75, 0.05 + vertbreakvariability, 4, 370, 0.15 + vertbreakvariability, 0.05 + horizontalbreakvariability, 150, 'jacobdegrom', 'FASTBALL')
    return
def highinsidefastball():
    vertbreakvariable = random.uniform(0,0.065)
    horizontalbreakvariable = random.uniform(-0.05,0)
    yoffset = random.uniform(-0.5,0.25)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 45, (screen.get_height() / 3) + 187)
    simulate(True, ball_pos, 0.5, -0.075 + horizontalbreakvariable, -2.75 + yoffset, 0.085 + vertbreakvariable, 4, 370, 0.05 + vertbreakvariable, -0.025 + horizontalbreakvariable, 150, 'jacobdegrom', 'FASTBALL')
    return
def lowslider():
    vertbreakvariability = random.uniform(0,0.15)
    horizontalbreakvariability = random.uniform(0,0.10)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 45, (screen.get_height() / 3) + 187)
    simulate(True, ball_pos, 0.75, 0.200 + horizontalbreakvariability, -0.30, 0.150 + vertbreakvariability, 4, 400, 0.600 + vertbreakvariability, 0.225 + horizontalbreakvariability, 100, 'jacobdegrom', 'SLIDER')
    return
def lowchangeup():
    vertbreakvariability = random.uniform(0,0.15)
    horizontalbreakvariability = random.uniform(0,-0.05)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 45, (screen.get_height() / 3) + 187)
    simulate(True, ball_pos, 1, -0.075 + horizontalbreakvariability, -0.25, 0.220 + vertbreakvariability, 4, 450, 0.450 + vertbreakvariability, -0.075 + horizontalbreakvariability, 160, 'jacobdegrom', 'CHANGEUP')
    return
def lowoutsidefastball():
    vertbreakvariability = random.uniform(0,0.10)
    horizontalbreakvariability = random.uniform(0,0.20)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 45, (screen.get_height() / 3) + 187)
    simulate(True, ball_pos, 1, 0.125 + horizontalbreakvariability, -0.25 , 0.225 + vertbreakvariability, 4, 370, 0.550 + vertbreakvariability, 0.15 + horizontalbreakvariability, 150, 'jacobdegrom', 'FASTBALL')
    return


#SALE PITCH TYPES
def leftylowinsidefastball():
    yoffset = random.uniform(0.25, 0.25)
    vertbreakvariability = random.uniform(0,0.10)
    horizontalbreakvariability = random.uniform(0,0.175)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) + 61, (screen.get_height() / 3) + 209)
    simulate(True, ball_pos, -0.25, -0.175 - horizontalbreakvariability, -0.5 + yoffset, 0.15 + vertbreakvariability, 4, 380, 0.55 + vertbreakvariability, -0.15 - horizontalbreakvariability , 100, 'chrissale', 'FASTBALL')
    return
def leftyhighfastball():
    xoffset = random.uniform(0, -0.10)
    yoffset = random.uniform(0, 0.075)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) + 61, (screen.get_height() / 3) + 209)
    simulate(True, ball_pos, -2.5, -0.2 + xoffset, -2.5, 0.055 + yoffset, 4, 380, 0.025 + yoffset, -0.25 + xoffset, 200, 'chrissale', 'FASTBALL')
    return
def leftyhighmiddlefastball():
    yoffset = random.uniform(0.25, 0.25)
    vertbreakvariability = random.uniform(0,0.10)
    horizontalbreakvariability = random.uniform(0,0.175)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) + 61, (screen.get_height() / 3) + 209)
    simulate(True, ball_pos, -0.25, -0.075 - horizontalbreakvariability, -1.25 + yoffset, -0.30 + vertbreakvariability, 4, 380, 0.10 + vertbreakvariability, -0.25 - horizontalbreakvariability , 100, 'chrissale', 'FASTBALL')
    return
def leftyslider():
    vertbreakvariability = random.uniform(0,0.10)
    horizontalbreakvariability = random.uniform(0,-0.15)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) + 61, (screen.get_height() / 3) + 209)
    simulate(True, ball_pos, -0.1, -0.200 + horizontalbreakvariability, -0.75, 0.225 + vertbreakvariability, 4, 480, 0.450 + vertbreakvariability, -0.275 + horizontalbreakvariability, 160, 'chrissale', 'SLIDER')
    return
def leftychangeup():
    vertbreakvariable = random.uniform(0,0.10)
    horizontalbreakvariable = random.uniform(0,0.165)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) + 61, (screen.get_height() / 3) + 209 )
    simulate(True, ball_pos, -1.25, -0.175 + horizontalbreakvariable, -0.45, 0.225 + vertbreakvariable, 4, 430, 0.525 + vertbreakvariable, 0.15 + horizontalbreakvariable , 175, 'chrissale', 'CHANGEUP')
    return
def lowoutsidesinker():
    vertbreakvariable = random.uniform(0,0.10)
    horizontalbreakvariable = random.uniform(-0.075,0.025)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) + 61, (screen.get_height() / 3) + 209 )
    simulate(True, ball_pos, -0.5, -0.250 + horizontalbreakvariable, -0.35, 0.15 + vertbreakvariable, 4, 380, 0.45 + vertbreakvariable, 0.075 + horizontalbreakvariable , 100, 'chrissale', 'SINKER')
    return



# CREDIT TO e-James -> https://stackoverflow.com/questions/401847/circle-rectangle-collision-detection-intersection
def collision(circlex, circley, radius, rectmiddlex, rectmiddley, rectwidth, rectheight):
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
def swing_start(timenow, swing_startime):
    if timenow <= swing_startime + 110:
        battersix(x + 21, y + 25)
    elif timenow > swing_startime + 110 and timenow <= swing_startime + 150:
        batterseven(x + 7,y + 84)
    elif timenow > swing_startime + 150 and timenow <= swing_startime + 200:
        battereight(x + 12,y + 84)
    elif timenow > swing_startime + 200 and timenow <= swing_startime + 210:
        batternine(x + 12,y + 84)
    elif timenow > swing_startime + 210 and timenow <= swing_startime + 225:
        batterten(x - 150,y + 84)
    elif timenow > swing_startime + 225 and timenow <= swing_startime + 240:
        battereleven(x - 177,y - 69)
    elif timenow > swing_startime + 240:
        battertwelve(x + 28,y + 48)
    return

#Default stance if no swing
def leg_kick(currenttime, start_time):
    if currenttime <= start_time + 50:
        batterone(x,y)
    elif currenttime > start_time + 50 and currenttime <= start_time + 200:
        battertwo(x + 11,y - 5)
    elif currenttime > start_time + 200 and currenttime <= start_time + 300:
        batterthree(x + 7,y - 10)
    elif currenttime > start_time + 300 and currenttime <= start_time + 475:
        batterfour(x - 21,y + 11)
    elif currenttime > start_time + 475 and currenttime <= start_time + 550:
        batterfive(x - 20,y + 21)
    elif currenttime > start_time + 550 and currenttime <= start_time + 940:
        battersix(x + 21, y + 25)
    elif currenttime > start_time + 940 and currenttime <= start_time + 1000:
        batterthirteen(x,y)
    elif currenttime > start_time + 1000 and currenttime <= start_time + 1100:
        batterfourteen(x,y)
    elif currenttime > start_time + 1100:
        batterfifteen(x,y)
    return

#High swing animation
def high_swing_start(timenow, swing_startime):
    if timenow <= swing_startime + 110:
        highswingone(x + 15, y)
    elif timenow > swing_startime + 110 and timenow <= swing_startime + 150:
        highswingtwo(x + 14,y + 70)
    elif timenow > swing_startime + 150 and timenow <= swing_startime + 200:
        highswingthree(x + 19,y + 70)
    elif timenow > swing_startime + 200 and timenow <= swing_startime + 210:
        highswingfour(x + 14,y + 70)
    elif timenow > swing_startime + 210 and timenow <= swing_startime + 225:
        highswingfive(x - 116,y + 70)
    elif timenow > swing_startime + 225 and timenow <= swing_startime + 240:
        highswingsix(x - 168,y - 1)
    elif timenow > swing_startime + 240:
        highswingseven(x + 31,y + 70)
    return



#GAME LOOP FOR END/SUMMARY SCREEN
def draw_inning_summary():
    global running
    global currentstrikeouts
    global currentwalks
    global currentouts
    global pitchnumber
    global currentballs
    global currentstrikes
    global menu_state
    global runs_scored
    global runners
    global just_refreshed
    global hits
    global first_pitch_thrown
    global textfinished
    global ishomerun

    textfinished = 0
    done = False
    counter = 0
    textoffset = 0
    messages_finished = 0
    messages = ["INNING OVER",
                "HITS : {}".format(hits),
                "WALKS: {}".format(currentwalks),
                "STRIKEOUTS : {}".format(currentstrikeouts),
                "RUNS SCORED : {}".format(runs_scored)]
    active_message = 0
    message = messages[active_message]

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
        mousepos = pygame.mouse.get_pos()
        if pygame.Rect((540,530), (192,29)).collidepoint(mousepos):
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND)
        else:
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
        full_message = 0
        screen.fill("black")
        if mainmenubutton.draw(screen):
            menu_state = 0
            first_pitch_thrown = False
            just_refreshed = 1
            currentballs = 0
            currentstrikes = 0
            pitchnumber = 0
            currentstrikeouts = 0
            currentwalks = 0
            currentouts = 0
            runs_scored = 0
            runners = 0
            hits = 0
            return
        clock.tick(60)/1000.0
        pygame.draw.rect(screen, 'white', [(440, 160), (400,300,)], 3)
        if counter < speed *len(message):
            counter += 1
        elif counter >= speed*len(message):
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
                oldmessage = font.render(messages[full_message], True, 'white')
                screen.blit(oldmessage, (450, 170 + offset))
                offset += 50
                full_message += 1
        snip = font.render(message[0:counter//speed], True, 'white')
        screen.blit(snip, (450, 170 + textoffset))
        pygame.display.flip()

    return

#GAME LOOP FOR MAIN MENU
def main_menu():
    global running
    global currentstrikeouts
    global currentwalks
    global currentouts
    global pitchnumber
    global currentballs
    global currentstrikes
    global menu_state
    global runs_scored
    global runners
    global just_refreshed
    global hits
    global first_pitch_thrown
    global textfinished
    global pitches_display

    done = False
    counter = 0
    textoffset = 0
    messages_finished = 0
    textfinished = 0

    messages = ["BASED BALL","A Baseball At-Bat Simulator"]

    active_message = 0
    message = messages[active_message]

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
        mousepos = pygame.mouse.get_pos()
        if pygame.Rect((400,500), (174,24)).collidepoint(mousepos) or pygame.Rect((400,600), (112, 24)).collidepoint(mousepos) or pygame.Rect((600,500), (191, 24)).collidepoint(mousepos):
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND)
        else:
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
        full_message = 0
        screen.fill("black")
        if faceoffsale.draw(screen):
            banner.hide()
            container.clear()
            menu_state = 1
            first_pitch_thrown = False
            just_refreshed = 1
            currentballs = 0
            currentstrikes = 0
            pitchnumber = 0
            currentstrikeouts = 0
            currentwalks = 0
            currentouts = 0
            runs_scored = 0
            runners = 0
            hits = 0
            pitches_display = []
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
            return
        elif faceoffdegrom.draw(screen):
            banner.hide()
            container.clear()
            menu_state = 2
            first_pitch_thrown = False
            just_refreshed = 1
            currentballs = 0
            currentstrikes = 0
            pitchnumber = 0
            currentstrikeouts = 0
            currentwalks = 0
            currentouts = 0
            runs_scored = 0
            runners = 0
            hits = 0
            pitches_display = []
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
            return
        elif faceoffsasaki.draw(screen):
            banner.hide()
            container.clear()
            menu_state = 3
            first_pitch_thrown = False
            just_refreshed = 1
            currentballs = 0
            currentstrikes = 0
            pitchnumber = 0
            currentstrikeouts = 0
            currentwalks = 0
            currentouts = 0
            runs_scored = 0
            runners = 0
            hits = 0
            pitches_display = []
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
            return
        elif faceoffyamamoto.draw(screen):
            banner.hide()
            container.clear()
            menu_state = 4
            first_pitch_thrown = False
            just_refreshed = 1
            currentballs = 0
            currentstrikes = 0
            pitchnumber = 0
            currentstrikeouts = 0
            currentwalks = 0
            currentouts = 0
            runs_scored = 0
            runners = 0
            hits = 0
            pitches_display = []
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
            return
        clock.tick(60)/1000.0
        if counter < speed *len(message):
            counter += 1
        elif counter >= speed*len(message):
            done = True
        if (active_message < len(messages) - 1 ) and done:
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
                oldmessage = bigfont.render(messages[full_message], True, 'white')
                screen.blit(oldmessage, (300, 170 + offset))
                offset += 100
                full_message += 1
        snip = bigfont.render(message[0:counter//speed], True, 'white')
        screen.blit(snip, (300, 170 + textoffset))
        pygame.display.flip()
    return


#GAME LOOP FOR AT-BAT
def simulate(yes, ball_pos, horizontalspeed,
            horizontalacceleration, verticalspeed, verticalacceleration,
            ballsize, traveltime, verticalbreak,
            horizontalbreak, breaktime, pitchername, pitchtype):

    pygame.mouse.set_cursor(pygame.cursors.Cursor(pygame.SYSTEM_CURSOR_CROSSHAIR))
    global currentballs
    global pitchnumber
    global currentstrikes
    global string
    global currentouts
    global currentstrikeouts
    global currentwalks
    global runners
    global runs_scored
    global swing_started
    global hits
    global hit_type
    global first_pitch_thrown
    global pitches_display
    first_pitch_thrown = True
    swing_started = 0

    salepitch.hide()
    strikezonetoggle.hide()
    degrompitch.hide()
    sasakipitch.hide()
    yamamotopitch.hide()
    backtomainmenu.hide()
    banner.hide()
    seepitches.hide()
    toggleumpsound.hide()

    soundplayed = 0
    on_time = 0
    made_contact = 0
    contact_time = 0
    swing_type = 0
    pitch_results_done = False

    starttime = pygame.time.get_ticks()
    current_time = starttime
    while yes:
        time_delta = clock.tick(60)/1000.0
        current_time += (time_delta*1000)
        #Pitcher Windup
        if current_time <= starttime + 1100:
            screen.fill("black")
            if pitchername == 'chrissale':
                if current_time <= starttime + 300:
                    leftyone(a,b)
                elif current_time > starttime + 300 and current_time <= starttime + 500:
                    leftytwo(a,b)
                elif current_time > starttime + 500 and current_time <= starttime + 700:
                    leftythree(a,b)
                elif current_time > starttime + 700 and current_time <= starttime + 900:
                    leftyfour(a,b)
                elif current_time > starttime + 900 and current_time <= starttime + 1000:
                    leftyfive(a,b + 10)
                elif current_time > starttime + 1000 and current_time <= starttime + 1100:
                    leftysix(a + 10,b + 25)
            elif pitchername == 'jacobdegrom':
                if current_time <= starttime + 300:
                    rightyone(c,d)
                elif current_time > starttime + 300 and current_time <= starttime + 500:
                    rightytwo(c,d)
                elif current_time > starttime + 500 and current_time <= starttime + 700:
                    rightythree(c,d)
                elif current_time > starttime + 700 and current_time <= starttime + 900:
                    rightyfour(c,d)
                elif current_time > starttime + 900 and current_time <= starttime + 1000:
                    rightyfive(c,d)
                elif current_time > starttime + 1000 and current_time <= starttime + 1100:
                    rightysix(c,d)
            elif pitchername == 'rokisasaki':
                if current_time <= starttime + 250:
                    roki1(c,d)
                elif current_time > starttime + 250 and current_time <= starttime + 350:
                    roki2(c,d)
                elif current_time > starttime + 350 and current_time <= starttime + 400:
                    roki3(c,d)
                elif current_time > starttime + 400 and current_time <= starttime + 550:
                    roki4(c,d)
                elif current_time > starttime + 550 and current_time <= starttime + 700:
                    roki5(c,d)
                elif current_time > starttime + 700 and current_time <= starttime + 800:
                    roki6(c,d)
                elif current_time > starttime + 800 and current_time <= starttime + 900:
                    roki7(c,d)
                elif current_time > starttime + 900 and current_time <= starttime + 975:
                    roki8(c,d)
                elif current_time > starttime + 975 and current_time <= starttime + 1000:
                    roki9(c,d)
                elif current_time > starttime + 1000 and current_time <= starttime + 1050:
                    roki10(c,d)
                elif current_time > starttime + 1050 and current_time <= starttime + 1100:
                    roki11(c,d)
            elif pitchername == 'Yamamoto':
                if current_time <= starttime + 250:
                    yamamoto1(c,d)
                elif current_time > starttime + 250 and current_time <= starttime + 350:
                    yamamoto2(c,d)
                elif current_time > starttime + 350 and current_time <= starttime + 400:
                    yamamoto3(c,d)
                elif current_time > starttime + 400 and current_time <= starttime + 550:
                    yamamoto4(c,d)
                elif current_time > starttime + 550 and current_time <= starttime + 700:
                    yamamoto5(c,d)
                elif current_time > starttime + 700 and current_time <= starttime + 800:
                    yamamoto6(c,d)
                elif current_time > starttime + 800 and current_time <= starttime + 900:
                    yamamoto7(c,d)
                elif current_time > starttime + 900 and current_time <= starttime + 975:
                    yamamoto8(c,d)
                elif current_time > starttime + 975 and current_time <= starttime + 1000:
                    yamamoto9(c,d)
                elif current_time > starttime + 1000 and current_time <= starttime + 1050:
                    yamamoto10(c,d)
                elif current_time > starttime + 1050 and current_time <= starttime + 1100:
                    yamamoto11(c,d)
            leg_kick(current_time, starttime + 700)
            draw_static()
            manager.update(time_delta)
            manager.draw_ui(screen)
            pygame.display.flip()

        #From time ball leaves the hand until ball finishes traveling
        if (current_time > starttime + 1100 and current_time < starttime + traveltime + 1150 and (on_time == 0 or (on_time > 0 and made_contact == 1))) or (on_time > 0 and current_time <= contact_time and made_contact == 0):
            screen.fill("black")
            if current_time > starttime + 1100 and current_time <= starttime + 1150:
                if pitchername == 'chrissale':
                    leftyseven(a + 8,b + 22)
                elif pitchername == 'jacobdegrom':
                    rightyseven(c,d)
                elif pitchername == 'rokisasaki':
                    roki12(c,d)
                elif pitchername == 'Yamamoto':
                    yamamoto12(c,d)
                pygame.draw.circle(screen, "white", ball_pos, ballsize)
                ball_pos.y += verticalspeed
                ball_pos.x += horizontalspeed
                horizontalspeed += horizontalacceleration
                verticalspeed += verticalacceleration
                ballsize = ballsize * 1.030
            #Ball continuing to travel because swing was too off timing
            elif current_time > starttime + 1150 and current_time <= starttime + breaktime + 1150 and on_time == 0:
                if current_time > starttime + 1150 and current_time <= starttime + 1200:
                    if pitchername == 'chrissale':
                        leftyeight(a - 11,b + 22)
                    elif pitchername == 'jacobdegrom':
                        rightyeight(c, d)
                    elif pitchername == 'rokisasaki':
                        roki13(c,d)
                    elif pitchername == 'Yamamoto':
                        yamamoto13(c,d)
                else:
                    if pitchername == 'chrissale':
                        leftynine(a + 16, b + 22)
                    elif pitchername == 'jacobdegrom':
                        rightynine(c, d)
                    elif pitchername == 'rokisasaki':
                        roki14(c,d)
                    elif pitchername == 'Yamamoto':
                        yamamoto14(c,d)
                pygame.draw.circle(screen, "white", ball_pos, ballsize)
                ball_pos.y += verticalspeed
                ball_pos.x += horizontalspeed
                horizontalspeed += horizontalacceleration
                verticalspeed += verticalacceleration
                ballsize = ballsize * 1.030
            elif (current_time > starttime + breaktime + 1150 and current_time <= starttime + traveltime + 1150 and (on_time == 0 or (on_time > 0 and made_contact == 1))) or (on_time > 0 and current_time <= contact_time and made_contact == 0):
                if pitchername == 'chrissale':
                    leftynine(a + 16, b + 22)
                elif pitchername == 'jacobdegrom':
                    rightynine(c, d)
                elif pitchername == 'rokisasaki':
                    roki14(c,d)
                elif pitchername == 'Yamamoto':
                    yamamoto14(c,d)
                pygame.draw.circle(screen, "white", ball_pos, ballsize)
                ball_pos.y += verticalspeed
                ball_pos.x += horizontalspeed
                horizontalspeed += horizontalbreak
                verticalspeed += verticalbreak
                ballsize = ballsize * 1.030
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN:
                    #CONTACT SWING
                    if event.key == pygame.K_w and swing_started == 0:
                        swing_type = 1
                        mousepos = pygame.mouse.get_pos()
                        #LOW SWING
                        if mousepos[1] > 500:
                            swing_starttime = pygame.time.get_ticks()
                            swing_started = 1
                            contact_time = swing_starttime + 150
                            on_time = contacttiming(swing_starttime,starttime,traveltime)
                        #HIGH SWING
                        elif mousepos[1] < 500:
                            swing_starttime = pygame.time.get_ticks()
                            swing_started = 2
                            contact_time = swing_starttime + 150
                            on_time = contacttiming(swing_starttime,starttime,traveltime)
                    #POWER SWING
                    elif event.key == pygame.K_e and swing_started == 0:
                        swing_type = 2
                        mousepos = pygame.mouse.get_pos()
                        #LOW SWING
                        if mousepos[1] > 500:
                            swing_starttime = pygame.time.get_ticks()
                            swing_started = 1
                            contact_time = swing_starttime + 150
                            on_time = powertiming(swing_starttime,starttime,traveltime)
                        #HIGH SWING
                        elif mousepos[1] < 500:
                            swing_starttime = pygame.time.get_ticks()
                            swing_started = 2
                            contact_time = swing_starttime + 150
                            on_time = powertiming(swing_starttime,starttime,traveltime)

            if swing_started > 0:
                timenow = current_time
                if swing_started == 1:
                    swing_start(timenow, swing_starttime)
                else:
                    high_swing_start(timenow, swing_starttime)
            elif swing_started == 0:
                leg_kick(current_time, starttime + 700)
            draw_static()
            manager.update(time_delta)
            manager.draw_ui(screen)
            pygame.display.flip()

            if (current_time > (starttime + traveltime + 1050) and soundplayed == 0 and on_time == 0) or (current_time > contact_time and soundplayed == 0 and (on_time > 0 and made_contact == 1)):
                glovepop()
                soundplayed += 1

        #FOUL BALL TIMING
        elif on_time == 1 and current_time > contact_time and current_time <= starttime + traveltime + 1800 and pitch_results_done == False and made_contact == 0:
            if pitchername == 'chrissale':
                leftynine(a + 16, b + 22)
            elif pitchername == 'jacobdegrom':
                rightynine(c, d)
            elif pitchername == 'rokisasaki':
                roki14(c, d)
            elif pitchername == 'Yamamoto':
                yamamoto14(c,d)
            if swing_started > 0:
                timenow = current_time
                if swing_started == 1:
                    swing_start(timenow, swing_starttime)
                else:
                    high_swing_start(timenow, swing_starttime)
            elif swing_started == 0:
                leg_kick(current_time, starttime + 700)
            #TIMING ON BUT SWING PATH OFF (SWING OVER OR UNDER BALL)
            outcome = loc_check(mousepos, ball_pos)
            if outcome == 'miss':
                made_contact = 1
            #TIMING ON AND PATH ON - FOUL BALL
            else:
                made_contact = 2
                pitch_results_done = True
                pitchnumber += 1
                if currentstrikes == 2:
                    container.clear()
                    string = "<font size=5>PITCH {}: {}<br>FOUL<br>COUNT IS {} - {}</font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    textbox = pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                    scoreboard = drawscoreboard(result)
                    containerupdate(textbox,scoreboard)
                else:
                    currentstrikes += 1
                    container.clear()
                    string = "<font size=5>PITCH {}: {}<br>FOUL<br>COUNT IS {} - {}</font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    textbox = pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                    scoreboard = drawscoreboard(result)
                    containerupdate(textbox,scoreboard)

        #PERFECT TIMING
        elif on_time == 2 and current_time > contact_time and current_time <= starttime + traveltime + 1800 and pitch_results_done == False and made_contact == 0:
            if pitchername == 'chrissale':
                leftynine(a + 16, b + 22)
            elif pitchername == 'jacobdegrom':
                rightynine(c, d)
            elif pitchername == 'rokisasaki':
                roki14(c, d)
            elif pitchername == 'Yamamoto':
                yamamoto14(c,d)
            if swing_started > 0:
                timenow = current_time
                if swing_started == 1:
                    swing_start(timenow, swing_starttime)
                else:
                    high_swing_start(timenow, swing_starttime)
            elif swing_started == 0:
                leg_kick(current_time, starttime + 700)
            #PERFECT TIMING BUT SWING PATH OFF
            outcome = loc_check(mousepos, ball_pos)
            if outcome == 'miss':
                made_contact = 1
            #PERFECT TIMING AND SWING PATH ON - SUCCESSFUL HIT
            else:
                container.clear()
                made_contact = 2
                pitch_results_done = True
                pitchnumber += 1
                if swing_type == 1:
                    hit_string = contact_hit_outcome()
                elif swing_type == 2:
                    hit_string = power_hit_outcome()
                if ishomerun != '':
                    banner.set_text("{}".format(ishomerun))
                else:
                    banner.set_text("{}".format(hit_string))
                banner.show()
                banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR,{'time_per_letter': 0.1})
                string = "<font size=5>PITCH {}: {}<br>HIT - {}<br>COUNT IS {} - {}</font>".format(pitchnumber, pitchtype, hit_string, currentballs, currentstrikes)
                textbox = pitchresult(string)
                hits += 1
                textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                scoreboard = drawscoreboard(result)
                scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
                containerupdate(textbox, scoreboard)
                pitchnumber = 0
                currentstrikes = 0
                currentballs = 0

        #Follow through - play rest of the swing animation
        elif on_time > 0 and current_time > contact_time and current_time <= starttime + traveltime + 1800 and pitch_results_done == True and made_contact == 2:
            screen.fill("black")
            if pitchername == 'chrissale':
                leftynine(a + 16, b + 22)
            elif pitchername == 'jacobdegrom':
                rightynine(c, d)
            elif pitchername == 'rokisasaki':
                roki14(c, d)
            elif pitchername == 'Yamamoto':
                yamamoto14(c,d)
            if swing_started > 0:
                timenow = current_time
                if swing_started == 1:
                    swing_start(timenow, swing_starttime)
                else:
                    high_swing_start(timenow, swing_starttime)
            pygame.draw.circle(screen, "white", ball_pos, fourseamballsize, 2)
            draw_static()
            manager.update(time_delta)
            manager.draw_ui(screen)
            pygame.display.flip()
            #Play sounds
            if soundplayed == 0 and on_time == 1:
                foulball.play()
                soundplayed += 1
            elif soundplayed == 0 and on_time == 2:
                if hit_type == 1:
                    single.play()
                elif hit_type == 2:
                    double.play()
                elif hit_type == 3:
                    triple.play()
                elif hit_type == 4:
                    homer.play()
                soundplayed += 1

        #UPDATE RESULTS IF NO CONTACT MADE AT ALL - SWINGING STRIKE OR CALLED STRIKE OR BALL
        elif (current_time > starttime + traveltime + 1150 and pitch_results_done == False and (on_time == 0 or (on_time > 0 and made_contact == 1))):
            if pitchername == 'chrissale':
                leftynine(a + 16, b + 22)
            elif pitchername == 'jacobdegrom':
                rightynine(c, d)
            elif pitchername == 'rokisasaki':
                roki14(c, d)
            elif pitchername == 'Yamamoto':
                yamamoto14(c,d)
            if swing_started > 0:
                timenow = current_time
                if swing_started == 1:
                    swing_start(timenow, swing_starttime)
                else:
                    high_swing_start(timenow, swing_starttime)
            elif swing_started == 0:
                leg_kick(current_time, starttime + 700)
            pitch_results_done = True
            #BALL OUTSIDE THE ZONE AND NOT SWUNG AT - BALL
            if (not collision(ball_pos.x, ball_pos.y, 11, 630, 482.5, 130, 165)) and swing_started == 0:
                if umpsound:
                    ballcall.play()
                currentballs += 1
                pitchnumber += 1
                #WALK OCCURS
                if currentballs == 4:
                    container.clear()
                    string = "<font size=5>PITCH {}: {}<br>BALL<br>COUNT IS {} - {}<br><b>WALK</b></font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    textbox = pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                    currentwalks += 1
                    pitchnumber = 0
                    currentstrikes = 0
                    currentballs = 0
                    if runners == 0.000:
                        runners = 0.100
                    elif runners == 0.100 or runners == 0.010:
                        runners = 0.110
                    elif runners == 0.001:
                        runners = 0.101
                    elif runners == 0.110 or runners == 0.011 or runners == 0.101:
                        runners = 0.111
                    elif runners == 0.111:
                        runs_scored += 1
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                    scoreboard = drawscoreboard(result)
                    scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
                    containerupdate(textbox,scoreboard)
                    banner.set_text("WALK")
                    banner.show()
                    banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR,{'time_per_letter': 0.1})
                else:
                    #Normal Ball
                    container.clear()
                    string = "<font size=5>PITCH {}: {}<br>BALL<br>COUNT IS {} - {}</font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    textbox = pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                    scoreboard = drawscoreboard(result)
                    containerupdate(textbox,scoreboard)
            #STRIKE (CALLED OR SWINGING STRIKE)
            else:
                pitchnumber += 1
                currentstrikes += 1
                if swing_started == 0 and currentstrikes == 3 and umpsound:
                    called_strike_3.play()
                elif swing_started == 0 and currentstrikes != 3 and umpsound:
                    strikecall.play()
                #STRIKEOUT OCCURS
                if currentstrikes == 3:
                    container.clear()
                    if swing_started == 0:
                        string = "<font size=5>PITCH {}: {}<br>CALLED STRIKE<br>COUNT IS {} - {}<br><b>STRIKEOUT</b></font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    else:
                        string = "<font size=5>PITCH {}: {}<br>SWINGING STRIKE<br>COUNT IS {} - {}<br><b>STRIKEOUT</b></font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    textbox = pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                    currentstrikeouts += 1
                    currentouts +=1
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                    scoreboard = drawscoreboard(result)
                    scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
                    banner.set_text("STRIKEOUT")
                    banner.show()
                    banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR,{'time_per_letter': 0.1})
                    containerupdate(textbox,scoreboard)
                    pitchnumber = 0
                    currentstrikes = 0
                    currentballs = 0
                else:
                    #Normal Strike
                    container.clear()
                    if swing_started == 0:
                        string = "<font size=5>PITCH {}: {}<br>CALLED STRIKE<br>COUNT IS {} - {}<br></font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    else:
                        string = "<font size=5>PITCH {}: {}<br>SWINGING STRIKE<br>COUNT IS {} - {}<br></font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    textbox = pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                    scoreboard = drawscoreboard(result)
                    containerupdate(textbox,scoreboard)

        #FOLLOW THROUGH IF SWUNG AND MISSED and ball has already reached the plate (For late swings)
        elif current_time > starttime + traveltime + 1150 and pitch_results_done == True and current_time <= starttime + traveltime + 1800 and (on_time == 0 or (on_time > 0 and made_contact == 1)):
            screen.fill("black")
            if pitchername == 'chrissale':
                leftynine(a + 16, b + 22)
            elif pitchername == 'jacobdegrom':
                rightynine(c, d)
            elif pitchername == 'rokisasaki':
                roki14(c, d)
            elif pitchername == 'Yamamoto':
                yamamoto14(c,d)
            if (current_time > contact_time and soundplayed == 0 and (on_time > 0 and made_contact == 1)):
                glovepop()
                soundplayed += 1
            if swing_started > 0:
                timenow = current_time
                if swing_started == 1:
                    swing_start(timenow, swing_starttime)
                else:
                    high_swing_start(timenow, swing_starttime)
            elif swing_started == 0:
                leg_kick(current_time, starttime + 700)
            pygame.draw.circle(screen, "white", ball_pos, fourseamballsize, 2)
            draw_static()
            manager.update(time_delta)
            manager.draw_ui(screen)
            pygame.display.flip()

        #END LOOP (END OF PITCH)
        elif current_time > starttime + traveltime + 1800:
            yes = False
            salepitch.show()
            strikezonetoggle.show()
            backtomainmenu.show()
            sasakipitch.show()
            yamamotopitch.show()
            degrompitch.show()
            toggleumpsound.show()
            seepitches.show()

    pitches_display.append(ball_pos)
    pygame.mouse.set_cursor(pygame.cursors.Cursor(pygame.SYSTEM_CURSOR_ARROW))
    return



#Main Game Loop
while running:

    time_delta = clock.tick(60)/1000.0
    check_menu()

    if menu_state == 0:
        main_menu()
    elif menu_state == 1:
        degrompitch.hide()
        sasakipitch.hide()
        yamamotopitch.hide()
        salepitch.show()
        backtomainmenu.show()
        strikezonetoggle.show()
        toggleumpsound.show()
        return_to_game.hide()
        seepitches.show()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == strikezonetoggle:
                    if strikezonedrawn == 1:
                        strikezonedrawn = 2
                    elif strikezonedrawn == 2:
                        strikezonedrawn = 3
                    elif strikezonedrawn == 3:
                        strikezonedrawn = 1
                elif event.ui_element == toggleumpsound:
                    if umpsound == True:
                        umpsound = False
                    elif umpsound == False:
                        umpsound = True
                elif event.ui_element == salepitch:
                    lefty_pitch_decision_maker()
                elif event.ui_element == backtomainmenu:
                    menu_state = 0
                elif event.ui_element == seepitches:
                    menu_state = 200
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    lefty_pitch_decision_maker()
            manager.process_events(event)
        manager.update(time_delta)
        screen.fill("black")
        if just_refreshed == 1:
            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
            scoreboard = drawscoreboard(result)
            scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
            string = "<font size=5><br>COUNT IS {} - {}</font>".format(pitchnumber, currentballs, currentstrikes)
            textbox = pitchresult(string)
            textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
            containerupdate(textbox, scoreboard)
            just_refreshed = 0
            current_gamemode = 1
        leftyone(a,b)
        draw_static()
        batterone(x,y)
        if first_pitch_thrown:
            pygame.draw.circle(screen, "white", ball_pos, fourseamballsize, 2)
        manager.draw_ui(screen)
        pygame.display.flip()

    elif menu_state == 2:
        salepitch.hide()
        sasakipitch.hide()
        yamamotopitch.hide()
        degrompitch.show()
        backtomainmenu.show()
        strikezonetoggle.show()
        return_to_game.hide()
        seepitches.show()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == strikezonetoggle:
                    if strikezonedrawn == 1:
                        strikezonedrawn = 2
                    elif strikezonedrawn == 2:
                        strikezonedrawn = 3
                    elif strikezonedrawn == 3:
                        strikezonedrawn = 1
                elif event.ui_element == toggleumpsound:
                    if umpsound == True:
                        umpsound = False
                    elif umpsound == False:
                        umpsound = True
                elif event.ui_element == degrompitch:
                    pitch_decision_maker()
                elif event.ui_element == backtomainmenu:
                    menu_state = 0
                elif event.ui_element == seepitches:
                    menu_state = 200
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    pitch_decision_maker()
            manager.process_events(event)
        manager.update(time_delta)
        screen.fill("black")
        if just_refreshed == 1:
            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
            scoreboard = drawscoreboard(result)
            scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
            string = "<font size=5><br>COUNT IS {} - {}</font>".format(pitchnumber, currentballs, currentstrikes)
            textbox = pitchresult(string)
            textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
            containerupdate(textbox, scoreboard)
            just_refreshed = 0
            current_gamemode = 2
        manager.draw_ui(screen)
        rightyone(c,d)
        draw_static()
        batterone(x,y)
        if first_pitch_thrown:
            pygame.draw.circle(screen, "white", ball_pos, fourseamballsize, 2)
        pygame.display.flip()

    elif menu_state == 3:
        salepitch.hide()
        degrompitch.hide()
        sasakipitch.show()
        yamamotopitch.hide()
        return_to_game.hide()
        seepitches.show()
        backtomainmenu.show()
        strikezonetoggle.show()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == strikezonetoggle:
                    if strikezonedrawn == 1:
                        strikezonedrawn = 2
                    elif strikezonedrawn == 2:
                        strikezonedrawn = 3
                    elif strikezonedrawn == 3:
                        strikezonedrawn = 1
                elif event.ui_element == toggleumpsound:
                    if umpsound == True:
                        umpsound = False
                    elif umpsound == False:
                        umpsound = True
                elif event.ui_element == sasakipitch:
                    Sasaki_AI()
                elif event.ui_element == backtomainmenu:
                    menu_state = 0
                elif event.ui_element == seepitches:
                    menu_state = 200
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    Sasaki_AI()
            manager.process_events(event)
        manager.update(time_delta)
        screen.fill("black")
        if just_refreshed == 1:
            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
            scoreboard = drawscoreboard(result)
            scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
            string = "<font size=5><br>COUNT IS {} - {}</font>".format(pitchnumber, currentballs, currentstrikes)
            textbox = pitchresult(string)
            textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
            containerupdate(textbox, scoreboard)
            just_refreshed = 0
            current_gamemode = 3
        manager.draw_ui(screen)
        roki1(c,d)
        draw_static()
        batterone(x,y)
        if first_pitch_thrown:
            pygame.draw.circle(screen, "white", ball_pos, fourseamballsize, 2)
        pygame.display.flip()

    elif menu_state == 4:
        salepitch.hide()
        degrompitch.hide()
        sasakipitch.hide()
        yamamotopitch.show()
        return_to_game.hide()
        seepitches.show()
        backtomainmenu.show()
        strikezonetoggle.show()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == strikezonetoggle:
                    if strikezonedrawn == 1:
                        strikezonedrawn = 2
                    elif strikezonedrawn == 2:
                        strikezonedrawn = 3
                    elif strikezonedrawn == 3:
                        strikezonedrawn = 1
                elif event.ui_element == toggleumpsound:
                    if umpsound == True:
                        umpsound = False
                    elif umpsound == False:
                        umpsound = True
                elif event.ui_element == yamamotopitch:
                    Yamamoto_AI()
                elif event.ui_element == backtomainmenu:
                    menu_state = 0
                elif event.ui_element == seepitches:
                    menu_state = 200
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    Yamamoto_AI()
            manager.process_events(event)
        manager.update(time_delta)
        screen.fill("black")
        if just_refreshed == 1:
            result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
            scoreboard = drawscoreboard(result)
            scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
            string = "<font size=5><br>COUNT IS {} - {}</font>".format(pitchnumber, currentballs, currentstrikes)
            textbox = pitchresult(string)
            textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
            containerupdate(textbox, scoreboard)
            just_refreshed = 0
            current_gamemode = 4
        manager.draw_ui(screen)
        yamamoto1(c,d)
        draw_static()
        batterone(x,y)
        if first_pitch_thrown:
            pygame.draw.circle(screen, "white", ball_pos, fourseamballsize, 2)
        pygame.display.flip()

    elif menu_state == 200:
        salepitch.hide()
        degrompitch.hide()
        sasakipitch.hide()
        yamamotopitch.hide()
        seepitches.hide()
        return_to_game.show()
        backtomainmenu.show()
        strikezonetoggle.show()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == strikezonetoggle:
                    if strikezonedrawn == 1:
                        strikezonedrawn = 2
                    elif strikezonedrawn == 2:
                        strikezonedrawn = 3
                    elif strikezonedrawn == 3:
                        strikezonedrawn = 1
                elif event.ui_element == backtomainmenu:
                    menu_state = 0
                elif event.ui_element == return_to_game:
                    menu_state = current_gamemode
            manager.process_events(event)
        manager.update(time_delta)
        screen.fill("black")
        manager.draw_ui(screen)
        draw_static()
        batterone(x,y)
        for pitch_pos in pitches_display:
            pygame.draw.circle(screen, "white", pitch_pos, fourseamballsize, 2)
        pygame.display.flip()

    elif menu_state == 100:
        draw_inning_summary()

pygame.quit()