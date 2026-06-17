#!/usr/bin/env python3
"""
color_sample.py — Point the robot camera at a color sample and read its values.

Usage:
    python3 color_sample.py

Place your printed vinyl under the camera, press ENTER to sample the center
region, and the script reports the Hex code, RGB, and HSV values — plus whether
it falls inside the existing detection thresholds (white, yellow, green, blue).

Press Ctrl+C to quit.
"""

import sys
import time
import numpy as np

SAMPLE_SIZE = 40   # px — square region sampled at frame centre


def open_camera(width=320, height=240):
    try:
        from picamera2 import Picamera2
        cam = Picamera2()
        cfg = cam.create_preview_configuration(
            main={"format": "RGB888", "size": (width, height)})
        cam.configure(cfg)
        cam.start()
        time.sleep(1.0)   # let AGC settle
        print("  Camera: picamera2")
        return ('pi', cam)
    except Exception:
        pass
    import cv2
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    time.sleep(0.5)
    print("  Camera: OpenCV")
    return ('cv', cap)


def grab_frame(cam_tuple):
    import cv2
    kind, cam = cam_tuple
    if kind == 'pi':
        rgb = cam.capture_array()
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    else:
        ret, frame = cam.read()
        return frame if ret else None


def close_camera(cam_tuple):
    kind, cam = cam_tuple
    if kind == 'pi':
        cam.stop()
        cam.close()
    else:
        cam.release()


def classify(h, s, v):
    """Map HSV to a human-readable label using the robot's detection ranges."""
    if v < 50:
        return "BLACK / too dark to detect"
    if s < 50 and v > 150:
        return "WHITE  (matches white threshold)"
    if 20 <= h <= 35 and s > 80 and v > 80:
        return "YELLOW (matches yellow threshold)"
    if 40 <= h <= 80 and s > 80 and v > 80:
        return "GREEN  ✓  will be detected as green"
    if 100 <= h <= 130 and s > 80 and v > 80:
        return "BLUE   ✓  will be detected as blue"
    if s < 80:
        return f"GRAY / low saturation  (H={h} S={s} V={v})"
    return f"OTHER — not in any threshold  (H={h} S={s} V={v})"


def sample(frame):
    import cv2
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    half = SAMPLE_SIZE // 2
    roi = frame[cy - half:cy + half, cx - half:cx + half]
    mean_bgr = roi.mean(axis=(0, 1))
    b, g, r = mean_bgr
    pixel = np.uint8([[[b, g, r]]])
    hsv = cv2.cvtColor(pixel, cv2.COLOR_BGR2HSV)[0][0]
    hue, sat, val = int(hsv[0]), int(hsv[1]), int(hsv[2])
    hex_code = f"#{int(r):02X}{int(g):02X}{int(b):02X}"

    # Save annotated frame for visual check
    out = frame.copy()
    cv2.rectangle(out, (cx - half, cy - half), (cx + half, cy + half), (0, 255, 0), 2)
    cv2.putText(out, hex_code, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.imwrite("/tmp/color_sample.jpg", out)

    return hex_code, int(r), int(g), int(b), hue, sat, val


def main():
    print("\nColor Sampler — hold printed vinyl under the camera centre")
    print("=" * 55)
    cam = open_camera()
    print(f"  Sampling a {SAMPLE_SIZE}×{SAMPLE_SIZE}px region at frame centre")
    print("  Annotated frame saved to /tmp/color_sample.jpg after each sample")
    print("  Press ENTER to sample  |  Ctrl+C to quit\n")

    try:
        while True:
            input("  [ Press ENTER to sample ] ")
            frame = grab_frame(cam)
            if frame is None:
                print("  ERROR: could not read frame — check camera connection\n")
                continue

            hex_code, r, g, b, hue, sat, val = sample(frame)

            print(f"\n  ┌─────────────────────────────────────┐")
            print(f"  │  Hex  : {hex_code:<28}│")
            print(f"  │  RGB  : R={r:<3} G={g:<3} B={b:<3}           │")
            print(f"  │  HSV  : H={hue:<3} S={sat:<3} V={val:<3}           │")
            print(f"  │         (OpenCV H=0–180, S/V=0–255) │")
            print(f"  │  ID   : {classify(hue, sat, val):<28}│")
            print(f"  └─────────────────────────────────────┘")
            print(f"  Frame saved → /tmp/color_sample.jpg\n")

    except KeyboardInterrupt:
        print("\n  Quitting.")
    finally:
        close_camera(cam)


if __name__ == '__main__':
    main()
