# CAVIA Vision Pipeline

This directory contains the current work-in-progress implementation of Context-Aware Visual Intent Arbitration for MyoGrip CAVIA.

## Current capabilities

- Receives the XIAO ESP32-S3 camera MJPEG stream
- Detects supported objects using YOLO
- Uses a fixed centre reticle for object and region targeting
- Applies predefined class-specific functional-region rules
- Uses temporal tracking to produce SEARCHING, LOCKED and LOST states
- Emits structured object-region results for later CAVIA integration

## Setup

Install the dependencies:

```powershell
pip install -r requirements.txt```

Run the vision pipeline against the XIAO camera stream:

```bash
cd vision
CAVIA_CAMERA_IP=<xiao-ip> python objdet.py
```

Press `Q` or `Esc` to quit. Interface contracts and the planned package layout are in
[`docs/interfaces.md`](../../docs/interfaces.md) and [`docs/architecture.md`](../../docs/architecture.md).
