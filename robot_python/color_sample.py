#!/usr/bin/env python3
"""
color_sample.py — Point the robot camera at a color sample and read its values.

Usage:
    python3 color_sample.py

Place your printed vinyl under the camera, press ENTER to sample the centre
region. Reports Hex, RGB, HSV and whether the color falls inside the robot's
detection thresholds (white, yellow, green, blue).

No cv2 required — uses picamera2 + numpy only.

Press Ctrl+C to quit.
"""

import time
import numpy as np

SAMPLE_SIZE = 40   # px — square region sampled at frame centre
WIDTH, HEIGHT = 320, 240


def rgb_to_hsv_opencv(r, g, b):
    """
    Convert RGB (0-255) to OpenCV-style HSV: H=0-180, S=0-255, V=0-255.
    Pure Python — no cv2 needed.
    """
    r_, g_, b_ = r / 255.0, g / 255.0, b / 255.0
    cmax = max(r_, g_, b_)
    cmin = min(r_, g_, b_)
    diff = cmax - cmin

    # Value
    v = cmax

    # Saturation
    s = 0.0 if cmax == 0 else diff / cmax

    # Hue (degrees 0-360, then halved for OpenCV 0-180)
    if diff == 0:
        h_deg = 0.0
    elif cmax == r_:
        h_deg = 60.0 * (((g_ - b_) / diff) % 6)
    elif cmax == g_:
        h_deg = 60.0 * ((b_ - r_) / diff + 2)
    else:
        h_deg = 60.0 * ((r_ - g_) / diff + 4)

    return int(h_deg / 2), int(s * 255), int(v * 255)


def classify(h, s, v):
    """Map OpenCV HSV to a label using the robot's detection thresholds."""
    if v < 50:
        return "BLACK / too dark to detect"
    if s < 50 and v > 150:
        return "WHITE  — matches white threshold"
    if 20 <= h <= 35 and s > 80 and v > 80:
        return "YELLOW — matches yellow threshold"
    if 40 <= h <= 80 and s > 80 and v > 80:
        return "GREEN  ✓  will be detected as green"
    if 100 <= h <= 130 and s > 80 and v > 80:
        return "BLUE   ✓  will be detected as blue"
    if s < 80:
        return f"GRAY / low saturation  (H={h} S={s} V={v})"
    return f"OTHER — not in any threshold  (H={h} S={s} V={v})"


def save_annotated(frame_rgb, cx, cy, half, hex_code):
    """Try to save an annotated JPEG using Pillow. Silent if unavailable."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.fromarray(frame_rgb)
        draw = ImageDraw.Draw(img)
        draw.rectangle([cx - half, cy - half, cx + half, cy + half],
                       outline=(0, 255, 0), width=2)
        draw.text((6, 4), hex_code, fill=(255, 255, 255))
        img.save("/tmp/color_sample.jpg")
        return True
    except Exception:
        return False


def main():
    print("\nColor Sampler — hold printed vinyl under the camera centre")
    print("=" * 55)

    try:
        from picamera2 import Picamera2
    except ImportError:
        print("ERROR: picamera2 not found.")
        print("Run:  pip3 install picamera2")
        return

    cam = Picamera2()
    cfg = cam.create_preview_configuration(
        main={"format": "RGB888", "size": (WIDTH, HEIGHT)})
    cam.configure(cfg)
    cam.start()
    time.sleep(1.5)   # let AGC/AWB settle
    print("  Camera ready (picamera2)")
    print(f"  Sampling a {SAMPLE_SIZE}×{SAMPLE_SIZE}px region at frame centre ({WIDTH//2},{HEIGHT//2})")
    print("  Press ENTER to sample  |  Ctrl+C to quit\n")

    cx, cy   = WIDTH  // 2, HEIGHT // 2
    half     = SAMPLE_SIZE // 2

    try:
        while True:
            input("  [ Press ENTER to sample ] ")

            frame_rgb = cam.capture_array()   # shape (H, W, 3) RGB uint8
            roi = frame_rgb[cy - half:cy + half, cx - half:cx + half]
            mean = roi.mean(axis=(0, 1))
            r, g, b = int(mean[0]), int(mean[1]), int(mean[2])

            hue, sat, val = rgb_to_hsv_opencv(r, g, b)
            hex_code = f"#{r:02X}{g:02X}{b:02X}"
            label    = classify(hue, sat, val)

            saved = save_annotated(frame_rgb, cx, cy, half, hex_code)
            saved_msg = "  Frame saved → /tmp/color_sample.jpg" if saved else ""

            print(f"\n  ┌─────────────────────────────────────────┐")
            print(f"  │  Hex  : {hex_code:<32}│")
            print(f"  │  RGB  : R={r:<3} G={g:<3} B={b:<3}              │")
            print(f"  │  HSV  : H={hue:<3} S={sat:<3} V={val:<3}              │")
            print(f"  │         (OpenCV H=0–180, S/V=0–255)     │")
            print(f"  │  ID   : {label:<32}│")
            print(f"  └─────────────────────────────────────────┘")
            if saved_msg:
                print(saved_msg)
            print()

    except KeyboardInterrupt:
        print("\n  Quitting.")
    finally:
        cam.stop()
        cam.close()


if __name__ == '__main__':
    main()
