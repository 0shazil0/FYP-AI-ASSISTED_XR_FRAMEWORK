# NeuroGuide XR — Implementation Plan 2.0

## Hybrid Open-Vocabulary Vision + Reasoning Architecture

**Group 19 | FYP 2026**
**Date:** March 6, 2026
**Status:** Revised after review of the current workspace and backend scaffold

---

## 1. Why This Revision Exists

The original plan was useful for bootstrapping, but it is now partially misaligned with both:

- the **current codebase state**, and
- the **target research direction** for a stronger, more publishable FYP.

### Key observations from the current workspace

| Area | Current State | Implication |
|---|---|---|
| Backend server | FastAPI + WebSocket pipeline already exists in `backend/main.py` | Good base for streaming XR guidance |
| Frame filtering | `backend/services/frame_differ.py` is already implemented | Good foundation for event-triggered inference |
| Vision-language service | `backend/services/vlm_service.py` currently calls local Ollama with `qwen3-vl:4b` | Good for prototyping, but not ideal as the only perception module |
| Config | `backend/config.py` currently targets local Ollama settings | Favors local/offline experimentation |
| Unity project | Main Unity AR project exists and builds | Front-end XR base is available |
| Unity integration scripts | `UnityClient/` still appears separate from the main Unity scene structure | Integration work remains |
| Advanced perception | No dedicated detector / segmenter / depth estimator yet | Main technical gap |

### Why the old plan needs updating

The earlier architecture leaned too heavily on a single multimodal model for everything. That is workable for demos, but not ideal for:

- real-time XR responsiveness,
- strong scene grounding,
- open-vocabulary detection,
- explainable system design,
- publishable systems framing.

---

## 2. Revised Core Decision

## Final System Direction

Build a **hybrid perception-reasoning XR assistant** with four layers:

1. **Fast Perception Layer**  
   Lightweight detector/tracker for frequent updates.
2. **Deep Semantic Layer**  
   Triggered open-vocabulary detection + segmentation + optional depth.
3. **Reasoning Layer**  
   Text LLM consumes structured scene JSON, not raw images when possible.
4. **XR Delivery Layer**  
   Unity renders arrows, highlights, labels, step panels, and interaction feedback.

This is the best balance of:

- accuracy,
- speed,
- open-world coverage,
- hardware realism,
- research value.

---

## 3. Updated Architecture

```text
ANDROID / UNITY XR CLIENT
    |
    |  RGB frame + device state + task context
    v
FASTAPI WEBSOCKET BACKEND
    |
    +--> Frame differ / trigger logic
    |
    +--> Fast Perception Layer
    |       - YOLOv8n ONNX or equivalent lightweight detector
    |       - runs frequently for tracking / quick updates
    |
    +--> Deep Semantic Layer (only on trigger)
    |       - Grounding DINO for open-vocabulary detection
    |       - SAM for precise masks / object regions
    |       - MiDaS or ZoeDepth for relative depth (optional but valuable)
    |
    +--> Scene Fusion Layer
    |       - merge boxes, labels, masks, depth, task state
    |       - build compact scene JSON
    |
    +--> Reasoning Layer
    |       - Qwen3:4B / Qwen2.5 / small text LLM via Ollama or vLLM
    |       - returns structured step guidance
    |
    +--> Safety / Rule Layer
    |       - confidence thresholds
    |       - fallback instructions
    |       - no unsafe hallucinated actuation
    |
    v
UNITY XR OVERLAY SYSTEM
    - arrow placement
    - highlight placement
    - text panels
    - step progress UI
    - optional audio guidance
```

---

## 4. Model Strategy

### 4.1 Fast layer

**Primary choice:** `YOLOv8n` exported to ONNX  
**Role:** fast detection, tracking cues, continuous updates, cheap trigger signals.

Why it stays:
- fast on modest hardware,
- easy deployment,
- good for frame-to-frame continuity,
- useful even if class vocabulary is limited.

### 4.2 Deep semantic layer

**Primary choice:** `Grounding DINO`  
**Role:** open-vocabulary detection using text prompts.

Why:
- much broader semantic coverage than fixed COCO-only detectors,
- stronger match for real-world assistive guidance,
- useful for domain transfer across gym, kitchen, lab, room objects.

