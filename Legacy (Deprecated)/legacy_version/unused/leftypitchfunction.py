def lefty_pitch_decision_maker():
    global currentballs
    global currentstrikes
    rando = random.uniform(1,10)
    # 0-0  OR  1 - 1  OR 3 - 2
    if ((currentballs == 0 and currentstrikes == 0) or
        (currentballs == 4) or
        (currentstrikes == 3) or
        (currentballs == 1 and currentstrikes == 1) or
        (currentballs == 3 and currentstrikes == 2)):
        if rando >= 1 and rando <= 5.36:
            highlow = random.uniform(1,10)
            if highlow >= 1 and highlow <= 6:
                lowoutsidesinker()
            else:
                sale_fastball()
        elif rando > 5.36 and rando <= 8.87:
            leftyslider()
        else:
            leftychangeup()
    # 1 - 0 OR 2 - 1
    elif (currentballs == 1 and currentstrikes == 0) or (currentballs == 2 and currentstrikes == 1):
        if rando >= 1 and rando <= 6.46:
            highlow = random.uniform(1,10)
            if highlow >= 1 and highlow <= 5:
                lowoutsidesinker()
            else:
                sale_fastball()
        elif rando > 6.46 and rando <= 9.04:
            leftyslider()
        else:
            leftychangeup()
    # 0 - 1  OR  2 - 2
    elif (currentballs == 0 and currentstrikes == 1) or (currentballs == 2 and currentstrikes == 2):
        if rando >= 1 and rando <= 6.39:
            highlow = random.uniform(1,10)
            if highlow >= 1 and highlow <= 4:
                lowoutsidesinker()
            else:
                sale_fastball()
        elif rando > 6.39 and rando <= 8.54:
            leftyslider()
        else:
            leftychangeup()
    # 2 - 0  OR  3 - 1  OR  3 - 0
    elif (currentballs == 2 and currentstrikes == 0) or (currentballs == 3 and currentstrikes == 1) or (currentballs == 3 and currentstrikes == 0) :
        if rando >= 1 and rando <= 7:
            highlow = random.uniform(1,10)
            if highlow >= 1 and highlow <= 8:
                lowoutsidesinker()
            else:
                leftyhighfastball()
        elif rando > 7 and rando <= 9:
            leftyslider()
        else:
            leftychangeup()
    # 0 - 2  OR  1 - 2
    elif (currentballs == 0 and currentstrikes == 2) or (currentballs == 1 and currentstrikes == 2):
        if rando >= 1 and rando <= 4.5:
            highlow = random.uniform(1,10)
            if highlow >= 1 and highlow <= 3:
                lowoutsidesinker()
            else:
                sale_fastball()
        elif rando > 4.5 and rando <= 8.5:
            leftyslider()
        else:
            leftychangeup()
    return





    rando = random.uniform(1,10)
    if rando <= 3:
        sasaki_highinsidefastball()
    elif rando > 3 and rando <= 6:
        sasaki_lowoutsidesplitter()
    else:
        sasaki_highoutsidefastball()
    return

    rando = random.uniform(1,10)
    if rando <= 2:
        sasaki_highinsidefastball()
    elif rando > 2 and rando <= 4:
        sasaki_lowoutsidesplitter()
    elif rando > 4 and rando <= 6:
        sasaki_highoutsidefastball()
    elif rando > 6 and rando <= 8:
        sasaki_lowinsidefastball()
    else:
        sasaki_lowoutsidefastball()
    return

def sasaki_highoutsidefastball():
    vertbreakvariable = random.uniform(0,0.15)
    horizontalbreakvariable = random.uniform(0,0.165)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 42, (screen.get_height() / 3) + 164 )
    simulate(True, ball_pos, 1.5, 0.195 + horizontalbreakvariable, -0.35, 0.175 + vertbreakvariable, 4, 370, 0.25 + vertbreakvariable, 0.05 + horizontalbreakvariable , 100, 'rokisasaki', 'FASTBALL')
    return

def sasaki_lowinsidefastball():
    vertbreakvariable = random.uniform(0,0.095)
    horizontalbreakvariable = random.uniform(-0.125,0)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 42, (screen.get_height() / 3) + 164 )
    simulate(True, ball_pos, 0.25, -0.085 + horizontalbreakvariable, -0.10 , 0.30 + vertbreakvariable, 4, 370, 0.650 + vertbreakvariable, -0.145 + horizontalbreakvariable, 150, 'rokisasaki', 'FASTBALL')
    return

