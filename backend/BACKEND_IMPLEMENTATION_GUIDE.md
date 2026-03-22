# Backend Module Breakdown and Detailed Implementation Guide

## NeuroGuide XR — Phase-by-Phase Backend Plan

**Date:** March 6, 2026
**Primary detector for Phase 1:** `YOLOv26`

---

## 1. Concrete Backend Module Breakdown

### Current target structure

```text
backend/
├── main.py
├── config.py
├── requirements.txt
├── schemas.py
├── prompts/
│   └── gym_coach.txt
└── services/
    ├── __init__.py
    ├── frame_differ.py
    ├── vlm_service.py
    ├── detection_service.py
  ├── open_vocab_service.py
    ├── scene_fusion_service.py
    ├── reasoning_service.py
    └── pipeline_service.py
```

### Module responsibilities

| Module | Responsibility | Phase |
|---|---|---|
| [main.py](main.py) | FastAPI app, WebSocket endpoint, request loop | Phase 0–1 |
| [config.py](config.py) | All runtime settings and environment flags | Phase 0–1 |
| [schemas.py](schemas.py) | Typed message contracts for detections, scenes, and guidance | Phase 1 |
| [services/frame_differ.py](services/frame_differ.py) | Skip redundant heavy processing | Phase 0 |
| [services/detection_service.py](services/detection_service.py) | `YOLOv26` loading, ONNX export, and inference | Phase 1 |
| [services/open_vocab_service.py](services/open_vocab_service.py) | Triggered `Grounding DINO` open-vocabulary detection scaffold | Phase 2 |
| [services/scene_fusion_service.py](services/scene_fusion_service.py) | Convert raw detections into a structured scene object | Phase 1 |
| [services/reasoning_service.py](services/reasoning_service.py) | Produce guidance from scene JSON; fallback to VLM if needed | Phase 1 |
| [services/pipeline_service.py](services/pipeline_service.py) | Orchestrates decode → detect → fuse → reason | Phase 1 |
| [services/vlm_service.py](services/vlm_service.py) | Transitional multimodal fallback path | Phase 1 |

---

## 2. Phase-by-Phase Delivery Plan

## Phase 0 — Stable Transport Loop

### Goal
Have a reliable XR-to-backend loop before adding advanced models.

### Required outcome
- Unity sends frames.
- Backend decodes frames.
- `FrameDiffer` suppresses redundant work.
- Backend responds with valid guidance JSON.

### Status
Already mostly present.

---

## Phase 1 — `YOLOv26` Detection Backbone

### Goal
Introduce a fast local detector as the first perception layer.

### Why this phase comes first
This gives:
- immediate measurable progress,
- usable detections without waiting for open-vocabulary models,
- a clean interface for later `Grounding DINO` and `SAM` integration.

### Implementation flow
1. Load `yolo26n.pt`
2. Export to ONNX
3. Load `yolo26n.onnx`
4. Run inference on decoded OpenCV frames
5. Convert detections into normalized scene JSON
6. Produce rule-based guidance
7. Keep `vlm_service.py` as fallback only

### Reference code path

```python
from ultralytics import YOLO

model = YOLO("yolo26n.pt")
model.export(format="onnx")
onnx_model = YOLO("yolo26n.onnx")
results = onnx_model("https://ultralytics.com/images/bus.jpg")
```

### In this backend, the runtime version is adapted to:
- export automatically if the ONNX file does not exist,
- run inference on frame arrays instead of URLs,
- normalize boxes for Unity/XR use.

---

## Phase 2 — Structured Scene Fusion

### Goal
Stop sending raw detector outputs directly into UI logic.

### Output contract
Every frame should become a scene object like:

```json
{
  "scene_id": "scene_20260306_120000_123456",
  "task_context": {
    "use_case": "gym_coach",
    "task": "general_guidance",
    "step_number": 1,
    "total_steps": 1
  },
  "objects": [
    {
      "label": "barbell",
      "confidence": 0.91,
      "bbox": [0.31, 0.22, 0.66, 0.36],
      "source": "yolo26_onnx"
    }
  ],
  "scene_summary": "Detected barbell, bench",
  "system_confidence": 0.84
}
```

### Why this matters
This scene object becomes the stable interface for:
- Unity overlays,
- text reasoning,
- evaluation logging,
- future semantic upgrades.

---

## Phase 3 — Reasoning Layer

### Goal
Generate task guidance from scene JSON.

### Initial method
Use lightweight rule-based reasoning.

### Transitional method
If scene confidence is weak, call [services/vlm_service.py](services/vlm_service.py).

### Final method
Replace or augment with a text LLM that consumes scene JSON.

### Why this is correct
This avoids using a multimodal model for every frame.

---

## Phase 4 — Open-Vocabulary Upgrade

### Goal
Add `Grounding DINO` only after the local fast detector is stable.

### Integration point
[services/open_vocab_service.py](services/open_vocab_service.py) is now scaffolded and plugged into [services/pipeline_service.py](services/pipeline_service.py).