### 4.3 Segmentation layer

**Primary choice:** `SAM` or `MobileSAM`  
**Role:** accurate region masks and better spatial grounding.

Why:
- more precise overlay anchoring,
- stronger visual explanation in AR,
- enables future region-level interaction.

### 4.4 Depth layer

**Primary choice:** `MiDaS small` initially  
**Role:** relative distance estimation for spatial reasoning.

Why:
- useful for approximate placement,
- good research value,
- optional in MVP but strong in final system.

### 4.5 Reasoning layer

**Primary choice:** local text reasoning via `Qwen3:4B` or similar through Ollama  
**Role:** instruction generation, step logic, contextual feedback.

Important change:
- use the LLM mainly for **reasoning over structured scene data**,
- do **not** rely on a vision LLM for every frame.

This reduces latency and makes the system easier to defend academically.

---

## 5. Why This Stack Is Better Than a Single VLM Pipeline

| Approach | Strength | Limitation |
|---|---|---|
| Single VLM for all frames | Simple prototype | Too slow, expensive, harder to control |
| YOLO-only | Fast | Limited object vocabulary and weak semantics |
| Grounding DINO only | Open vocabulary | Too heavy to run continuously |
| **Hybrid stack** | Best balance of speed + semantics + realism | More engineering effort, but worth it |

### Research argument

This revised system is stronger because it explicitly separates:

- **perception**,
- **scene understanding**,
- **reasoning**,
- **XR presentation**.

That separation is publishable, modular, and easier to evaluate.

---

## 6. Real-Time Execution Policy

Do **not** run heavy models on every frame.

### Trigger policy

Run `Grounding DINO + SAM (+ depth)` only when one of the following happens:

- significant scene change from `FrameDiffer`,
- a new object class appears,
- user requests explanation,
- task step changes,
- confidence from fast detector drops,
- periodic refresh timer expires.

### Default loop

- Unity captures frames at controlled intervals.
- Backend compares against recent state.
- Fast detector updates short-term object hypotheses.
- Heavy semantic refresh is triggered only when needed.
- Scene JSON is cached.
- LLM is called only when guidance meaningfully needs updating.

This is the most practical design for limited GPUs and laptop deployment.

---

## 7. Structured Scene Representation

The reasoning model should consume compact scene JSON.

### Target schema

```json
{
  "scene_id": "session_001_frame_128",
  "task_context": {
    "use_case": "gym_coach",
    "task": "bench_press",
    "step_number": 2,
    "total_steps": 5
  },
  "objects": [
    {
      "label": "barbell",
      "confidence": 0.91,
      "source": "grounding_dino",
      "bbox": [0.34, 0.21, 0.62, 0.33],
      "depth": 1.42,
      "mask_ref": "mask_01"
    }
  ],
  "scene_summary": "indoor gym scene with bench and barbell",
  "camera_state": {
    "device_motion": "stable"
  },
  "system_confidence": 0.86
}
```

### Why this matters

This makes the reasoning layer:

- faster,
- cheaper,
- more deterministic,
- easier to debug,
- easier to evaluate.

---

## 8. Updated System Phases

## Phase 0 — Baseline Consolidation

**Goal:** stabilize the current scaffold before adding advanced perception.

### Tasks
- Merge or verify Unity runtime scripts inside the main Unity project.
- Confirm phone or editor client can send frames to `backend/main.py`.
- Keep the current `vlm_service.py` as a temporary fallback guidance path.
- Add explicit message schemas for `frame`, `guidance`, `status`, and `error`.
- Add per-session logging and saved sample frames for debugging.

### Deliverable
End-to-end Unity-to-backend-to-Unity loop works reliably.

---

## Phase 1 — Refactor Backend Into Services

**Goal:** turn the current backend into a modular hybrid pipeline.

### New backend services to add
- `backend/services/detection_service.py`
- `backend/services/open_vocab_service.py`
- `backend/services/segmentation_service.py`
- `backend/services/depth_service.py`
- `backend/services/scene_fusion_service.py`
- `backend/services/reasoning_service.py`
- `backend/services/cache_service.py`
- `backend/services/task_state_manager.py`

