from helper import pitcher
import random
import pygame

class Yamamoto(pitcher.Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 30,
                         (screen.get_height() / 3) + 175,
                         pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183),
                         screen,
                         'Yoshinobu Yamamoto',
                         1100)
        self.load_img(loadfunc, 'Yamamoto/', 14)
        self.add_pitch_type(self.yamamoto_middle_fastball, "FFM")
        

    def yamamotoCurve(self, simulation_func):
        sampley = random.uniform(0,-20)
        samplex = random.uniform(-10,20)
        simulation_func(self.release_point, 'Yamamoto', 0, 0.06, samplex, sampley, 460, 'CB')

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


    def yamamotoCurve(self, main_simulation):
        sampley = random.uniform(0,-20)
        samplex = random.uniform(-10,20)
        main_simulation(self.release_point, 'Yamamoto', 0.001, 0.055, samplex, sampley, 460, 'CB')
    def yamamotoHighFastball(self, main_simulation):
        sampley = random.uniform(0,-20)
        samplex = random.uniform(-10,20)
        main_simulation(self.release_point, 'Yamamoto', -0.01, 0.01, samplex, sampley, 380, 'FF')
    def yamamotoFastball(self, main_simulation):
        sampley = random.uniform(0, 40)
        samplex = random.uniform(0,40)
        main_simulation(self.release_point, 'Yamamoto', -0.015, 0.005, samplex, sampley, 380, 'FF')
    def yamamoto_middle_fastball(self, main_simulation):
        sampley = random.uniform(-10,30)
        samplex = random.uniform(0,40)
        main_simulation(self.release_point, 'Yamamoto', -0.015, 0.005, samplex, sampley, 380, 'FF')
    def yamamotoSplitter(self, main_simulation):
        sampley = random.uniform(-5, 10)
        samplex = random.uniform(-10,20)
        main_simulation(self.release_point, 'Yamamoto', random.uniform(-0.02, 0.001), 0.045, samplex, sampley, 420, 'FS')
    def yamamoto_high_splitter(self, main_simulation):
        sampley = random.uniform(-20, -5)
        samplex = random.uniform(-15,25)
        main_simulation(self.release_point, 'Yamamoto', random.uniform(-0.02, 0.001), 0.045, samplex, sampley, 420, 'FSH')
    def yamamotoCutter(self, main_simulation):
        sampley = random.uniform(-10, 30)
        samplex = random.uniform(-10,30)
        main_simulation(self.release_point, 'Yamamoto', 0.001, 0.0175, samplex, sampley, 400, 'FC')
