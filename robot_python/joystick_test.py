#!/usr/bin/env python3
"""
File: joystick_test.py
Module: V2X Robot Platform — Joystick Diagnostic Tool

Purpose:
    Interactive test utility that prints joystick button and axis index
    numbers live as you press buttons and move sticks. Use this to identify
    the correct axis/button indices for config.yaml on a new controller.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.0

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""
import os, time
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
pygame.init()
pygame.joystick.init()

n = pygame.joystick.get_count()
if n == 0:
    print("No joystick found — is the dongle plugged in?")
    raise SystemExit

js = pygame.joystick.Joystick(0)
js.init()
print(f"Controller: {js.get_name()}")
print(f"  Axes: {js.get_numaxes()}   Buttons: {js.get_numbuttons()}")
print()
print("Press buttons / move sticks. Ctrl-C to quit.")
print("-" * 50)

prev_btns = [0] * js.get_numbuttons()
prev_axes = [0.0] * js.get_numaxes()

while True:
    pygame.event.pump()

    # Buttons — print only on change
    for i in range(js.get_numbuttons()):
        v = js.get_button(i)
        if v != prev_btns[i]:
            state = "PRESSED " if v else "released"
            print(f"  Button {i:2d} : {state}")
            prev_btns[i] = v

    # Axes — print only when value changes meaningfully
    for i in range(js.get_numaxes()):
        v = round(js.get_axis(i), 2)
        if abs(v - prev_axes[i]) > 0.05:
            print(f"  Axis   {i:2d} : {v:+.2f}")
            prev_axes[i] = v

    time.sleep(0.02)
