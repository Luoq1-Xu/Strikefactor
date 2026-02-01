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
        self.add_pitch_type(self.FB, "FF")
        self.add_pitch_type(self.FS, "FS")

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

    def FB(self, simulation_func):
        ax, ay = -0.005, 0.0025
        speed_mph = random.gauss(96.1, 1.0)
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)

        # Specify target location directly (with optional randomness)
        target_x = random.uniform(590, 670)  # x position at plate
        target_y = random.uniform(410, 560)  # y position at plate

        vx, vy = calculate_pitch_velocity(
            self.release_point,
            target_x=target_x,
            target_y=target_y,
            ax=ax,
            ay=ay,
            traveltime=travel_time
        )

        simulation_func(self.release_point, 'rokisasaki', ax, ay, vx, vy, travel_time, 'FF')

    def FS(self, simulation_func):
        ax, ay = -0.005, 0.055
        speed_mph = random.gauss(85.0, 1.0)
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)

        # Specify target location directly (with optional randomness)
        target_x = random.uniform(590, 670)  # x position at plate
        target_y = random.uniform(550, 660)  # y position at plate

        vx, vy = calculate_pitch_velocity(
            self.release_point,
            target_x=target_x,
            target_y=target_y,
            ax=ax,
            ay=ay,
            traveltime=travel_time
        )

        simulation_func(self.release_point, 'rokisasaki', ax, ay, vx, vy, travel_time, 'FS')

