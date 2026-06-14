#!/usr/bin/env python3
"""
File: joystick.py
Module: V2X Robot Platform — Joystick Input Handler

Purpose:
    Reads RF joystick commands via USB dongle using pygame (SDL headless via
    SDL_VIDEODRIVER=dummy). Provides a simple deadman-hold interface: while the
    deadman button is held the robot follows stick input; when released the main
    loop switches to autonomous lane following. Safe to use when no joystick is
    connected — start() returns False and the system runs fully autonomously.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.0

Axis / Button Mapping (configurable in config.yaml):
    axis_throttle  — left stick Y (inverted, push forward = positive vx)
    axis_steering  — right stick X
    deadman_button — hold to drive (default 5 = LB / L1)

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

import logging
import os
import threading
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class Joystick:

    def __init__(self,
                 device_index:       int   = 0,
                 deadman_button:     int   = 4,
                 turbo_button:       int   = 5,
                 arm_button:         int   = 7,
                 amb_arrive_button:  int   = 0,   # A button — simulate ambulance arrive
                 amb_depart_button:  int   = 1,   # B button — simulate ambulance depart
                 train_button:       int   = 2,   # X button — toggle training recording
                 axis_throttle:      int   = 1,
                 axis_steering:      int   = 3,
                 max_speed:          float = 0.4,
                 turbo_speed:        float = 0.8,
                 max_steering:       float = 1.5,
                 deadzone:           float = 0.10,
                 accel_rate:         float = 2.0,
                 decel_rate:         float = 4.0):

        self._dev_idx          = device_index
        self._deadman_btn      = deadman_button
        self._turbo_btn        = turbo_button
        self._arm_btn          = arm_button
        self._amb_arrive_btn   = amb_arrive_button
        self._amb_depart_btn   = amb_depart_button
        self._train_btn        = train_button
        self._ax_throttle      = axis_throttle
        self._ax_steering  = axis_steering
        self._max_speed    = max_speed
        self._turbo_speed  = turbo_speed
        self._max_steering = max_steering
        self._deadzone     = deadzone
        self._accel_rate   = accel_rate   # m/s² ramp up
        self._decel_rate   = decel_rate   # m/s² ramp down (faster stop)

        self._vx                   = 0.0
        self._wz                   = 0.0
        self._vx_slewed            = 0.0
        self._deadman              = False
        self._arm_btn_prev         = False
        self._arm_press_flag       = False
        self._amb_arrive_btn_prev  = False
        self._amb_arrive_flag      = False
        self._amb_depart_btn_prev  = False
        self._amb_depart_flag      = False
        self._train_btn_prev       = False
        self._train_toggle_flag    = False
        self._lock                 = threading.Lock()
        self._running         = False
        self._js              = None

    # ── Lifecycle ────────────────────────────────────────────────────────
    def start(self) -> bool:
        """Initialise pygame and start joystick thread. Returns True if joystick found immediately."""
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

        try:
            import pygame
            pygame.init()
            pygame.joystick.init()
        except Exception as e:
            logger.error("pygame init failed: %s", e)
            return False

        self._running = True
        threading.Thread(target=self._loop, daemon=True, name='joystick').start()

        found = self._try_connect()
        if not found:
            logger.warning("Joystick: no device found — will retry every 5 s")
        return found

    def _try_connect(self) -> bool:
        """Attempt to connect to the USB joystick. Returns True if found."""
        import pygame
        pygame.joystick.quit()
        pygame.joystick.init()
        n = pygame.joystick.get_count()
        if n == 0:
            return False
        idx = self._dev_idx if self._dev_idx < n else 0
        try:
            js = pygame.joystick.Joystick(idx)
            js.init()
            with self._lock:
                self._js = js
            logger.info("Joystick: '%s'  axes=%d  buttons=%d  deadman=btn%d  turbo=btn%d  arm=btn%d",
                        js.get_name(), js.get_numaxes(), js.get_numbuttons(),
                        self._deadman_btn, self._turbo_btn, self._arm_btn)
            return True
        except Exception as e:
            logger.error("Joystick init error: %s", e)
            return False

    def stop(self):
        self._running = False

    def connected(self) -> bool:
        return self._js is not None

    # ── Public API ───────────────────────────────────────────────────────
    def get_command(self) -> Optional[Tuple[float, float]]:
        """
        Returns (vx m/s, wz rad/s) when deadman button is held.
        Returns None when released — caller should use autonomous driving.
        """
        with self._lock:
            if not self._deadman:
                return None
            return self._vx, self._wz

    def is_manual(self) -> bool:
        with self._lock:
            return self._deadman

    def get_arm_press(self) -> bool:
        """Returns True once per press of the arm/disarm button (rising-edge, consume-on-read)."""
        with self._lock:
            if self._arm_press_flag:
                self._arm_press_flag = False
                return True
            return False

    def get_amb_arrive(self) -> bool:
        """Returns True once per press of the A button (ambulance-arrive simulation)."""
        with self._lock:
            if self._amb_arrive_flag:
                self._amb_arrive_flag = False
                return True
            return False

    def get_amb_depart(self) -> bool:
        """Returns True once per press of the B button (ambulance-depart simulation)."""
        with self._lock:
            if self._amb_depart_flag:
                self._amb_depart_flag = False
                return True
            return False

    def get_train_toggle(self) -> bool:
        """Returns True once per press of the X button (toggle training recording)."""
        with self._lock:
            if self._train_toggle_flag:
                self._train_toggle_flag = False
                return True
            return False

    # ── Background poll loop (50 Hz) ─────────────────────────────────────
    def _loop(self):
        import pygame
        dt = 0.02   # matches time.sleep(0.02) below
        _no_js_ticks = 0

        while self._running:
            with self._lock:
                js = self._js

            pygame.event.pump()

            if js is None:
                _no_js_ticks += 1
                if _no_js_ticks % 250 == 0:   # every 5 s at 50 Hz
                    self._try_connect()
                time.sleep(dt)
                continue

            try:
                n_buttons   = self._js.get_numbuttons()
                deadman     = bool(self._js.get_button(self._deadman_btn)) \
                              if self._deadman_btn < n_buttons else False
                turbo       = bool(self._js.get_button(self._turbo_btn)) \
                              if self._turbo_btn < n_buttons else False
                arm_now     = bool(self._js.get_button(self._arm_btn)) \
                              if self._arm_btn < n_buttons else False
                arrive_now  = bool(self._js.get_button(self._amb_arrive_btn)) \
                              if self._amb_arrive_btn < n_buttons else False
                depart_now  = bool(self._js.get_button(self._amb_depart_btn)) \
                              if self._amb_depart_btn < n_buttons else False
                train_now   = bool(self._js.get_button(self._train_btn)) \
                              if self._train_btn < n_buttons else False

                n_axes = self._js.get_numaxes()

                raw_thr = self._js.get_axis(self._ax_throttle) \
                          if self._ax_throttle < n_axes else 0.0
                raw_str = self._js.get_axis(self._ax_steering) \
                          if self._ax_steering < n_axes else 0.0

                # Apply deadzone
                if abs(raw_thr) < self._deadzone:
                    raw_thr = 0.0
                if abs(raw_str) < self._deadzone:
                    raw_str = 0.0

                speed = self._turbo_speed if turbo else self._max_speed
                # Left stick Y: push forward = axis negative → invert for positive vx
                vx_target = -raw_thr * speed
                # Right stick X: push right = axis positive → turn right = negative wz
                wz = -raw_str * self._max_steering

                # Slew rate limit on vx: ramp up slowly, ramp down faster
                diff = vx_target - self._vx_slewed
                if diff > 0:
                    step = min(diff,  self._accel_rate * dt)
                else:
                    step = max(diff, -self._decel_rate * dt)
                self._vx_slewed += step
                vx = self._vx_slewed

            except Exception as e:
                logger.warning("Joystick read error — will reconnect: %s", e)
                with self._lock:
                    self._js = None
                deadman, arm_now, arrive_now, depart_now, train_now, vx, wz = False, False, False, False, False, 0.0, 0.0
                self._vx_slewed = 0.0

            if not deadman:
                # Reset slew state so next press starts from zero
                self._vx_slewed = 0.0

            # Rising-edge detection
            arm_press    = arm_now    and not self._arm_btn_prev
            arrive_press = arrive_now and not self._amb_arrive_btn_prev
            depart_press = depart_now and not self._amb_depart_btn_prev
            train_press  = train_now  and not self._train_btn_prev

            self._arm_btn_prev        = arm_now
            self._amb_arrive_btn_prev = arrive_now
            self._amb_depart_btn_prev = depart_now
            self._train_btn_prev      = train_now

            with self._lock:
                self._deadman = deadman
                self._vx      = vx
                self._wz      = wz
                if arm_press:
                    self._arm_press_flag = True
                if arrive_press:
                    self._amb_arrive_flag = True
                if depart_press:
                    self._amb_depart_flag = True
                if train_press:
                    self._train_toggle_flag = True

            time.sleep(0.02)   # 50 Hz
