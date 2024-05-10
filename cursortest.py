import pygame
from pygame import gfxdraw
import math
pygame.init()

screen = pygame.display.set_mode((600,400))
clock = pygame.time.Clock()

# old type, "bitmap" cursor
cursor1 = pygame.cursors.diamond

# new type, "system" cursor
cursor2 = pygame.SYSTEM_CURSOR_HAND

def draw_arc(surface, center, radius, start_angle, stop_angle, color):
    x,y = center
    start_angle = int(start_angle%360)
    stop_angle = int(stop_angle%360)
    if start_angle == stop_angle:
        gfxdraw.circle(surface, x, y, radius, color)
    else:
        gfxdraw.arc(surface, x, y, radius, start_angle, stop_angle, color)

# new type, "color" cursor
surf = pygame.Surface((100, 30), pygame.SRCALPHA)
pygame.draw.rect(surf, (255,255,255), [5, 5, 100, 25], width=1)
cursor3 = pygame.cursors.Cursor((15,5), surf)


# Circular PCI cursor
surf2 = pygame.Surface((50, 50), pygame.SRCALPHA)
gfxdraw.aacircle(surf2, 25, 25, 15, (255,255,255))
gfxdraw.aacircle(surf2, 25, 25, 16, (255,255,255))
gfxdraw.aacircle(surf2, 25, 25, 17, (255,255,255))
crosshair = pygame.cursors.Cursor((25,25), surf2)

cursors = [cursor1, cursor2, cursor3]
cursor_index = 0

# the arguments to set_cursor can be a Cursor object
# or it will construct a Cursor object internally from the arguments
pygame.mouse.set_cursor(cursors[cursor_index])

def lol():
    starttime = pygame.time.get_ticks()
    current_time = starttime
    while current_time < starttime + 5000:
        print("lol")
        current_time = pygame.time.get_ticks()
        pygame.mouse.set_cursor(cursors[2])
        pygame.display.flip()
        clock.tick(144)
    print("OVER")

def bruh():
    pygame.mouse.set_cursor(cursors[2])
    
def stupid():
    pygame.mouse.set_cursor(cursors[1])
    clock.tick(1)

while True:
    screen.fill("purple")
    
    for event in pygame.event.get():
        if event.type == pygame.MOUSEBUTTONDOWN:
            cursor_index += 1
            cursor_index %= len(cursors)
            pygame.mouse.set_cursor(cursors[cursor_index])

        if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    pygame.mouse.set_cursor(cursors[2])
                    pygame.time.delay(300)
                    lol()
                elif event.key == pygame.K_w:
                    bruh()
                elif event.key == pygame.K_e:
                    stupid()

        if event.type == pygame.QUIT:
            pygame.quit()
            raise SystemExit

    pygame.display.flip()
    clock.tick(144)





class Runner:

    # 0 = Home plate, 1 = First base, 2 = Second base, 3 = Third base
    onBase = False
    base = 0
    speed = 1

    def __init__(self, hit):
        self.onBase = True
        self.base = hit
        self.scored = False

    def advance(self, hit):
        self.base += hit
        if self.base > 3:
            self.scored = True
            self.onBase = False
    
class ScoreKeeper:

    def __init__(self):
        self.runners = []
        self.bases = [3 * 'white']
        self.score = 0
    
    # Takes in hit_type, then returns tuple of (bases, score)
    def update_hit_event(self, hit_type):
        self.runners.append(Runner(hit_type))
        basesFilled = [3 * 'white']
        scored = 0
        for runner in self.runners[:]:
            runner.advance(hit_type)
            if runner.scored:
                self.runners.remove(runner)
                scored += 1
            else:
                basesFilled[runner.base - 1] = 'yellow'
        self.score += scored
        self.bases = basesFilled
        return (basesFilled, scored)
    
    def get_bases(self):
        return self.bases
    
    def get_score(self):




