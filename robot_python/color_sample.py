#!/usr/bin/env python3
"""
color_sample.py — Sample the robot camera and check against detection thresholds.

Hold a coloured line under the camera centre. Readings update every 0.5 s.
Reads thresholds live from config.yaml so results match exactly what the robot detects.

Usage:
    python3 color_sample.py          # continuous (Ctrl-C to quit)
    python3 color_sample.py --once   # single sample then exit

On the OBU: stop the robot service first so the camera is free:
    sudo systemctl stop v2x_car      # or v2x_emgy on the ambulance OBU
"""

import os
import sys
import time
import numpy as np

SAMPLE_W  = 80     # sample region width  (px) — wide enough to catch the line
SAMPLE_H  = 60     # sample region height (px) — taller than 25mm lines
WIDTH     = 320
HEIGHT    = 240
INTERVAL  = 0.5    # seconds between auto-samples
DETECT_PCT = 5.0   # % of sample pixels that must match to call it "detected"


# ── Load thresholds ──────────────────────────────────────────────────────────

def load_thresholds():
    """Load HSV thresholds from config.yaml next to this script. Falls back to defaults."""
    defaults = {
        'white':  ((  0,   0, 150), (180,  70, 255)),
        'yellow': (( 20,  80,  80), ( 35, 255, 255)),
        'green':  (( 40,  80,  80), ( 80, 255, 255)),
        'blue':   ((  0, 100, 100), ( 20, 255, 255)),
    }
    try:
        import yaml
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
        with open(path) as f:
            cfg = yaml.safe_load(f)
        lf = cfg.get('lane_follower', {})
        loaded = {
            'white':  ((lf.get('white_h_low',    0), lf.get('white_s_low',   0), lf.get('white_v_low',  150)),
                       (lf.get('white_h_high', 180), lf.get('white_s_high',  70), lf.get('white_v_high', 255))),
            'yellow': ((lf.get('yellow_h_low',  20), lf.get('yellow_s_low',  80), lf.get('yellow_v_low',  80)),
                       (lf.get('yellow_h_high', 35), lf.get('yellow_s_high',255), lf.get('yellow_v_high',255))),
            'green':  ((lf.get('green_h_low',   40), lf.get('green_s_low',   80), lf.get('green_v_low',   80)),
                       (lf.get('green_h_high',  80), lf.get('green_s_high', 255), lf.get('green_v_high', 255))),
            'blue':   ((lf.get('blue_h_low',     0), lf.get('blue_s_low',  100), lf.get('blue_v_low',   100)),
                       (lf.get('blue_h_high',   20), lf.get('blue_s_high', 255), lf.get('blue_v_high',  255))),
        }
        print("  Thresholds: config.yaml")
        return loaded
    except Exception as e:
        print(f"  Thresholds: defaults (config.yaml not loaded: {e})")
        return defaults


# ── Camera ───────────────────────────────────────────────────────────────────

def start_camera():
    """Try picamera2, then fall back to OpenCV USB webcam."""
    try:
        from picamera2 import Picamera2
        cam = Picamera2()
        config = cam.create_preview_configuration(
            main={"format": "RGB888", "size": (WIDTH, HEIGHT)})
        cam.configure(config)
        cam.start()
        time.sleep(2.0)   # let AGC / AWB settle
        print("  Camera: picamera2")
        return cam, 'pi'
    except Exception as e:
        print(f"  picamera2 failed ({e}), trying OpenCV...")
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        if not cap.isOpened():
            raise RuntimeError("VideoCapture(0) could not open")
        time.sleep(0.5)
        print("  Camera: OpenCV/USB")
        return cap, 'cv'
    except Exception as e:
        raise RuntimeError(f"No camera available: {e}")


def grab_rgb(cam, mode):
    if mode == 'pi':
        arr = cam.capture_array()
        return arr[:, :, :3]   # drop alpha if present (RGBA→RGB)
    else:
        import cv2
        ok, frame = cam.read()
        if not ok:
            raise RuntimeError("Camera read failed")
        return frame[:, :, ::-1]   # BGR→RGB


def stop_camera(cam, mode):
    try:
        if mode == 'pi':
            cam.stop()
        else:
            cam.release()
    except Exception:
        pass


# ── Colour analysis ──────────────────────────────────────────────────────────

