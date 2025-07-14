import pygame
from config import get_path, resource_path

class Batter:
    def __init__(self, screen):
        self.screen = screen
        self.handedness = 'R'
        self.x = 330
        self.y = 190
        self.batter = self.loadimg('assets/images/batter_right_swing/TROUT', 15)
        self.batterhigh = self.loadimg('assets/images/batter_right_high_swing/HIGHSWING', 7)
        self.batterleft = self.loadimg('assets/images/batter_left_swing/TROUTLEFT', 15)
        self.batterlefthigh = self.loadimg('assets/images/batter_left_high_swing/HIGHSWINGLEFT', 7)

    def loadimg(self, name, number):
        name = get_path(name)
        counter = 1
        storage = []
        while counter <= number:
            storage.append(pygame.image.load(resource_path(f'{name}{counter}.png')).convert_alpha())
            counter += 1
        return storage
        
    def set_handedness(self, hand):
        self.handedness = hand
        self.x = 330 if hand == 'R' else 735

    def get_handedness(self):
        return self.handedness
    
    def toggle_handedness(self):
        if self.handedness == 'R':
            self.handedness = 'L'
            self.x = 735
        else:
            self.handedness = 'R'
            self.x = 330
        
    def draw_stance(self, number=1, xoffset=0, yoffset=0):
        if self.handedness == 'R':
            self.screen.blit(self.batter[number - 1], (self.x + xoffset, self.y + yoffset))
        else:
            self.screen.blit(self.batterleft[number - 1], (self.x + xoffset, self.y + yoffset))
            
    def draw_high_swing(self, number, xoffset=0, yoffset=0):
        if self.handedness == 'R':
            self.screen.blit(self.batterhigh[number - 1], (self.x + xoffset, self.y + yoffset))
        else:
            self.screen.blit(self.batterlefthigh[number - 1], (self.x + xoffset, self.y + yoffset))
            
    # Default stance if no swing
    def leg_kick(self, currenttime, start_time):
        if currenttime <= start_time + 50:
            self.draw_stance(1, 0, 0)
        elif currenttime > start_time + 50 and currenttime <= start_time + 200:
            self.draw_stance(2, 11 if self.handedness == 'R' else 10, -5)
        elif currenttime > start_time + 200 and currenttime <= start_time + 300:
            self.draw_stance(3, 7 if self.handedness == 'R' else 8, -10)
        elif currenttime > start_time + 300 and currenttime <= start_time + 475:
            self.draw_stance(4, -21 if self.handedness == 'R' else -7, 11)
        elif currenttime > start_time + 475 and currenttime <= start_time + 550:
            self.draw_stance(5, -20 if self.handedness == 'R' else 10, 21)
        elif currenttime > start_time + 550 and currenttime <= start_time + 940:
            self.draw_stance(6, 21 if self.handedness == 'R' else 1, 25)
        elif currenttime > start_time + 940 and currenttime <= start_time + 1000:
            self.draw_stance(13, 12 if self.handedness == 'R' else -12, 27)
        elif currenttime > start_time + 1000 and currenttime <= start_time + 1100:
            self.draw_stance(14, 8 if self.handedness == 'R' else -8, 29)
        elif currenttime > start_time + 1100:
            self.draw_stance(15, 6 if self.handedness == 'R' else -6, 24)
        return
    
    # Low swing animation
    def swing_start(self, timenow, swing_startime):
        if timenow <= swing_startime + 110:
            self.draw_stance(6, 21 if self.handedness == 'R' else 1, 25)
        elif timenow > swing_startime + 110 and timenow <= swing_startime + 150:
            self.draw_stance(7, 7 if self.handedness == 'R' else -70, 84)
        elif timenow > swing_startime + 150 and timenow <= swing_startime + 200:
            self.draw_stance(8, 12 if self.handedness == 'R' else -83, 84)
        elif timenow > swing_startime + 200 and timenow <= swing_startime + 210:
            self.draw_stance(9, 12 if self.handedness == 'R' else 18, 84)
        elif timenow > swing_startime + 210 and timenow <= swing_startime + 225:
            self.draw_stance(10, -150 if self.handedness == 'R' else 4, 84)
        elif timenow > swing_startime + 225 and timenow <= swing_startime + 240:
            self.draw_stance(11, -177 if self.handedness == 'R' else 7, -69)
        elif timenow > swing_startime + 240:
            self.draw_stance(12, 28 if self.handedness == 'R' else -90, 48)
        return


    # High swing animation
    def high_swing_start(self, timenow, swing_startime):
        if timenow <= swing_startime + 110:
            self.draw_high_swing(1, 15 if self.handedness == 'R' else -15, 0)
        elif timenow > swing_startime + 110 and timenow <= swing_startime + 150:
            self.draw_high_swing(2, 14 if self.handedness == 'R' else -101, 70)
        elif timenow > swing_startime + 150 and timenow <= swing_startime + 200:
            self.draw_high_swing(3, 19 if self.handedness == 'R' else -108, 70)
        elif timenow > swing_startime + 200 and timenow <= swing_startime + 210:
            self.draw_high_swing(4, 14 if self.handedness == 'R' else 22, 70)
        elif timenow > swing_startime + 210 and timenow <= swing_startime + 225:
            self.draw_high_swing(5, -116 if self.handedness == 'R' else 17, 70)
        elif timenow > swing_startime + 225 and timenow <= swing_startime + 240:
            self.draw_high_swing(6, -168 if self.handedness == 'R' else -11, -1)
        elif timenow > swing_startime + 240:
            self.draw_high_swing(7, 31 if self.handedness == 'R' else -176, 70)
        return