### Refactoring changes
- Keep `frame_differ.py` and expand it for trigger control.
- Rename or narrow `vlm_service.py` into one of two roles:
  - temporary fallback multimodal path, or
  - final text reasoning path if image input is removed from that service.
- Introduce a central orchestrator in `main.py` or `pipeline_service.py`.

### Deliverable
Backend supports modular model calls rather than a single all-in-one request path.

---

## Phase 2 — Fast Perception Layer

**Goal:** add lightweight continuous detection.

### Tasks
- Train or adopt a small `YOLOv8n` baseline.
- Export to ONNX.
- Run inference locally with ONNX Runtime.
- Return normalized bounding boxes and confidence values.
- Add simple object tracking or temporal smoothing.
- Use detector output for trigger suggestions and overlay continuity.

### Deliverable
Fast object hints are available at near real-time speed.

---

## Phase 3 — Deep Semantic Layer

**Goal:** add open-vocabulary understanding.

### Tasks
- Integrate `Grounding DINO`.
- Define prompt sets by domain:
  - gym equipment,
  - body parts / posture anchors,
  - kitchen items,
  - room objects / signage.
- Add configurable confidence thresholds.
- Store results in a shared scene object format.
- Evaluate response time on available hardware.

### Deliverable
System detects many more real-world objects than YOLO alone.

---

## Phase 4 — Segmentation + Optional Depth

**Goal:** improve precision for XR anchoring and spatial reasoning.

### Tasks
- Feed selected Grounding DINO boxes into `SAM` or `MobileSAM`.
- Produce mask references or contour summaries.
- Integrate `MiDaS small` for relative depth estimation.
- Fuse approximate depth with object detections.
- Add world placement heuristics for Unity overlays.

### Deliverable
Higher-quality overlays with stronger scene grounding.

---

## Phase 5 — Scene Fusion + Reasoning

**Goal:** move from raw detections to explainable guidance.

### Tasks
- Build `scene_fusion_service.py` to merge:
  - fast detection,
  - open-vocabulary detection,
  - segmentation,
  - optional depth,
  - task state,
  - recent history.
- Create compact JSON prompts for the LLM.
- Use a text-first reasoning model through Ollama or vLLM.
- Enforce structured JSON outputs for guidance.
- Add rule-based guardrails for unsafe or low-confidence cases.

### Target response schema

```json
{
  "type": "guidance",
  "task": "bench_press",
  "instruction_text": "Lower the bar in a controlled motion and keep your wrists aligned.",
  "visual_type": "highlight",
  "target_label": "barbell",
  "location_3d": [0.0, 0.15, 1.4],
  "objects_detected": ["barbell", "bench"],
  "step_number": 2,
  "total_steps": 5,
  "confidence": 0.86,
  "reasoning_source": "scene_json"
}
```

### Deliverable
Reasoning is grounded in structured perception instead of raw image guessing.

---

## Phase 6 — Unity XR Integration

**Goal:** convert backend intelligence into convincing assistive XR output.

### Tasks
- Move production scripts into `My project (1)/Assets/Scripts/` if still separated.
- Add a clear `GuidanceMessage` C# model matching backend JSON.
- Implement overlay manager support for:
  - arrows,
  - highlights,
  - labels,
  - step panels,
  - confidence-aware fallbacks.
- Use raycasts / anchors for 2D-to-3D placement.
- Add smoothing to reduce jitter.
- Show system states such as:
  - detecting,
  - understanding,
  - guiding,
  - low confidence.

### Deliverable
Unity scene presents stable, meaningful, task-aware AR guidance.

---

## Phase 7 — Domain Completion

**Goal:** demonstrate one polished primary domain and one transferable secondary domain.

### Domain priority
1. **Primary:** Gym Coach
2. **Secondary:** Cooking Assistant

### Gym Coach scope
- identify equipment,
- identify current step,
- give posture or motion correction,
- highlight target object or interaction region.

### Cooking Assistant scope
- detect tools / ingredients,
- highlight next target item,
- guide procedural steps.

### Deliverable
Generalizable hybrid XR assistant across two domains.

---

## Phase 8 — Evaluation and Thesis Packaging

**Goal:** produce strong FYP evidence.

### Technical metrics
- end-to-end latency,
- triggered semantic refresh frequency,
- fast layer FPS,
- heavy layer response time,
- object grounding accuracy,
- overlay stability,
- cache hit rate,
- task completion success.

