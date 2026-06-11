# V2X Demo Track Design

> **Space:** 10 × 12 ft (3048 × 3657 mm) oval loop  
> **AprilTag family:** `DICT_APRILTAG_36H11`  
> **Tags:** 10 inner (primary) + 8 outer (recovery) = 18 total  
> **Last updated:** 2026-06-11

---

## Overview

An oval loop track. Both robots follow the **white oval boundary line**.  
When an emergency alert arrives the car steers left onto the **yellow yield zone** (inner island) and holds until the ambulance passes.

```
┌──────────────────────────────────────────┐
│  outer yellow boundary                   │
│  ┌──────────────────────────────────┐    │
│  │  white oval (robots follow this) │    │
│  │  ┌────────────────────────┐      │    │
│  │  │  yellow inner island   │      │    │
│  │  │  (yield zone / inner   │      │    │
│  │  │   AprilTag wall)       │      │    │
│  │  └────────────────────────┘      │    │
│  └──────────────────────────────────┘    │
└──────────────────────────────────────────┘
```

Direction of travel: **clockwise** (viewed from above).

---

## Floor Materials

| Item | Spec | Qty |
|------|------|-----|
| White tape (oval boundary) | 25 mm wide | ~8 m |
| Yellow tape (inner island) | 25 mm wide | ~6 m |
| Yellow tape (outer boundary) | 25 mm wide | ~10 m |
| AprilTag prints (inner) | 10 cm × 10 cm on white card | 10 |
| AprilTag prints (outer) | 10 cm × 10 cm on white card | 8 |

---

## Lane Markings

```
← road direction (clockwise) →

  [outer yellow boundary]
        |
  ~510 mm road width
        |
  [white oval line]  ← robots follow this
        |
  ~510 mm inner track width  ← yield / evasion zone
        |
  [yellow inner island]  ← car moves left onto this during emergency
```

- **White oval**: main lane boundary — broken dashes, 25 mm wide
- **Yellow inner island**: left side boundary — continuous strip; car steers onto it during evasion
- **Yellow outer boundary**: right/outer edge — continuous strip; marks arena limit
- **Track width**: ~510 mm (white oval to yellow inner island, each side)

---

## AprilTag Layout

### Inner Tags — primary zone tracking (IDs 0–9)

Mounted on the wall/edge of the **inner yellow island**, facing outward so the robot sees them while driving the oval.

| ID | Position (clockwise from start) | Notes |
|----|----------------------------------|-------|
| 0  | 0.00 m — start / finish         | |
| 1  | 0.67 m                           | |
| 2  | 1.34 m                           | |
| 3  | 2.01 m                           | |
| 4  | 2.68 m                           | |
| 5  | 3.35 m                           | |
| 6  | 4.02 m                           | |
| 7  | 4.69 m                           | |
| 8  | 5.36 m                           | |
| 9  | 6.03 m                           | |

Inner oval perimeter: **≈ 6.7 m** — 10 tags at ~0.67 m spacing.

### Outer Tags — recovery reference only (IDs 10–17)

Mounted on the **outer yellow boundary wall**, facing inward. Detected only when the robot drifts outside the inner oval. Triggers `off_track` warning; does not update zone.

| ID | Position (clockwise from start) | Notes |
|----|----------------------------------|-------|
| 10 | 0.0 m   | |
| 11 | 1.24 m  | |
| 12 | 2.49 m  | |
| 13 | 3.73 m  | |
| 14 | 4.97 m  | |
| 15 | 6.22 m  | |
| 16 | 7.46 m  | |
| 17 | 8.71 m  | |

Outer boundary perimeter: **≈ 9.9 m** — 8 tags at ~1.24 m spacing.

---

## AprilTag Print Spec

| Parameter | Value |
|-----------|-------|
| Family | `36h11` |
| Outer tag size | **10 cm × 10 cm** (including black border) |
| Printed on | White card / heavy paper |
| Laminate | Optional — protects from scuffs |
| Orientation | Vertical on wall, facing track centre |
| Height from ground | Match camera height (~350 mm) |
| ID label | Write tag ID on back for reinstallation |

Generate tags:
```python
import cv2
dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36H11)
for tag_id in range(18):
    img = cv2.aruco.generateImageMarker(dictionary, tag_id, 300)
    cv2.imwrite(f"tag_{tag_id:02d}.png", img)
```
Print each PNG at exactly **10 cm × 10 cm** (verify with a ruler).

---

## Robot Configuration

These values in `config.yaml` match the physical track:

```yaml
position:
  n_inner_tags: 10        # IDs 0-9 on inner oval wall — primary zone tracking
  n_outer_tags: 8         # IDs 10-17 on outer boundary — drift/recovery reference
  tag_spacing_m: 0.70     # 3D slant distance: sqrt(0.35m_height² + 0.61m_ground²)
  tag_size_m: 0.10        # 10 cm printed tag (outer border included)
  focal_px: 264.0         # ArduCam 8MP IMX219 at 320px — verify with calibration

emergency_handler:
  n_tags: 10
  yield_zone_gap: 3       # yield only if ambulance ≤ 3 zones (~2 m) behind
```

---

## focal_px Calibration

After mounting the camera at the correct height and angle:

1. Place the robot so an inner tag is exactly **30 cm** in front of the camera lens.
2. Run:
   ```bash
   cd ~/projects/V2X/robot_python && source .venv/bin/activate
   python3 -c "
   import cv2, numpy as np
   from camera import Camera
   cam = Camera(0, 320, 240, use_picamera2=True)
   cam.start()
   import time; time.sleep(2)
   frame = cam.get_frame()
   d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36H11)
   corners, ids, _ = cv2.aruco.detectMarkers(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), d)
   if ids is not None:
       w = np.linalg.norm(corners[0][0][1] - corners[0][0][0])
       focal = w * 0.30 / 0.10
       print(f'focal_px = {focal:.1f}  (set this in config.yaml)')
   cam.stop()
   "
   ```
3. Set `focal_px` in `config.yaml` to the printed value.

---

## Camera Setup

| Parameter | Value |
|-----------|-------|
| Camera | ArduCam 8MP IMX219 (same optics as Pi Camera v2) |
| Height from ground | ~350 mm |
| Tilt | ~30° downward |
| Resolution | 320 × 240 px (processing) |
| Horizontal FOV | ~62° |
| Visible ahead (crop 0.30) | 250 mm – 950 mm |
| Track width in FOV at 850 mm | ~1020 mm — covers full 1019 mm track |

---

## Assembly Checklist

- [ ] Lay out oval track boundary (white tape, ~6.7 m inner oval perimeter)
- [ ] Lay yellow inner island tape (inner boundary of driving lane)
- [ ] Lay yellow outer boundary tape (outer limit of arena)
- [ ] Print 18 AprilTags at 10 cm × 10 cm
- [ ] Mount inner tags 0–9 on inner island wall, evenly spaced, ~350 mm height
- [ ] Mount outer tags 10–17 on outer boundary wall, evenly spaced, ~350 mm height
- [ ] Mount camera on robot at ~350 mm height, ~30° downward tilt
- [ ] Stop v2x_car service: `sudo systemctl stop v2x_car`
- [ ] Run `python3 main_car.py` and open http://robot-ip:5005/
- [ ] Verify tags detected: hold each tag in front of camera, confirm green box + ID in stream
- [ ] Calibrate `focal_px` (see above)
- [ ] Tune HSV values for white/yellow under actual room lighting
- [ ] Place robots at tag 0 (start line), facing clockwise
- [ ] Press Start (btn7) to arm car; ambulance arms automatically
