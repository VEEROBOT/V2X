#!/usr/bin/env python3
"""
Joystick input — reads RF joystick via USB dongle using pygame.

The USB dongle appears as /dev/input/js0 (standard Linux HID joystick).
pygame reads it transparently. SDL_VIDEODRIVER=dummy lets it run headless
on a Pi without a connected display.

Behaviour:
  Hold deadman button  → joystick controls robot (manual mode)
  Release deadman      → returns None → main loop uses autonomous driving

Axis mapping (defaults match a standard gamepad, configure in config.yaml):
  axis_throttle : left stick Y  (inverted — push forward = positive speed)
  axis_steering : right stick X

Button mapping:
  deadman_button : hold to drive  (default 5 = LB / L1)

Usage:
  js = Joystick(...)
  js.start()   # returns False if no joystick found (safe — system runs autonomously)

  cmd = js.get_command()
  if cmd is not None:
      vx, wz = cmd   # manual override
  else:
      # autonomous

Check connected:
  js.connected()  # True if joystick was found and initialised
"""

import logging
import os
import threading
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class Joystick:

    def __init__(self,
                 device_index:   int   = 0,
                 deadman_button: int   = 4,
                 turbo_button:   int   = 5,
                 arm_button:     int   = 7,
                 axis_throttle:  int   = 1,
                 axis_steering:  int   = 3,
                 max_speed:      float = 0.4,
                 turbo_speed:    float = 0.8,
                 max_steering:   float = 1.5,
                 deadzone:       float = 0.10,
                 accel_rate:     float = 2.0,
                 decel_rate:     float = 4.0):

        self._dev_idx      = device_index
        self._deadman_btn  = deadman_button
        self._turbo_btn    = turbo_button
        self._arm_btn      = arm_button
        self._ax_throttle  = axis_throttle
        self._ax_steering  = axis_steering
        self._max_speed    = max_speed
        self._turbo_speed  = turbo_speed
        self._max_steering = max_steering
        self._deadzone     = deadzone
        self._accel_rate   = accel_rate   # m/s² ramp up
        self._decel_rate   = decel_rate   # m/s² ramp down (faster stop)

        self._vx              = 0.0
        self._wz              = 0.0
        self._vx_slewed       = 0.0   # slew-rate-limited output
        self._deadman         = False
        self._arm_btn_prev    = False  # for rising-edge detection
        self._arm_press_flag  = False  # consumed by get_arm_press()
        self._lock            = threading.Lock()
        self._running         = False
        self._js              = None

    # ── Lifecycle ────────────────────────────────────────────────────────
    def start(self) -> bool:
        """Initialise pygame and joystick. Returns True if joystick found."""
        # Must be set before pygame.init() on a headless Pi
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

        try:
            import pygame
            pygame.init()
            pygame.joystick.init()
        except Exception as e:
            logger.error("pygame init failed: %s", e)
            return False

        import pygame
        n = pygame.joystick.get_count()
        if n == 0:
            logger.warning("Joystick: no device found — autonomous-only mode")
            return False

        if self._dev_idx >= n:
            logger.warning("Joystick index %d not available (%d found) — using index 0",
                           self._dev_idx, n)
            self._dev_idx = 0

        try:
            self._js = pygame.joystick.Joystick(self._dev_idx)
            self._js.init()
        except Exception as e:
            logger.error("Joystick init error: %s", e)
            return False

        logger.info("Joystick: '%s'  axes=%d  buttons=%d  deadman=btn%d  turbo=btn%d  arm=btn%d",
                    self._js.get_name(),
                    self._js.get_numaxes(),
                    self._js.get_numbuttons(),
                    self._deadman_btn,
                    self._turbo_btn,
                    self._arm_btn)

        self._running = True
        threading.Thread(target=self._loop, daemon=True, name='joystick').start()
        return True

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

    # ── Background poll loop (50 Hz) ─────────────────────────────────────
    def _loop(self):
        import pygame
        dt = 0.02   # matches time.sleep(0.02) below

        while self._running:
            pygame.event.pump()

            try:
                n_buttons = self._js.get_numbuttons()
                deadman   = bool(self._js.get_button(self._deadman_btn)) \
                            if self._deadman_btn < n_buttons else False
                turbo     = bool(self._js.get_button(self._turbo_btn)) \
                            if self._turbo_btn < n_buttons else False
                arm_now   = bool(self._js.get_button(self._arm_btn)) \
                            if self._arm_btn < n_buttons else False

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
                logger.error("Joystick read error: %s", e)
                deadman, arm_now, vx, wz = False, False, 0.0, 0.0
                self._vx_slewed = 0.0

            if not deadman:
                # Reset slew state so next press starts from zero
                self._vx_slewed = 0.0

            # Rising-edge detection for arm button
            arm_press = arm_now and not self._arm_btn_prev
            self._arm_btn_prev = arm_now

            with self._lock:
                self._deadman = deadman
                self._vx      = vx
                self._wz      = wz
                if arm_press:
                    self._arm_press_flag = True

            time.sleep(0.02)   # 50 Hz