### Trigger policy
Run only on:
- scene changes,
- user requests,
- low-confidence detector states,
- periodic refresh.

### Current scaffold behavior
- disabled by default through `GROUNDING_DINO_ENABLED=false`
- supports per-use-case label vocabularies
- can be forced with `force_open_vocab=true`
- can be requested with `request_mode="explain_scene"`

---

## Phase 5 — Segmentation and Depth

### Goal
Improve overlay placement and spatial explanation.

### Add later
- `SAM` or `MobileSAM`
- `MiDaS small`

These should enrich the scene object, not replace it.

---

## 3. Detailed Implementation Guide

## Step 1 — Install dependencies

Update [requirements.txt](requirements.txt) with:
- `ultralytics`
- `onnxruntime`

Optional later:
- `onnx`
- `onnxsim`

---

## Step 2 — Add runtime configuration

Use [config.py](config.py) for:
- `YOLO_MODEL_NAME`
- `YOLO_IMAGE_SIZE`
- `YOLO_CONFIDENCE_THRESHOLD`
- `YOLO_MAX_DETECTIONS`
- `YOLO_EXPORT_ONNX`
- `REASONING_USE_VLM_FALLBACK`

### Suggested defaults
- model: `yolo26n.pt`
- image size: `640`
- confidence: `0.35`
- export ONNX: `true`

---

## Step 3 — Create typed schemas

Use [schemas.py](schemas.py) to define:
- `TaskContext`
- `DetectionObject`
- `SceneState`
- `GuidancePayload`

This keeps the transport contract stable across all future phases.

---

## Step 4 — Build `YOLOv26` detection service

Use [services/detection_service.py](services/detection_service.py).

For manual verification, use [export_yolo26_to_onnx.py](export_yolo26_to_onnx.py).

### Responsibilities
- lazy-load the model,
- export ONNX when needed,
- run inference,
- return normalized detections.

### Important behavior
If `ultralytics` is unavailable or model loading fails:
- disable the detector gracefully,
- keep the backend alive,
- expose error text in debug metadata.

---

## Step 5 — Build scene fusion layer

Use [services/scene_fusion_service.py](services/scene_fusion_service.py).

### Responsibilities
- assign `scene_id`,
- compute summary text,
- calculate scene confidence,
- store detector metadata.

This is where raw detections become an explainable scene description.

---

## Step 6 — Build reasoning layer

Use [services/reasoning_service.py](services/reasoning_service.py).

### Phase 1 behavior
- if gym objects appear, return gym-style guidance,
- if a person appears, return centering/alignment guidance,
- if no reliable objects appear, fall back to VLM or generic guidance.

### Why this is enough for now
It gives you:
- a working pipeline,
- measurable latency,
- a clean place to later replace rules with LLM reasoning.

---

## Step 7 — Build orchestration layer

Use [services/pipeline_service.py](services/pipeline_service.py).

### Responsibilities
- decode frame bytes,
- read task context from payload,
- call detection service,
- call scene fusion,
- call reasoning,
- return a single `GuidancePayload`.

This avoids placing application logic directly in [main.py](main.py).

---

## Step 8 — Refactor WebSocket route

Update [main.py](main.py) so the route only handles:
- client connection,
- input validation,
- frame differ check,
- timeout handling,
- cached response reuse,
- JSON response send.

The route should not contain perception logic anymore.

---

## 4. Immediate Test Plan

## Test A — Startup

Expected:
- backend starts,
- no import errors,
- detector either loads or fails gracefully.

## Test B — ONNX export

Expected on first run:
- `yolo26n.pt` loads,
- `yolo26n.onnx` is created,
- runtime uses the ONNX model.

## Test C — Inference

Send a valid frame.

Expected response:
- `type = guidance`
- `objects_detected` populated when objects are found
- `confidence` present
- `reasoning_source` present
- debug contains detector info

## Test D — Frame differ caching

Send nearly identical frames.

Expected:
- cached response reused,
- `debug.cache_hit = true`

---

## 5. Phase 1 Deliverable Definition

Phase 1 is complete when:
- `YOLOv26` is integrated,
- ONNX export works,
- backend produces structured guidance from detections,
- fallback still works if the detector fails,
- Unity can keep consuming the same response shape.

---

## 6. Recommended Next Implementation After Phase 1

After this phase is stable, add:
1. `open_vocab_service.py` for `Grounding DINO`
2. `segmentation_service.py` for `SAM`
3. `depth_service.py` for `MiDaS`
4. `task_state_manager.py` for multi-step flow
5. richer Unity overlay placement from normalized boxes

---

## 7. Summary

The correct order is:

1. transport stability
2. `YOLOv26` fast detection
3. scene schema
4. rule-based reasoning
5. VLM fallback
6. open-vocabulary upgrade
7. segmentation and depth

That sequence is practical, defensible, and aligned with your FYP goals.
