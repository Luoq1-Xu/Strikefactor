import pygame
import random
import numpy as np
import sys
import os

#delta mov
ds=10
do=0.01

def resource_path(relative_path):
    try:
    # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

pygame.mixer.pre_init(44100, 16, 2, 4096)
pygame.init()
pop1 = pygame.mixer.Sound(resource_path("Sounds/POPSFX.mp3"))
run=True

#screensize
screensize = (width,height)=(600,600)
center=(int(width/2),int(height/2 - 100))
screen = pygame.display.set_mode(screensize)

def test():
    curr = start = pygame.time.get_ticks()
    ball = [center[0],center[1], 1000]
    while curr < start+500:
        screen.fill((0,0,0))
        w = p[2] * 30 / 5000
        pygame.draw.circle(screen,(255,255,0),(int(ball[0]/w+center[0]),int(ball[1]/w+center[1])),int(10/w))
        pygame.display.update()
        pygame.time.delay(20)
        ball[2]-=ds
        ball[1]-=1



ball = [center[0],center[1], 500]
vy = -3
vx = -5
accelx = 0.1
accely = 0.3

#Stars
points=[]
for i in range(1000):
    n1 = random.randrange(-5000,5000)
    n2 = random.randrange(-5000,5000)
    n3 = random.randrange(-5000,5000)
    points.append([n1,n2,n3])

while run:
    pygame.time.delay(10)
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            run=False

    ################## keys
    keys=pygame.key.get_pressed()

    if keys[pygame.K_w]:
        for p in points:
            p[2]-=ds
    if keys[pygame.K_s]:
        for p in points:
            p[2]+=ds

    if keys[pygame.K_t]:
        test()

    if keys[pygame.K_a] or keys[pygame.K_d]:
        if keys[pygame.K_a]:
            for p in points:
                p[0], p[2] = np.cos(-do)*p[0]-np.sin(-do)*p[2], np.sin(-do)*p[0]+np.cos(-do)*p[2]
        else:
            for p in points:
                p[0], p[2] = np.cos(do)*p[0]-np.sin(do)*p[2], np.sin(do)*p[0]+np.cos(do)*p[2]

    ###############################projection###################

    screen.fill((0,0,0))


    
    d = ball[2] * 30 / 5000
    if ball[2] > 50:
        pygame.draw.circle(screen,(255,255,255),(int(ball[0]),int(ball[1])),int(10/d))
    else:
        pop1.play()
        ball[2] = 500
        ball[1] = center[1]
        ball[0] = center[0]
        vy = 0
    ball[2] -= 10
    ball[1] += vy
    vy += accely
    print(ball)

    for p in points:
        #this is to create new stars
        if p[2]<=-5000 or p[2]>=5000:
            p[0], p[1], p[2] = random.randrange(-5000,5000), random.randrange(-5000,5000), 5000
        else:
            #this is to ignore stars which are behind the ship
            if p[2]<=0:
                pass
            else:
                w = p[2] * 30 / 5000
                pygame.draw.circle(screen,(255,255,0),(int(p[0]/w+center[0]),int(p[1]/w+center[1])),int(10/w))

    pygame.display.update()



