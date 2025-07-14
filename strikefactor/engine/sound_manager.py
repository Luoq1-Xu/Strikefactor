import pygame
import os
from config import get_path, resource_path
import random

class SoundManager:
    def __init__(self, sound_dir="assets/sounds"):
        self.sound_dir = sound_dir
        self.sounds = {}
        self.pending_sounds = []
        self.load_sounds()
        
    def load_sounds(self):
        # Load all game sounds
        sound_files = {
            'pop1': "POPSFX.mp3",
            'pop2': "POP2.mp3",
            'pop3': "POP3.mp3",
            'pop4': "POP4.mp3",
            'pop5': "POP5.mp3",
            'pop6': "POP6.mp3",
            'strike': "STRIKECALL.mp3",
            'ball': "BALLCALL.mp3",
            'foul': "FOULBALL.mp3",
            'single': "SINGLE.mp3",
            'double': "DOUBLE.mp3",
            'triple': "TRIPLE.mp3",
            'homerun': "HOMERUN.mp3",
            'strike3': "CALLEDSTRIKE3.mp3",
            'sizzle': "sss.mp3"
        }
        
        for name, filename in sound_files.items():
            # Prepend the directory path
            full_path = resource_path(get_path(os.path.join(self.sound_dir, filename)))
            if os.path.exists(full_path):
                self.sounds[name] = pygame.mixer.Sound(full_path)
            else:
                print(f"Warning: Sound file not found at {full_path}")
            
    def play(self, sound_name):
        if sound_name in self.sounds:
            self.sounds[sound_name].play()
            
    def schedule_sound(self, sound_name, delay=1000):
        """Schedule a sound to be played after a delay"""
        if sound_name in self.sounds:
            play_time = pygame.time.get_ticks() + delay
            self.pending_sounds.append((play_time, sound_name))
    
    def glovepop(self):
        rand = random.randint(2,5)
        if rand == 2:
            self.play('pop2')
        elif rand == 3:
            self.play('pop6')
        else:
            self.play('pop5')
        return

    def update(self):
        """Check and play scheduled sounds. This should be called once per frame."""
        current_time = pygame.time.get_ticks()
        # Iterate over a copy since we might modify the list
        for play_time, sound_name in list(self.pending_sounds):
            if current_time >= play_time:
                self.play(sound_name)
                self.pending_sounds.remove((play_time, sound_name))