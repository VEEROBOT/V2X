# V2X Demo Track Design

> **Space:** 16 × 16 ft (4.88 × 4.88 m) rounded-square loop  
> **AprilTag family:** `DICT_APRILTAG_36H11` (IDs 0 – 17)  
> **Last updated:** 2026-06-08

---

## Overview

A single-lane loop track that both robots follow.  
The car drives on the white centre-line; when an emergency alert arrives it steers left onto the yellow yield zone and holds until the ambulance passes.

```
┌──────────────────────────────────┐
│  ╔════════════════════════════╗  │  Black boundary (foam tile edges)
│  ║  ·  ·  ·  ·  ·  ·  ·  · ·  ║  │  ·  = AprilTag (ID in table below)
│  ║                            ║  │
│  ║  ·                      ·  ║  │  Road surface: BLACK foam tiles
│  ║                            ║  │  Centre line:  WHITE tape (broken)
│  ║  ·                      ·  ║  │  Left shoulder: YELLOW tape (yield)
│  ║                            ║  │
│  ║  ·  ·  ·  ·  ·  ·  ·  · ·  ║  │
│  ╚════════════════════════════╝  │
└──────────────────────────────────┘
```

Direction of travel: **clockwise** (looking from above).

---

## Floor Materials

| Item | Spec | Qty |
|------|------|-----|
| Foam puzzle tiles | 60 cm × 60 cm, black | ~24 tiles (fill 16 × 16 ft) |
| White gaffer / vinyl tape | 25 mm wide | ~20 m |
| Yellow gaffer / vinyl tape | 25 mm wide | ~10 m |
| AprilTag prints | 10 cm × 10 cm on white card | 18 |

---

## Lane Markings

```
← road direction →
┌──────────────────────────────────────┐
│  YELLOW YIELD ZONE  │  ROAD  │ EDGE  │
│  (25 mm tape)       │        │       │
│─────────────────────│        │       │
│                     │ ─ ─ ─  │       │  ← WHITE broken centre line
│─────────────────────│  GAP   │       │     gap = 15 cm for AprilTag
│  YELLOW             │        │       │
└──────────────────────────────────────┘
 ←10cm→ ←5cm gap→ ←tag→ ←5cm gap→
```

- **Centre line**: white tape, broken every ~30 cm with a 15 cm gap
- **AprilTag placement**: centred in a 15 cm gap, flush with the road surface
- **Yellow yield zone**: single strip of yellow tape, 8–10 cm to the left of the centre line; car steers left onto it during evasion

---

## AprilTag Layout

| ID | Position on loop (clockwise from start) |
|----|-----------------------------------------|
| 0  | 0.0 m  — start / finish line           |
| 1  | 1.0 m                                   |
| 2  | 2.0 m                                   |
| 3  | 3.0 m                                   |
| 4  | 4.0 m                                   |
| 5  | 5.0 m                                   |
| 6  | 6.0 m                                   |
| 7  | 7.0 m                                   |
| 8  | 8.0 m                                   |
| 9  | 9.0 m                                   |
| 10 | 10.0 m                                  |
| 11 | 11.0 m                                  |
| 12 | 12.0 m                                  |
| 13 | 13.0 m                                  |
| 14 | 14.0 m                                  |
| 15 | 15.0 m                                  |
| 16 | 16.0 m                                  |
| 17 | 17.0 m                                  |

Total perimeter: **≈ 18 m** (4 straight sides × ~4 m + 4 rounded corners × ~0.5 m each)

---

## AprilTag Print Spec

| Parameter | Value |
|-----------|-------|
| Family | `36h11` |
| Outer tag size | **10 cm × 10 cm** (including black border) |
| Printed on | White card / heavy paper |
| Laminate | Optional — protects from wheel scuffs |
| Orientation | Flat on floor, centred in tape gap |
| ID label | Write tag ID on back for reinstallation |

Generate tags with:
```python
import cv2, numpy as np
aruco = cv2.aruco
params = aruco.DetectorParameters()
dictionary = aruco.getPredefinedDictionary(aruco.DICT_APRILTAG_36H11)
for tag_id in range(18):
    img = aruco.generateImageMarker(dictionary, tag_id, 300)
    cv2.imwrite(f"tag_{tag_id:02d}.png", img)
```
Then print each PNG at 10 cm × 10 cm (verify with a ruler before placing).

---

## Robot Configuration

These values in `config.yaml` must match the physical track:

```yaml
position:
  n_tags: 18          # total tags on track
  tag_spacing_m: 1.0  # distance between consecutive tags (metres)
  tag_size_m: 0.10    # printed tag outer size (metres)
  focal_px: 250.0     # calibrate after setup — see below

emergency_handler:
  n_tags: 18
  yield_zone_gap: 3   # yield only if ambulance is within 3 m behind
```

---

## focal_px Calibration

After the track is built and camera is mounted:

1. Place the robot so a tag is exactly **30 cm** in front of the camera lens.
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
   aruco = cv2.aruco
   d = aruco.getPredefinedDictionary(aruco.DICT_APRILTAG_36H11)
   corners, ids, _ = aruco.detectMarkers(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), d)
   if ids is not None:
       w = np.linalg.norm(corners[0][0][1] - corners[0][0][0])
       focal = w * 0.30 / 0.10
       print(f'focal_px = {focal:.1f}  (set this in config.yaml)')
   cam.stop()
   "
   ```
3. Set `focal_px` in `config.yaml` to the printed value.

---

## Assembly Checklist

- [ ] Lay foam tiles in 4×4 grid (≈ 16 × 16 ft)
- [ ] Mark the loop boundary with chalk or temp tape first
- [ ] Cut/shape corner tiles for rounded corners
- [ ] Lay white centre-line tape (broken every ~45 cm, 15 cm gap)
- [ ] Lay yellow yield-zone tape parallel to centre line, 10 cm to its left
- [ ] Print 18 AprilTags at 10 cm × 10 cm (use tag generation script above)
- [ ] Place tags flat in the 15 cm tape gaps, IDs 0 → 17 clockwise
- [ ] Place robots at tag 0 (start line), both facing clockwise
- [ ] Run `python3 diag_drive.py` to verify UART, then test camera
- [ ] Calibrate `focal_px` (see above)
- [ ] Tune HSV values for white/yellow under actual room lighting  
  (`config.yaml` → `lane_follower: white_v_low`, `yellow_h_low / yellow_h_high`)