def sasaki_lowoutsidefastball():
    vertbreakvariable = random.uniform(0,0.20)
    horizontalbreakvariable = random.uniform(0,0.165)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 42, (screen.get_height() / 3) + 164 )
    simulate(True, ball_pos, 1.5, 0.175 + horizontalbreakvariable, -0.1, 0.250 + vertbreakvariable, 4, 370, 0.560 + vertbreakvariable, 0.055 + horizontalbreakvariable , 100, 'rokisasaki', 'FASTBALL')
    return

def sasaki_lowoutsidefastball():
    vertbreakvariable = random.uniform(0,0.15)
    horizontalbreakvariable = random.uniform(-0.165,0.165)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 42, (screen.get_height() / 3) + 164 )
    simulate(True, ball_pos, 0.65, 0.15 , 0.25, 0.15, 4, 370, 1.25 + vertbreakvariable, 0.35 + horizontalbreakvariable, 130, 'rokisasaki', 'FASTBALL')
    return


def yamamoto_lowoutsidefastball():
    vertbreakvariable = random.uniform(0,0.20)
    horizontalbreakvariable = random.uniform(0,0.165)
    global ball_pos
    ball_pos = pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183)
    simulate(True, ball_pos, 1.5, 0.175 + horizontalbreakvariable, 0.05, 0.200 + vertbreakvariable, 4, 380, 0.275 + vertbreakvariable, 0.055 + horizontalbreakvariable , 100, 'Yamamoto', 'FASTBALL')
    return



def Yamamoto_AI():
    rando = random.uniform(1,10)
    if rando <= 5:
        yamamoto_fastball()
    elif rando <= 7:
        yamamoto_lowsplitter()
    else:
        yamamoto_lowcurveball()
    return



def pitch_decision_maker():
    global currentballs
    global currentstrikes
    rando = random.uniform(1,10)
    # 0-0  OR  1 - 1  OR 3 - 2
    if ((currentballs == 0 and currentstrikes == 0) or
        (currentballs == 4) or
        (currentstrikes == 3) or
        (currentballs == 1 and currentstrikes == 1) or
        (currentballs == 3 and currentstrikes == 2)):
        if rando >= 1 and rando <= 5:
            highoutsidefastball()
        elif rando > 5 and rando <= 7.27:
            highinsidefastball()
        elif rando > 7.27:
            lowslider()
    # 1 - 0 OR 2 - 1
    elif (currentballs == 1 and currentstrikes == 0) or (currentballs == 2 and currentstrikes == 1):
        if rando >= 1 and rando <= 4:
            highoutsidefastball()
        elif rando > 4 and rando <= 7.5:
            highinsidefastball()
        elif rando > 7.5 and rando <= 9:
            lowslider()
        else:
            lowchangeup()
    # 0 - 1  OR  2 - 2
    elif (currentballs == 0 and currentstrikes == 1) or (currentballs == 2 and currentstrikes == 2):
        if rando >= 1 and rando <= 2:
            highoutsidefastball()
        elif rando > 2 and rando <= 6:
            highinsidefastball()
        elif rando > 6 and rando <= 9.5:
            lowslider()
        else:
            lowchangeup()
    # 2 - 0  OR  3 - 1  OR  3 - 0
    elif (currentballs == 2 and currentstrikes == 0) or (currentballs == 3 and currentstrikes == 1) or (currentballs == 3 and currentstrikes == 0) :
        if rando >= 1 and rando <= 6:
            highoutsidefastball()
        elif rando > 6 and rando <= 7.5:
            highinsidefastball()
        elif rando > 7.5 and rando <= 9:
            lowslider()
        else:
            lowchangeup()
    # 0 - 2  OR  1 - 2
    elif (currentballs == 0 and currentstrikes == 2) or (currentballs == 1 and currentstrikes == 2):
        if rando >= 1 and rando <= 2:
            highoutsidefastball()
        elif rando > 2 and rando <= 5:
            highinsidefastball()
        elif rando > 5 and rando <= 9:
            lowslider()
        else:
            lowchangeup()
    return