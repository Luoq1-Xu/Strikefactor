from .pitcher import Pitcher
import random
import pygame


class Sale(Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 40,
                         (screen.get_height() / 3) + 180,
                         pygame.Vector2((screen.get_width() / 2) + 61, (screen.get_height() / 3) + 209),
                         screen,
                         'Chris Sale',
                         1100,
                         6.7)
        self.load_img(loadfunc, 'assets/images/sale/LEFTY', 9)
        self.add_pitch_type(self.FF, 'FF')
        self.add_pitch_type(self.SL, 'SL')
        self.add_pitch_type(self.CH, 'CH')
        self.add_pitch_type(self.SI, 'SI')

    def draw_pitcher(self, start_time, current_time):
        if current_time == 0 and start_time == 0:
            self.draw(self.screen, 1)
        if current_time <= start_time + 300:
            self.draw(self.screen, 1)
        elif current_time > start_time + 300 and current_time <= start_time + 500:
            self.draw(self.screen, 2)
        elif current_time > start_time + 500 and current_time <= start_time + 700:
            self.draw(self.screen, 3)
        elif current_time > start_time + 700 and current_time <= start_time + 900:
            self.draw(self.screen, 4)
        elif current_time > start_time + 900 and current_time <= start_time + 1000:
            self.draw(self.screen, 5, 0, 10)
        elif current_time > start_time + 1000 and current_time <= start_time + 1100:
            self.draw(self.screen, 6, 10, 25)
        elif current_time > start_time + 1100 and current_time <= start_time + 1120:
            self.draw(self.screen, 7, 8, 22)
        elif current_time > start_time + 1120 and current_time <= start_time + 1140:
            self.draw(self.screen, 8, -11, 22)
        elif current_time > start_time + 1140:
            self.draw(self.screen, 9, 16, 22)

    def SL(self, simulation_func):
        speed_mph = random.gauss(79.0, 1.0)
        pfx_x = random.gauss(11.0, 0.5)    # glove-side break (inches)
        pfx_z = random.gauss(0.0, 0.5)    # minimal vertical (inches)
        target_x = random.uniform(400, 700)
        target_y = random.uniform(480, 620)
        simulation_func(self.release_point, 'chrissale', speed_mph, pfx_x, pfx_z, target_x, target_y, 'SL')

    def FF(self, simulation_func):
        speed_mph = random.gauss(94.8, 0.25)
        pfx_x = random.gauss(-9.0, 1.0)   # arm-side run (inches, LHP = catcher's left)
        pfx_z = random.gauss(15.0, 1.0)   # rise from backspin (inches)
        target_x = random.uniform(490, 670)
        target_y = random.uniform(420, 600)
        simulation_func(self.release_point, 'chrissale', speed_mph, pfx_x, pfx_z, target_x, target_y, 'FF')

    def SI(self, simulation_func):
        speed_mph = random.gauss(93.9, 0.25)
        pfx_x = random.gauss(-8.0, 1.0)  # heavy arm-side run (inches)
        pfx_z = random.gauss(5.0, 1.0)    # less rise = more sink (inches)
        target_x = random.uniform(460, 770)
        target_y = random.uniform(420, 600)
        simulation_func(self.release_point, 'chrissale', speed_mph, pfx_x, pfx_z, target_x, target_y, 'SI')

    def CH(self, simulation_func):
        speed_mph = random.gauss(87.0, 0.50)
        pfx_x = random.gauss(-17.0, 1.0)  # arm-side run (inches)
        pfx_z = random.gauss(8.0, 1.0)    # moderate rise (inches)
        target_x = random.uniform(490, 770)
        target_y = random.uniform(420, 600)
        simulation_func(self.release_point, 'chrissale', speed_mph, pfx_x, pfx_z, target_x, target_y, 'CH')
