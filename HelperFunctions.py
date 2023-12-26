def simulate(yes, ball_pos, horizontalspeed,
            horizontalacceleration, verticalspeed, verticalacceleration,
            ballsize, traveltime, verticalbreak,
            horizontalbreak, breaktime, pitchername, pitchtype):

    pygame.mouse.set_cursor(pygame.cursors.Cursor(pygame.SYSTEM_CURSOR_CROSSHAIR))
    global currentballs
    global pitchnumber
    global currentstrikes
    global string
    global currentouts
    global currentstrikeouts
    global currentwalks
    global runners
    global runs_scored
    global swing_started
    global hits
    global hit_type
    global first_pitch_thrown
    global pitches_display
    first_pitch_thrown = True
    swing_started = 0

    salepitch.hide()
    strikezonetoggle.hide()
    degrompitch.hide()
    sasakipitch.hide()
    yamamotopitch.hide()
    backtomainmenu.hide()
    banner.hide()
    seepitches.hide()
    toggleumpsound.hide()

    soundplayed = 0
    on_time = 0
    made_contact = 0
    contact_time = 0
    swing_type = 0
    pitch_results_done = False

    starttime = pygame.time.get_ticks()
    current_time = starttime
    while yes:
        time_delta = clock.tick(60)/1000.0
        current_time += (time_delta*1000)
        #Pitcher Windup
        if current_time <= starttime + 1100:
            screen.fill("black")
            if pitchername == 'chrissale':
                if current_time <= starttime + 300:
                    leftyone(a,b)
                elif current_time > starttime + 300 and current_time <= starttime + 500:
                    leftytwo(a,b)
                elif current_time > starttime + 500 and current_time <= starttime + 700:
                    leftythree(a,b)
                elif current_time > starttime + 700 and current_time <= starttime + 900:
                    leftyfour(a,b)
                elif current_time > starttime + 900 and current_time <= starttime + 1000:
                    leftyfive(a,b + 10)
                elif current_time > starttime + 1000 and current_time <= starttime + 1100:
                    leftysix(a + 10,b + 25)
            elif pitchername == 'jacobdegrom':
                if current_time <= starttime + 300:
                    rightyone(c,d)
                elif current_time > starttime + 300 and current_time <= starttime + 500:
                    rightytwo(c,d)
                elif current_time > starttime + 500 and current_time <= starttime + 700:
                    rightythree(c,d)
                elif current_time > starttime + 700 and current_time <= starttime + 900:
                    rightyfour(c,d)
                elif current_time > starttime + 900 and current_time <= starttime + 1000:
                    rightyfive(c,d)
                elif current_time > starttime + 1000 and current_time <= starttime + 1100:
                    rightysix(c,d)
            elif pitchername == 'rokisasaki':
                if current_time <= starttime + 250:
                    roki1(c,d)
                elif current_time > starttime + 250 and current_time <= starttime + 350:
                    roki2(c,d)
                elif current_time > starttime + 350 and current_time <= starttime + 400:
                    roki3(c,d)
                elif current_time > starttime + 400 and current_time <= starttime + 550:
                    roki4(c,d)
                elif current_time > starttime + 550 and current_time <= starttime + 700:
                    roki5(c,d)
                elif current_time > starttime + 700 and current_time <= starttime + 800:
                    roki6(c,d)
                elif current_time > starttime + 800 and current_time <= starttime + 900:
                    roki7(c,d)
                elif current_time > starttime + 900 and current_time <= starttime + 975:
                    roki8(c,d)
                elif current_time > starttime + 975 and current_time <= starttime + 1000:
                    roki9(c,d)
                elif current_time > starttime + 1000 and current_time <= starttime + 1050:
                    roki10(c,d)
                elif current_time > starttime + 1050 and current_time <= starttime + 1100:
                    roki11(c,d)
            elif pitchername == 'Yamamoto':
                if current_time <= starttime + 250:
                    yamamoto1(c,d)
                elif current_time > starttime + 250 and current_time <= starttime + 350:
                    yamamoto2(c,d)
                elif current_time > starttime + 350 and current_time <= starttime + 400:
                    yamamoto3(c,d)
                elif current_time > starttime + 400 and current_time <= starttime + 550:
                    yamamoto4(c,d)
                elif current_time > starttime + 550 and current_time <= starttime + 700:
                    yamamoto5(c,d)
                elif current_time > starttime + 700 and current_time <= starttime + 800:
                    yamamoto6(c,d)
                elif current_time > starttime + 800 and current_time <= starttime + 900:
                    yamamoto7(c,d)
                elif current_time > starttime + 900 and current_time <= starttime + 975:
                    yamamoto8(c,d)
                elif current_time > starttime + 975 and current_time <= starttime + 1000:
                    yamamoto9(c,d)
                elif current_time > starttime + 1000 and current_time <= starttime + 1050:
                    yamamoto10(c,d)
                elif current_time > starttime + 1050 and current_time <= starttime + 1100:
                    yamamoto11(c,d)
            leg_kick(current_time, starttime + 700)
            draw_static()
            manager.update(time_delta)
            manager.draw_ui(screen)
            pygame.display.flip()

        #From time ball leaves the hand until ball finishes traveling
        if (current_time > starttime + 1100 and current_time < starttime + traveltime + 1150 and (on_time == 0 or (on_time > 0 and made_contact == 1))) or (on_time > 0 and current_time <= contact_time and made_contact == 0):
            screen.fill("black")
            if current_time > starttime + 1100 and current_time <= starttime + 1150:
                if pitchername == 'chrissale':
                    leftyseven(a + 8,b + 22)
                elif pitchername == 'jacobdegrom':
                    rightyseven(c,d)
                elif pitchername == 'rokisasaki':
                    roki12(c,d)
                elif pitchername == 'Yamamoto':
                    yamamoto12(c,d)
                pygame.draw.circle(screen, "white", ball_pos, ballsize)
                ball_pos.y += verticalspeed
                ball_pos.x += horizontalspeed
                horizontalspeed += horizontalacceleration
                verticalspeed += verticalacceleration
                ballsize = ballsize * 1.030
            #Ball continuing to travel because swing was too off timing
            elif current_time > starttime + 1150 and current_time <= starttime + breaktime + 1150 and on_time == 0:
                if current_time > starttime + 1150 and current_time <= starttime + 1200:
                    if pitchername == 'chrissale':
                        leftyeight(a - 11,b + 22)
                    elif pitchername == 'jacobdegrom':
                        rightyeight(c, d)
                    elif pitchername == 'rokisasaki':
                        roki13(c,d)
                    elif pitchername == 'Yamamoto':
                        yamamoto13(c,d)
                else:
                    if pitchername == 'chrissale':
                        leftynine(a + 16, b + 22)
                    elif pitchername == 'jacobdegrom':
                        rightynine(c, d)
                    elif pitchername == 'rokisasaki':
                        roki14(c,d)
                    elif pitchername == 'Yamamoto':
                        yamamoto14(c,d)
                pygame.draw.circle(screen, "white", ball_pos, ballsize)
                ball_pos.y += verticalspeed
                ball_pos.x += horizontalspeed
                horizontalspeed += horizontalacceleration
                verticalspeed += verticalacceleration
                ballsize = ballsize * 1.030
            elif (current_time > starttime + breaktime + 1150 and current_time <= starttime + traveltime + 1150 and (on_time == 0 or (on_time > 0 and made_contact == 1))) or (on_time > 0 and current_time <= contact_time and made_contact == 0):
                if pitchername == 'chrissale':
                    leftynine(a + 16, b + 22)
                elif pitchername == 'jacobdegrom':
                    rightynine(c, d)
                elif pitchername == 'rokisasaki':
                    roki14(c,d)
                elif pitchername == 'Yamamoto':
                    yamamoto14(c,d)
                pygame.draw.circle(screen, "white", ball_pos, ballsize)
                ball_pos.y += verticalspeed
                ball_pos.x += horizontalspeed
                horizontalspeed += horizontalbreak
                verticalspeed += verticalbreak
                ballsize = ballsize * 1.030
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN:
                    #CONTACT SWING
                    if event.key == pygame.K_w and swing_started == 0:
                        swing_type = 1
                        mousepos = pygame.mouse.get_pos()
                        #LOW SWING
                        if mousepos[1] > 500:
                            swing_starttime = pygame.time.get_ticks()
                            swing_started = 1
                            contact_time = swing_starttime + 150
                            on_time = contacttiming(swing_starttime,starttime,traveltime)
                        #HIGH SWING
                        elif mousepos[1] < 500:
                            swing_starttime = pygame.time.get_ticks()
                            swing_started = 2
                            contact_time = swing_starttime + 150
                            on_time = contacttiming(swing_starttime,starttime,traveltime)
                    #POWER SWING
                    elif event.key == pygame.K_e and swing_started == 0:
                        swing_type = 2
                        mousepos = pygame.mouse.get_pos()
                        #LOW SWING
                        if mousepos[1] > 500:
                            swing_starttime = pygame.time.get_ticks()
                            swing_started = 1
                            contact_time = swing_starttime + 150
                            on_time = powertiming(swing_starttime,starttime,traveltime)
                        #HIGH SWING
                        elif mousepos[1] < 500:
                            swing_starttime = pygame.time.get_ticks()
                            swing_started = 2
                            contact_time = swing_starttime + 150
                            on_time = powertiming(swing_starttime,starttime,traveltime)

            if swing_started > 0:
                timenow = current_time
                if swing_started == 1:
                    swing_start(timenow, swing_starttime)
                else:
                    high_swing_start(timenow, swing_starttime)
            elif swing_started == 0:
                leg_kick(current_time, starttime + 700)
            draw_static()
            manager.update(time_delta)
            manager.draw_ui(screen)
            pygame.display.flip()

            if (current_time > (starttime + traveltime + 1050) and soundplayed == 0 and on_time == 0) or (current_time > contact_time and soundplayed == 0 and (on_time > 0 and made_contact == 1)):
                glovepop()
                soundplayed += 1

        #FOUL BALL TIMING
        elif on_time == 1 and current_time > contact_time and current_time <= starttime + traveltime + 1800 and pitch_results_done == False and made_contact == 0:
            if pitchername == 'chrissale':
                leftynine(a + 16, b + 22)
            elif pitchername == 'jacobdegrom':
                rightynine(c, d)
            elif pitchername == 'rokisasaki':
                roki14(c, d)
            elif pitchername == 'Yamamoto':
                yamamoto14(c,d)
            if swing_started > 0:
                timenow = current_time
                if swing_started == 1:
                    swing_start(timenow, swing_starttime)
                else:
                    high_swing_start(timenow, swing_starttime)
            elif swing_started == 0:
                leg_kick(current_time, starttime + 700)
            #TIMING ON BUT SWING PATH OFF (SWING OVER OR UNDER BALL)
            if (ball_pos.x < 554 or ball_pos.x > 706) or (ball_pos.y < 385 or ball_pos.y > 480) and swing_started == 2:
                made_contact = 1
            elif (ball_pos.x < 554 or ball_pos.x > 706) or (ball_pos.y < 470 or ball_pos.y > 576) and swing_started == 1:
                made_contact = 1
            #TIMING ON AND PATH ON - FOUL BALL
            else:
                made_contact = 2
                pitch_results_done = True
                pitchnumber += 1
                if currentstrikes == 2:
                    container.clear()
                    string = "<font size=5>PITCH {}: {}<br>FOUL<br>COUNT IS {} - {}</font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    textbox = pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                    scoreboard = drawscoreboard(result)
                    containerupdate(textbox,scoreboard)
                else:
                    currentstrikes += 1
                    container.clear()
                    string = "<font size=5>PITCH {}: {}<br>FOUL<br>COUNT IS {} - {}</font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    textbox = pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                    scoreboard = drawscoreboard(result)
                    containerupdate(textbox,scoreboard)

        #PERFECT TIMING
        elif on_time == 2 and current_time > contact_time and current_time <= starttime + traveltime + 1800 and pitch_results_done == False and made_contact == 0:
            if pitchername == 'chrissale':
                leftynine(a + 16, b + 22)
            elif pitchername == 'jacobdegrom':
                rightynine(c, d)
            elif pitchername == 'rokisasaki':
                roki14(c, d)
            elif pitchername == 'Yamamoto':
                yamamoto14(c,d)
            if swing_started > 0:
                timenow = current_time
                if swing_started == 1:
                    swing_start(timenow, swing_starttime)
                else:
                    high_swing_start(timenow, swing_starttime)
            elif swing_started == 0:
                leg_kick(current_time, starttime + 700)
            #PERFECT TIMING BUT SWING PATH OFF
            if (ball_pos.x < 554 or ball_pos.x > 706) or (ball_pos.y < 385 or ball_pos.y > 480) and swing_started == 2:
                made_contact = 1
            elif (ball_pos.x < 554 or ball_pos.x > 706) or (ball_pos.y < 470 or ball_pos.y > 576) and swing_started == 1:
                made_contact = 1
            #PERFECT TIMING AND SWING PATH ON - SUCCESSFUL HIT
            else:
                container.clear()
                made_contact = 2
                pitch_results_done = True
                pitchnumber += 1
                if swing_type == 1:
                    hit_string = contact_hit_outcome()
                elif swing_type == 2:
                    hit_string = power_hit_outcome()
                if ishomerun != '':
                    banner.set_text("{}".format(ishomerun))
                else:
                    banner.set_text("{}".format(hit_string))
                banner.show()
                banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR,{'time_per_letter': 0.1})
                string = "<font size=5>PITCH {}: {}<br>HIT - {}<br>COUNT IS {} - {}</font>".format(pitchnumber, pitchtype, hit_string, currentballs, currentstrikes)
                textbox = pitchresult(string)
                hits += 1
                textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                scoreboard = drawscoreboard(result)
                scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
                containerupdate(textbox, scoreboard)
                pitchnumber = 0
                currentstrikes = 0
                currentballs = 0

        #Follow through - play rest of the swing animation
        elif on_time > 0 and current_time > contact_time and current_time <= starttime + traveltime + 1800 and pitch_results_done == True and made_contact == 2:
            screen.fill("black")
            if pitchername == 'chrissale':
                leftynine(a + 16, b + 22)
            elif pitchername == 'jacobdegrom':
                rightynine(c, d)
            elif pitchername == 'rokisasaki':
                roki14(c, d)
            elif pitchername == 'Yamamoto':
                yamamoto14(c,d)
            if swing_started > 0:
                timenow = current_time
                if swing_started == 1:
                    swing_start(timenow, swing_starttime)
                else:
                    high_swing_start(timenow, swing_starttime)
            pygame.draw.circle(screen, "white", ball_pos, fourseamballsize, 2)
            draw_static()
            manager.update(time_delta)
            manager.draw_ui(screen)
            pygame.display.flip()
            #Play sounds
            if soundplayed == 0 and on_time == 1:
                foulball.play()
                soundplayed += 1
            elif soundplayed == 0 and on_time == 2:
                if hit_type == 1:
                    single.play()
                elif hit_type == 2:
                    double.play()
                elif hit_type == 3:
                    triple.play()
                elif hit_type == 4:
                    homer.play()
                soundplayed += 1

        #UPDATE RESULTS IF NO CONTACT MADE AT ALL - SWINGING STRIKE OR CALLED STRIKE OR BALL
        elif (current_time > starttime + traveltime + 1150 and pitch_results_done == False and (on_time == 0 or (on_time > 0 and made_contact == 1))):
            if pitchername == 'chrissale':
                leftynine(a + 16, b + 22)
            elif pitchername == 'jacobdegrom':
                rightynine(c, d)
            elif pitchername == 'rokisasaki':
                roki14(c, d)
            elif pitchername == 'Yamamoto':
                yamamoto14(c,d)
            if swing_started > 0:
                timenow = current_time
                if swing_started == 1:
                    swing_start(timenow, swing_starttime)
                else:
                    high_swing_start(timenow, swing_starttime)
            elif swing_started == 0:
                leg_kick(current_time, starttime + 700)
            pitch_results_done = True
            #BALL OUTSIDE THE ZONE AND NOT SWUNG AT - BALL
            if (not collision(ball_pos.x, ball_pos.y, 11, 630, 482.5, 130, 165)) and swing_started == 0:
                if umpsound:
                    ballcall.play()
                currentballs += 1
                pitchnumber += 1
                #WALK OCCURS
                if currentballs == 4:
                    container.clear()
                    string = "<font size=5>PITCH {}: {}<br>BALL<br>COUNT IS {} - {}<br><b>WALK</b></font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    textbox = pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                    currentwalks += 1
                    pitchnumber = 0
                    currentstrikes = 0
                    currentballs = 0
                    if runners == 0.000:
                        runners = 0.100
                    elif runners == 0.100 or runners == 0.010:
                        runners = 0.110
                    elif runners == 0.001:
                        runners = 0.101
                    elif runners == 0.110 or runners == 0.011 or runners == 0.101:
                        runners = 0.111
                    elif runners == 0.111:
                        runs_scored += 1
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                    scoreboard = drawscoreboard(result)
                    scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
                    containerupdate(textbox,scoreboard)
                    banner.set_text("WALK")
                    banner.show()
                    banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR,{'time_per_letter': 0.1})
                else:
                    #Normal Ball
                    container.clear()
                    string = "<font size=5>PITCH {}: {}<br>BALL<br>COUNT IS {} - {}</font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    textbox = pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                    scoreboard = drawscoreboard(result)
                    containerupdate(textbox,scoreboard)
            #STRIKE (CALLED OR SWINGING STRIKE)
            else:
                pitchnumber += 1
                currentstrikes += 1
                if swing_started == 0 and currentstrikes == 3 and umpsound:
                    called_strike_3.play()
                elif swing_started == 0 and currentstrikes != 3 and umpsound:
                    strikecall.play()
                #STRIKEOUT OCCURS
                if currentstrikes == 3:
                    container.clear()
                    if swing_started == 0:
                        string = "<font size=5>PITCH {}: {}<br>CALLED STRIKE<br>COUNT IS {} - {}<br><b>STRIKEOUT</b></font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    else:
                        string = "<font size=5>PITCH {}: {}<br>SWINGING STRIKE<br>COUNT IS {} - {}<br><b>STRIKEOUT</b></font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    textbox = pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                    currentstrikeouts += 1
                    currentouts +=1
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                    scoreboard = drawscoreboard(result)
                    scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0075})
                    banner.set_text("STRIKEOUT")
                    banner.show()
                    banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR,{'time_per_letter': 0.1})
                    containerupdate(textbox,scoreboard)
                    pitchnumber = 0
                    currentstrikes = 0
                    currentballs = 0
                else:
                    #Normal Strike
                    container.clear()
                    if swing_started == 0:
                        string = "<font size=5>PITCH {}: {}<br>CALLED STRIKE<br>COUNT IS {} - {}<br></font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    else:
                        string = "<font size=5>PITCH {}: {}<br>SWINGING STRIKE<br>COUNT IS {} - {}<br></font>".format(pitchnumber, pitchtype, currentballs, currentstrikes)
                    textbox = pitchresult(string)
                    textbox.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': 0.0085})
                    result = "<font size=5>CURRENT OUTS : {}<br>STRIKEOUTS : {}<br>WALKS : {}<br>HITS : {}<br>RUNS SCORED: {}</font>".format(currentouts, currentstrikeouts, currentwalks, hits, runs_scored)
                    scoreboard = drawscoreboard(result)
                    containerupdate(textbox,scoreboard)

        #FOLLOW THROUGH IF SWUNG AND MISSED and ball has already reached the plate (For late swings)
        elif current_time > starttime + traveltime + 1150 and pitch_results_done == True and current_time <= starttime + traveltime + 1800 and (on_time == 0 or (on_time > 0 and made_contact == 1)):
            screen.fill("black")
            if pitchername == 'chrissale':
                leftynine(a + 16, b + 22)
            elif pitchername == 'jacobdegrom':
                rightynine(c, d)
            elif pitchername == 'rokisasaki':
                roki14(c, d)
            elif pitchername == 'Yamamoto':
                yamamoto14(c,d)
            if (current_time > contact_time and soundplayed == 0 and (on_time > 0 and made_contact == 1)):
                glovepop()
                soundplayed += 1
            if swing_started > 0:
                timenow = current_time
                if swing_started == 1:
                    swing_start(timenow, swing_starttime)
                else:
                    high_swing_start(timenow, swing_starttime)
            elif swing_started == 0:
                leg_kick(current_time, starttime + 700)
            pygame.draw.circle(screen, "white", ball_pos, fourseamballsize, 2)
            draw_static()
            manager.update(time_delta)
            manager.draw_ui(screen)
            pygame.display.flip()

        #END LOOP (END OF PITCH)
        elif current_time > starttime + traveltime + 1800:
            yes = False
            salepitch.show()
            strikezonetoggle.show()
            backtomainmenu.show()
            sasakipitch.show()
            yamamotopitch.show()
            degrompitch.show()
            toggleumpsound.show()
            seepitches.show()

    pitches_display.append(ball_pos)
    pygame.mouse.set_cursor(pygame.cursors.Cursor(pygame.SYSTEM_CURSOR_ARROW))
    return