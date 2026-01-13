from utils.physics import calculate_pitch_velocity, calculate_travel_time
from .pitcher import Pitcher
import random
import pygame

class Sasaki(Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 30,
                         (screen.get_height() / 3) + 180,
                         pygame.Vector2((screen.get_width() / 2) - 42, (screen.get_height() / 3) + 164),
                         screen,
                         'Roki Sasaki',
                         1100,
                         7.1)  # arm_extension in feet
        self.load_img(loadfunc, 'assets/images/sasaki/', 14)
        #self.add_pitch_type(self.CUI, "CUI")
        #self.add_pitch_type(self.FBI, "FBI")
        #self.add_pitch_type(self.sasakiSplitter, "FS")
        #self.add_pitch_type(self.sasakiFastball, "FF")
        #self.add_pitch_type(self.CUI, "CU")
        #self.add_pitch_type(self.sasaki_slider, "SL")
        self.add_pitch_type(self.fastball, "FF")
        #self.add_pitch_type(self.sasakiSplitter, "FS")

    def draw_pitcher(self, start_time, current_time):
        if current_time == 0 and start_time == 0:
            self.draw(self.screen, 1)
        if current_time <= start_time + 250:
            self.draw(self.screen, 1)
        elif current_time > start_time + 250 and current_time <= start_time + 350:
            self.draw(self.screen, 2, -4, -4)
        elif current_time > start_time + 350 and current_time <= start_time + 400:
            self.draw(self.screen, 3, -37, -4)
        elif current_time > start_time + 400 and current_time <= start_time + 550:
            self.draw(self.screen, 4, -31, -4)
        elif current_time > start_time + 550 and current_time <= start_time + 700:
            self.draw(self.screen, 5, -6, -5)
        elif current_time > start_time + 700 and current_time <= start_time + 800:
            self.draw(self.screen, 6, 0, -5)
        elif current_time > start_time + 800 and current_time <= start_time + 900:
            self.draw(self.screen, 7, -17, -3)
        elif current_time > start_time + 900 and current_time <= start_time + 975:
            self.draw(self.screen, 8, -24, 4)
        elif current_time > start_time + 975 and current_time <= start_time + 1000:
            self.draw(self.screen, 9, -5, 4)
        elif current_time > start_time + 1000 and current_time <= start_time + 1050:
            self.draw(self.screen, 10, 14, -3)
        elif current_time > start_time + 1050 and current_time <= start_time + 1100:
            self.draw(self.screen, 11, 2, -5)
        elif current_time > start_time + 1100 and current_time <= start_time + 1110:
            self.draw(self.screen, 12, -14, -15)
        elif current_time > start_time + 1110 and current_time <= start_time + 1120:
            self.draw(self.screen, 13, 5, 12)
        elif current_time > start_time + 1120:
            self.draw(self.screen, 14, -9, 12)

    def CUI(self, main_simulation):
        sampley = random.uniform(-17,15)
        samplex = random.uniform(-14, -5)
        speed_mph = 81.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'rokisasaki', 0.003, 0.02, samplex, sampley, travel_time, 'CU')

    def sasakiSplitter(self, main_simulation):
        sampley = random.uniform(-5,15)
        samplex = random.uniform(-10,20)
        horizontalBreak = random.uniform(-0.01, 0.01)
        speed_mph = 90.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'rokisasaki', horizontalBreak, 0.045, samplex, sampley, travel_time, 'FS')

    def fastball(self, main_simulation):
        sampley = random.uniform(-20, 40)
        samplex = random.uniform(-15, 45)
        speed_mph = 101.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'rokisasaki', -0.01, 0.005, samplex, sampley, travel_time, 'FF')

    def sasaki_slider(self, main_simulation):
        sampley = random.uniform(-30,10)
        samplex = random.uniform(-30,30)
        speed_mph = 86.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'rokisasaki', 0.015, 0.035, samplex, sampley, travel_time, 'SL')

    def FB(self, simulation_func):
        ax, ay = -0.005, 0.0025
        speed_mph = random.uniform(99, 103)
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)

        # Specify target location directly (with optional randomness)
        target_x = random.uniform(590, 670)  # x position at plate
        target_y = random.uniform(410, 460)  # y position at plate

        vx, vy = calculate_pitch_velocity(
            self.release_point,
            target_x=target_x,
            target_y=target_y,
            ax=ax,
            ay=ay,
            traveltime=travel_time
        )

        simulation_func(self.release_point, 'rokisasaki', ax, ay, vx, vy, travel_time, 'FF')

