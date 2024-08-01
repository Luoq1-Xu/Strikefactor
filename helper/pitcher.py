import pygame
import random

class Pitcher:

    def __init__(self, xpos, ypos, release_point, screen, name) -> None:
        self.name = name
        self.xpos = xpos
        self.ypos = ypos
        self.release_point = release_point
        self.pitch_count = 0
        self.outs = 0
        self.era = 0
        self.runs = 0
        self.hits_allowed = 0
        self.strikeouts = 0
        self.walks = 0
        self.pitch_arsenal = {}
        self.actions = []
        self.screen = screen
        self.basic_stats = {
            'pitch_count': 0,
            'strikes': 0,
            'balls': 0,
            'strikeouts': 0,
            'walks': 0,
            'outs': 0,
            'hits_allowed': 0,
            'runs_allowed': 0,
            'home_runs_allowed': 0
        }

    def load_img(self, loadfunc, name, number):
        self.sprites = loadfunc(name, number)

    def draw(self, screen, number, xoffset=0, yoffset=0):
        screen.blit(self.sprites[number - 1],
                    (self.xpos + xoffset,
                     self.ypos + yoffset))

    def add_pitch_type(self, pitch_func, pitch_name):
        self.pitch_arsenal[pitch_name] = pitch_func

    def recalculate_era(self):
        if not self.outs:
            return
        era = 9 * (self.runs / (self.outs / 3))
        return era

    def update_stats(self, input_dict):
        if 'outs' in input_dict:
            self.outs += input_dict['outs']
        if 'runs' in input_dict:
            self.runs += input_dict['runs']
        if 'strikeouts' in input_dict:
            self.strikeouts += input_dict['strikeouts']
        if 'walks' in input_dict:
            self.walks += input_dict['walks']
        if 'hits_allowed' in input_dict:
            self.hits_allowed += input_dict['hits_allowed']
        if 'pitch_count' in input_dict:
            self.pitch_count += input_dict['pitch_count']
        self.era = self.recalculate_era()

    def update_basic_stats(self, input_dict):
        for key in input_dict:
            self.basic_stats[key] += input_dict[key]

    def get_basic_stats(self):
        return self.basic_stats

    def draw_pitcher(self, start_time, current_time):
        return

    def pitch(self, simulation_func, pitch_name):
        self.pitch_arsenal[pitch_name](simulation_func)

    def print_basic_stats(self):
        print(f"Pitch Count: {self.basic_stats['pitch_count']}")
        print(f"Strikes: {self.basic_stats['strikes']}")
        print(f"Balls: {self.basic_stats['balls']}")
        print(f"Strikeouts: {self.basic_stats['strikeouts']}")
        print(f"Walks: {self.basic_stats['walks']}")
        print(f"Outs: {self.basic_stats['outs']}")
        print(f"Hits Allowed: {self.basic_stats['hits_allowed']}")
        print(f"Runs Allowed: {self.basic_stats['runs_allowed']}")
        print(f"Home Runs Allowed: {self.basic_stats['home_runs_allowed']}")

    def print_stats(self):
        print(f'ERA: {self.era}')
        print(f'Outs: {self.outs}')
        print(f'Runs: {self.runs}')
        print(f'Strikeouts: {self.strikeouts}')
        print(f'Walks: {self.walks}')
        print(f"Innings Pitched: {self.outs/3.0}")
        print(f"Hits Allowed: {self.hits_allowed}")
        print(f"WHIP: { (self.hits_allowed + self.walks) / (self.outs / 3.0) }")
        print(f"Pitches Thrown: {self.pitch_count}")

    def get_pitch_arsenal(self):
        return self.pitch_arsenal

    def get_pitch_names(self):
        return [key for key in self.pitch_arsenal]

    def add_action(self, action):
        self.actions.append(action)

    def random_pitch_name(self):
        return random.choice(self.get_pitch_names())

    def attach_ai(self, ai):
        self.ai = ai

    def get_ai(self):
        return self.ai