### Study metrics
- task completion time,
- error rate,
- perceived workload (NASA-TLX),
- usability (SUS),
- user confidence / clarity ratings.

### Research framing
Present the contribution as:

> A hybrid open-vocabulary perception and structured reasoning pipeline for mobile XR task guidance under constrained compute.

### Deliverable
A defensible, systems-oriented thesis with measurable technical claims.

---

## 9. Recommended File/Module End State

```text
backend/
├── main.py
├── config.py
├── requirements.txt
├── prompts/
│   ├── gym_coach.txt
│   ├── cooking_assistant.txt
│   └── reasoning_template.txt
├── services/
│   ├── frame_differ.py
│   ├── detection_service.py
│   ├── open_vocab_service.py
│   ├── segmentation_service.py
│   ├── depth_service.py
│   ├── scene_fusion_service.py
│   ├── reasoning_service.py
│   ├── task_state_manager.py
│   ├── cache_service.py
│   └── vlm_service.py          # fallback / transitional path only
└── models/
    ├── yolo/
    ├── grounding_dino/
    ├── sam/
    └── midas/
```

```text
My project (1)/Assets/
├── Scripts/
│   ├── Networking/
│   ├── AR/
│   ├── UI/
│   ├── Voice/
│   └── Core/
├── Prefabs/
├── Materials/
└── Scenes/
```

---

## 10. Practical Deployment Recommendation

### Minimum realistic path
If hardware is limited, use this staged deployment order:

1. `FrameDiffer` + current backend loop
2. `YOLOv8n ONNX`
3. `Grounding DINO` on trigger only
4. `SAM` for selected targets only
5. `MiDaS small` only if timing allows
6. Text reasoning via local Ollama

### Fallback policy
If `Grounding DINO + SAM` is too slow on the target machine:
- keep them as on-demand semantic refresh only,
- reduce image resolution,
- reduce prompt vocabulary,
- use MobileSAM,
- run without depth for MVP.

This still preserves the thesis contribution.

---

## 11. What Changes Immediately From the Old Plan

| Old Direction | New Direction |
|---|---|
| Single VLM-heavy guidance path | Hybrid layered perception + reasoning |
| Cloud-first Gemini assumption | Local-first modular pipeline, with optional fallback |
| Bounding boxes mainly from VLM output | Detection-first, then reasoning |
| Limited explainability | Strong structured-scene pipeline |
| Harder to scale to new objects | Open-vocabulary detection via Grounding DINO |
| Good demo architecture | Better research architecture |

---

## 12. Immediate Next Steps

### Sprint 1
- Keep the current backend functional.
- Refactor `vlm_service.py` into a temporary fallback role.
- Add a `reasoning_service.py` interface.
- Define the canonical scene JSON schema.
- Add `status` and `confidence` fields to backend responses.

### Sprint 2
- Integrate `YOLOv8n ONNX`.
- Benchmark latency on your machine.
- Use the fast detector for live updates and trigger signals.

### Sprint 3
- Integrate `Grounding DINO` as a triggered service.
- Start with gym prompt vocabulary.
- Log outputs for comparison against YOLO-only results.

### Sprint 4
- Add `SAM` and optional `MiDaS`.
- Improve Unity overlay placement using richer geometry cues.

---

## 13. Final Recommendation

For this FYP, the strongest realistic target is:

**Fast detector + triggered open-vocabulary detector + segmentation + optional depth + structured text reasoning + Unity XR overlays.**

That gives you:
- real engineering depth,
- publishable system design,
- practical runtime behavior,
- better explainability,
- stronger thesis narrative than a plain YOLO or plain VLM pipeline.

---

## 14. Decision Summary

### Adopt as official Plan 2.0

- **Primary runtime architecture:** hybrid triggered pipeline
- **Primary real-time detector:** YOLOv8n ONNX
- **Primary semantic detector:** Grounding DINO
- **Primary segmenter:** SAM or MobileSAM
- **Optional depth:** MiDaS small
- **Primary reasoner:** local text LLM via Ollama / vLLM
- **Primary demo domain:** Gym Coach
- **Secondary transfer domain:** Cooking Assistant

This is the recommended implementation direction going forward.