def rgb_to_hsv_cv(r, g, b):
    """RGB (0–255) → OpenCV HSV (H 0–180, S/V 0–255). Pure Python, no cv2."""
    r_, g_, b_ = r / 255.0, g / 255.0, b / 255.0
    cmax = max(r_, g_, b_)
    cmin = min(r_, g_, b_)
    diff = cmax - cmin
    v = cmax
    s = 0.0 if cmax == 0 else diff / cmax
    if diff == 0:
        h = 0.0
    elif cmax == r_:
        h = 60.0 * (((g_ - b_) / diff) % 6)
    elif cmax == g_:
        h = 60.0 * ((b_ - r_) / diff + 2)
    else:
        h = 60.0 * ((r_ - g_) / diff + 4)
    return int(h / 2), int(s * 255), int(v * 255)


def analyse_region(frame_rgb, cx, cy, sw, sh, thresholds):
    """
    Sample a region and return:
      mean_hsv  — (H, S, V) of the mean RGB
      mean_rgb  — (R, G, B) mean
      pcts      — {name: float} percentage of pixels matching each threshold
    """
    y0 = max(0, cy - sh // 2);  y1 = min(frame_rgb.shape[0], cy + sh // 2)
    x0 = max(0, cx - sw // 2);  x1 = min(frame_rgb.shape[1], cx + sw // 2)
    roi = frame_rgb[y0:y1, x0:x1]

    mean_rgb = tuple(int(x) for x in roi.mean(axis=(0, 1)))
    mean_hsv = rgb_to_hsv_cv(*mean_rgb)

    try:
        import cv2
        hsv_roi = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
        total   = hsv_roi.shape[0] * hsv_roi.shape[1]
        pcts = {}
        for name, (lo, hi) in thresholds.items():
            mask = cv2.inRange(hsv_roi,
                               np.array(lo, dtype=np.uint8),
                               np.array(hi, dtype=np.uint8))
            pcts[name] = 100.0 * int(mask.sum()) / 255 / max(total, 1)
    except ImportError:
        pcts = {name: 0.0 for name in thresholds}

    return mean_hsv, mean_rgb, pcts


# ── Display ──────────────────────────────────────────────────────────────────

BAR_W = 24

def bar(pct):
    filled = int(round(pct / 100.0 * BAR_W))
    filled = max(0, min(BAR_W, filled))
    return '█' * filled + '░' * (BAR_W - filled)


def print_sample(n, mean_hsv, mean_rgb, pcts):
    h, s, v   = mean_hsv
    r, g, b   = mean_rgb
    hex_code  = f"#{r:02X}{g:02X}{b:02X}"
    detections = [name.upper() for name, pct in pcts.items() if pct >= DETECT_PCT]
    det_str    = '  ◀  ' + ' + '.join(detections) if detections else '  (no match)'

    print(f"\n  [{n:4d}]  {hex_code}   H={h:3d}  S={s:3d}  V={v:3d}{det_str}")
    for name, pct in pcts.items():
        flag = ' ◀' if pct >= DETECT_PCT else ''
        print(f"         {name:<8s}  {bar(pct)}  {pct:5.1f}%{flag}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    once = '--once' in sys.argv

    print()
    print("V2X Color Sampler")
    print("=" * 52)

    thresholds = load_thresholds()
    print()
    for name, (lo, hi) in thresholds.items():
        print(f"    {name:<8s}  H {lo[0]:3d}–{hi[0]:3d}  S {lo[1]:3d}–{hi[1]:3d}  V {lo[2]:3d}–{hi[2]:3d}")
    print()

    try:
        cam, mode = start_camera()
    except RuntimeError as e:
        print(f"\n  ERROR: {e}")
        sys.exit(1)

    cx, cy = WIDTH // 2, HEIGHT // 2
    print(f"\n  Sampling {SAMPLE_W}×{SAMPLE_H}px at centre ({cx},{cy})")
    if once:
        print("  --once mode\n")
    else:
        print(f"  Auto-sampling every {INTERVAL}s  |  Ctrl-C to quit\n")

    try:
        n = 0
        while True:
            frame             = grab_rgb(cam, mode)
            mean_hsv, rgb, pcts = analyse_region(
                frame, cx, cy, SAMPLE_W, SAMPLE_H, thresholds)
            n += 1
            print_sample(n, mean_hsv, rgb, pcts)
            if once:
                break
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\n  Done.")
    finally:
        stop_camera(cam, mode)


if __name__ == '__main__':
    main()
