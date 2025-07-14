import pygame
import math
import os
from config import get_path, resource_path

class Ball:
    def __init__(self, screen):
        self.screen = screen
        self.position = [0, 0, 4600]  # x, y, z (distance)
        self.ball_frames = self.load_ball_frames()
        self.frame_counter = 0
        self.max_distance = 4600
        self.min_size = 3
        self.max_size = 11
        
    def load_ball_frames(self, path='Images/ball'):
        out = []
        ball_dir = get_path(path)
        for filename in os.listdir(ball_dir):
            out.append(pygame.image.load(f'{ball_dir}/{filename}').convert_alpha())
        return out
        
    def set_position(self, x, y, z):
        self.position = [x, y, z]
        
    def update(self, vx, vy, ax, ay, travel_time):
        dist = self.position[2]/300
        if dist > 1:
            self.position[1] += vy * (1/dist)
            self.position[2] -= (4300 * 1000)/(60 * travel_time)
            self.position[0] += vx * (1/dist)
            vy += (ay*300) * (1/dist)
            vx += (ax*300) * (1/dist)
        return vx, vy
        
    def draw(self):
        dist = self.position[2] / self.max_distance
        size = self.min_size + (self.max_size - self.min_size) * (1 - dist)
        ratio = size / 54
        
        image = pygame.transform.scale(self.ball_frames[self.frame_counter], 
                                      (int(ratio * 64), int(ratio * 66)))
        self.screen.blit(image, (self.position[0] - (29.22 * ratio), 
                                self.position[1] - (32.62 * ratio)))
        self.frame_counter = (self.frame_counter + 1) % len(self.ball_frames)