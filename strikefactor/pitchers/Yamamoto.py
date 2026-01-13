from .pitcher import Pitcher
from utils.physics import calculate_travel_time, calculate_pitch_velocity
import random
import pygame

class Yamamoto(Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 30,
                         (screen.get_height() / 3) + 175,
                         pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183),
                         screen,
                         'Yoshinobu Yamamoto',
                         1100,
                         6.5)  # arm_extension in feet
        self.load_img(loadfunc, 'assets/images/yamamoto/', 14)
        self.add_pitch_type(self.FB, "FF")
        self.add_pitch_type(self.yamamotoSplitter, "FS")
        self.add_pitch_type(self.yamamotoCurve, "CB")

    def draw_pitcher(self, start_time, current_time):
        if current_time == 0 and start_time == 0:
            self.draw(self.screen, 1)
        if current_time <= start_time + 250:
            self.draw(self.screen, 1)
        elif current_time > start_time + 250 and current_time <= start_time + 350:
            self.draw(self.screen, 2, -6, 0)
        elif current_time > start_time + 350 and current_time <= start_time + 400:
            self.draw(self.screen, 3, -6, 0)
        elif current_time > start_time + 400 and current_time <= start_time + 550:
            self.draw(self.screen, 4, -13, -1)
        elif current_time > start_time + 550 and current_time <= start_time + 700:
            self.draw(self.screen, 5, -20, 1)
        elif current_time > start_time + 700 and current_time <= start_time + 800:
            self.draw(self.screen, 6, -26, 2)
        elif current_time > start_time + 800 and current_time <= start_time + 900:
            self.draw(self.screen, 7, -11, 3)
        elif current_time > start_time + 900 and current_time <= start_time + 975:
            self.draw(self.screen, 8, -3, 4)
        elif current_time > start_time + 975 and current_time <= start_time + 1000:
            self.draw(self.screen, 9, 8, 4)
        elif current_time > start_time + 1000 and current_time <= start_time + 1050:
            self.draw(self.screen, 10, 5, 4)
        elif current_time > start_time + 1050 and current_time <= start_time + 1100:
            self.draw(self.screen, 11, -8, 11)
        elif current_time > start_time + 1100 and current_time <= start_time + 1110:
            self.draw(self.screen, 12, -24, 1)
        elif current_time > start_time + 1110 and current_time <= start_time + 1120:
            self.draw(self.screen, 13, 5, 12)
        elif current_time > start_time + 1120:
            self.draw(self.screen, 14, -33, 19)

    def FB(self, simulation_func):
        ax, ay = -0.0055, 0.005
        speed_mph = random.gauss(96.0, 1.0)
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

        simulation_func(self.release_point, 'Yamamoto', ax, ay, vx, vy, travel_time, 'FF')


    def yamamotoCurve(self, main_simulation):
        sampley = random.uniform(10,-30)
        samplex = random.uniform(-10,20)
        speed_mph = 73.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'Yamamoto', 0.001, 0.055, samplex, sampley, travel_time, 'CB')

    def yamamotoHighFastball(self, main_simulation):
        sampley = random.uniform(0,-20)
        samplex = random.uniform(-10,20)
        speed_mph = 96.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'Yamamoto', -0.01, 0.01, samplex, sampley, travel_time, 'FF')

    def yamamotoFastball(self, main_simulation):
        sampley = random.uniform(0, 40)
        samplex = random.uniform(-5,40)
        speed_mph = 96.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'Yamamoto', -0.01, 0.005, samplex, sampley, travel_time, 'FF')

    def yamamoto_middle_fastball(self, main_simulation):
        sampley = random.uniform(-10,30)
        samplex = random.uniform(0,40)
        speed_mph = 96.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'Yamamoto', -0.015, 0.005, samplex, sampley, travel_time, 'FF')

    def yamamotoSplitter(self, main_simulation):
        sampley = random.uniform(-5, 10)
        samplex = random.uniform(-10, 35)
        speed_mph = 89.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'Yamamoto', random.uniform(-0.005, -0.02), 0.045, samplex, sampley, travel_time, 'FS')

    def yamamoto_high_splitter(self, main_simulation):
        sampley = random.uniform(-20, -5)
        samplex = random.uniform(-15, 25)
        speed_mph = 89.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'Yamamoto', random.uniform(-0.02, 0.001), 0.045, samplex, sampley, travel_time, 'FSH')

    def yamamotoCutter(self, main_simulation):
        sampley = random.uniform(-10, 20)
        samplex = random.uniform(-10, 30)
        speed_mph = 91.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'Yamamoto', 0.005, 0.015, samplex, sampley, travel_time, 'FC')

    def yamamotoSlider(self, main_simulation):
        sampley = random.uniform(-10, 30)
        samplex = random.uniform(-10, 30)
        speed_mph = 85.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'Yamamoto', 0.0125, 0.035, samplex, sampley, travel_time, 'SL')

    def yamamotoSinker(self, main_simulation):
        sampley = random.uniform(-10, 20)
        samplex = random.uniform(-10, 30)
        speed_mph = 94.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'Yamamoto', -0.015, 0.025, samplex, sampley, travel_time, 'SI')

    def yamamoto_low_fastball(self, main_simulation):
        sampley = random.uniform(25, 35)
        samplex = random.uniform(5, 35)
        speed_mph = 96.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'Yamamoto', -0.01, 0.005, samplex, sampley, travel_time, 'FF')

    def yamamoto_low_splitter(self, main_simulation):
        sampley = random.uniform(30,35)
        samplex = random.uniform(5,20)
        speed_mph = 89.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'Yamamoto', -0.015, 0.05, samplex, sampley, travel_time, 'FS')