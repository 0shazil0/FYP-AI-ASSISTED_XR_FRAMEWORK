# NeuroGuide XR — Comprehensive Codebase Analysis Report

**Project:** NeuroGuide XR (Final Year Project)  
**Last Updated:** May 13, 2026  
**Status:** Active development — Phase 1 complete, Phase 2 in progress  

---

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Backend Structure & Architecture](#backend-structure--architecture)
3. [Backend Configuration & Models](#backend-configuration--models)
4. [Backend main.py — API & WebSocket Flow](#backend-mainpy--api--websocket-flow)
5. [Unity Project Structure](#unity-project-structure)
6. [Models & Assets](#models--assets)
7. [Data Flow Architecture](#data-flow-architecture)
8. [Key Features Implemented](#key-features-implemented)
9. [Implementation Patterns](#implementation-patterns)
10. [Integration Points](#integration-points)

---

## Executive Summary

**NeuroGuide XR** is a hybrid AR-assisted guidance system with two distinct operational modes:

### Mode 1: Live Scene Assistance (Half 1 — COMPLETE ✅)
- User points phone camera at physical environment (gym, kitchen, etc.)
- Backend captures frame, detects objects (YOLO), analyzes scene (VLM)
- Returns step-by-step guidance with world-anchored AR overlays
- Personas: Gym Trainer, Chef, Physiotherapist

### Mode 2: Software UI Assistance (Half 2 — IN PROGRESS)
- User asks natural language question about Windows software
- Backend converts query to UI automation steps via LLM
- Live PC screen streamed to phone, AR arrows guide through steps
- Uses pywinauto for Windows UI element resolution

**Technology Stack:**
- **Backend:** Python 3, FastAPI, AsyncIO, WebSocket
- **Mobile:** Unity 2022.3 LTS, AR Foundation, C#
- **AI/ML:** Ollama (local LLM/VLM), YOLO26, Grounding DINO, OpenAI/Hugging Face options
- **AR:** ARCore (Android), World-space anchored objects and overlays
- **Protocol:** WebSocket (JSON + binary frames), IMU sensor fusion

---

## Backend Structure & Architecture

### 1. Backend Directory Layout

```
backend/
├── main.py                          # FastAPI application, WebSocket handlers
├── config.py                        # Environment-based configuration
├── schemas.py                       # Pydantic models (contracts)
├── requirements.txt                 # Python dependencies
├── yolo26n.onnx                     # YOLO26 nano ONNX model (~6MB)
├── yolo26n.pt                       # YOLO26 nano PyTorch weights (~backup)
├── FastSAM-x.pt                     # FastSAM segmentation model (optional)
├── export_yolo26_to_onnx.py        # Utility to export YOLO to ONNX
├── prompts/                         # LLM/VLM prompt templates
│   ├── gym_coach.txt                # Main VLM prompt for gym guidance
│   ├── demo_scene.txt               # Alternative demo scene analysis
│   ├── demo_followup.txt            # Follow-up question analysis
│   ├── persona_gym_trainer.txt      # Gym trainer persona system prefix
│   ├── persona_chef.txt             # Chef persona system prefix
│   └── persona_physiotherapist.txt  # Physiotherapist persona prefix
└── services/                        # Modular AI/ML service layer
    ├── __init__.py
    ├── frame_differ.py              # Frame diffing for change detection
    ├── detection_service.py         # YOLO26 object detection
    ├── open_vocab_service.py        # Grounding DINO (open-vocabulary)
    ├── vlm_service.py               # Vision LLM (Ollama/OpenAI)
    ├── llm_service.py               # Language LLM for UI automation
    ├── scene_fusion_service.py      # Merges detections into scene state
    ├── reasoning_service.py         # Rule-based + VLM fallback reasoning
    ├── imu_fusion_service.py        # IMU sensor fusion (alpha smoothing)
    ├── pipeline_service.py          # Orchestrates all services
    ├── ui_detector.py               # Windows UI automation (pywinauto)
    ├── screen_capture.py            # Screen capture for copilot
    └── roboflow_detection_service.py # Custom gym machine detector
```

### 2. Service Dependencies & Relationships

```
main.py (FastAPI entry point)
  │
  ├── pipeline_service.py (Main orchestrator)
  │   ├── detection_service.py (YOLO26 runner)
  │   ├── open_vocab_service.py (Grounding DINO)
  │   ├── scene_fusion_service.py (Merge detections)
  │   ├── reasoning_service.py (Generate guidance)
  │   │   └── vlm_service.py (Fallback for empty scenes)
  │   ├── frame_differ.py (Frame change detection)
  │   └── imu_fusion_service.py (Motion scoring)
  │
  ├── vlm_service.py (Direct snapshot analysis)
  │   └── Ollama/OpenAI API calls
  │
  ├── llm_service.py (UI automation queries)
  │   ├── Ollama
  │   ├── OpenAI
  │   └── Hugging Face UI-TARS
  │
  ├── ui_detector.py (Windows element resolution)
  │   └── pywinauto (UIA Automation)
  │
  └── screen_capture.py (Live PC screen JPEG)
      └── PIL/Pillow
```

### 3. Service Descriptions

#### **frame_differ.py** — Change Detection Gate
- **Purpose:** Reduces redundant processing by caching frames below a threshold
- **Algorithm:** Compute absolute pixel difference between resized gray frames
- **Threshold:** Configurable, default 15.0 (mean absolute pixel change)
- **Output:** `(should_process: bool, diff_score: float)`
- **Use Case:** Only trigger expensive AI when scene materially changes

#### **detection_service.py** — YOLO26 Object Detection
- **Model:** YOLO26 Nano (lightweight, 6MB ONNX)
- **Input:** BGR image (OpenCV format)
- **Config Parameters:**
  - `YOLO_MODEL_NAME`: "yolo26n.onnx"
  - `YOLO_CONFIDENCE_THRESHOLD`: 0.5
  - `YOLO_IMAGE_SIZE`: 640
  - `YOLO_MAX_DETECTIONS`: 10
  - `YOLO_EXPORT_ONNX`: Auto-convert .pt to ONNX if enabled
- **Output:** `List[DetectionObject]` with (label, confidence, bbox, source)
- **Async:** Runs synchronously in a thread pool to avoid blocking

#### **open_vocab_service.py** — Grounding DINO (Open-Vocabulary Detection)
- **Model:** Grounding DINO Tiny (from HuggingFace)
- **Trigger Logic:** Only activated when:
  - YOLO confidence is low (<0.55)
  - Large frame difference (scene change spike)
  - IMU motion score is high
  - Minimum 3.0s since last trigger
- **Config Parameters:**
  - `GROUNDING_DINO_ENABLED`: Toggle (default: false)
  - `GROUNDING_DINO_MODEL_ID`: "IDEA-Research/grounding-dino-tiny"
  - `GROUNDING_DINO_BOX_THRESHOLD`: 0.30
  - `GROUNDING_DINO_TEXT_THRESHOLD`: 0.25
  - Labels per use-case (gym, cooking, default)
- **Device:** Auto GPU if available, fallback to CPU
- **Output:** Same schema as YOLO (DetectionObject list)

#### **vlm_service.py** — Vision Language Model
- **Models Supported:**
  - **Local Ollama:** qwen3-vl:4b (default), custom models
  - **Cloud Ollama:** gemma4:31b-cloud (slower, higher quality)
  - **OpenAI:** gpt-4o (Vision)
  - **HuggingFace:** Custom models
- **Modes:**
  1. **analyze_frame():** Stream mode, real-time guidance
  2. **analyze_snapshot():** Deep scene understanding with JSON recovery
- **Prompt System:** 
  - Base prompt + persona-specific prefix (gym_trainer, chef, physiotherapist)
  - Fallback to rule-based if VLM unavailable
- **JSON Recovery:** Auto-corrects truncated/malformed JSON responses
- **Timeout:** 150s (local), 300s (cloud)

#### **reasoning_service.py** — Guidance Generation Logic
- **Strategy:** Rule-based + optional VLM fallback
- **Rules Implemented:**
  1. If barbell/bench/dumbbell/kettlebell detected → "Focus on posture first..."
  2. If person detected → "Keep the subject centered..."
  3. Fallback → Request detailed VLM analysis if image available
- **Outputs:** `GuidancePayload` with:
  - instruction_text, visual_type, location_3d, confidence, reasoning_source

#### **scene_fusion_service.py** — State Building
- **Purpose:** Merges YOLO + Grounding DINO detections into unified SceneState
- **Unique Labels:** Extracts ordered list of detected objects
- **System Confidence:** Average confidence across all detections
- **Scene Summary:** Human-readable string ("Detected bench, person, dumbbell")
- **Metadata:** Includes diff_score, detector status, error messages, trigger reasons

#### **imu_fusion_service.py** — Motion Tracking
- **Input:** Accelerometer, Gyroscope, Attitude (quaternion) from mobile device
- **Smoothing:** Complementary filter with alpha parameter (default 0.24)
- **Motion Score:** Magnitude of acceleration (minus gravity) + gyroscope magnitude
- **Staleness Detection:** Marks IMU stale if >1.5s since last update
- **Use Case:** Triggers expensive Grounding DINO when motion exceeds threshold

#### **pipeline_service.py** — Orchestrator
- **Flow:**
  1. Decode frame from base64
  2. Run YOLO detection
  3. Decide whether to trigger Grounding DINO
  4. Merge detections
  5. Build scene state
  6. Generate guidance (rule-based + VLM fallback)
  7. Enrich debug info
- **Debug Output:** Includes all intermediate metrics for troubleshooting

#### **llm_service.py** — UI Automation Query Processor
- **Purpose:** Converts user natural language → structured UI action steps
- **Model Support:** Ollama, OpenAI, Hugging Face UI-TARS
- **System Prompt:** Enforces JSON response with strict schema
- **Output Schema:**
  ```json
  {
    "steps": [
      {
        "action": "click|type|scroll|double_click|right_click",
        "target": "UI element exact label",
        "type": "Button|MenuItem|Edit|TabItem|ComboBox",
        "value": "optional text to type"
      }
    ]
  }
  ```
- **Integration:** Works with pywinauto to map element labels to screen pixels

#### **ui_detector.py** — Windows UI Element Resolution
- **Technology:** pywinauto + UIA Automation API
- **Capabilities:**
  - Connect to running Windows app by title pattern
  - Resolve UI element by name + control type
  - Return pixel coordinates (x, y, width, height)
  - Timeout with graceful fallback
- **Supported Control Types:** Button, MenuItem, Edit, TabItem, ComboBox, etc.

---

## Backend Configuration & Models

### 1. config.py Environment Variables

#### **Core Timing**
```python
AI_TIMEOUT_SECONDS = 15                      # VLM analysis timeout
SNAPSHOT_TIMEOUT_SECONDS = 90               # Deep snapshot analysis
PROMPT_TIMEOUT_SECONDS = 90                 # Prompt generation timeout
FRAME_DIFF_THRESHOLD = 15.0                 # Mean pixel diff for frame change
```

#### **Ollama LLM Configuration**
```python
OLLAMA_MODE = "local" | "cloud"             # Where to run models
OLLAMA_BASE_URL = "http://127.0.0.1:11434"  # Local: localhost, Cloud: https://ollama.com
OLLAMA_MODEL = "qwen3-vl:4b"                # Local default (or "gemma4:31b-cloud")
OLLAMA_API_KEY = ""                         # Required for cloud mode
OLLAMA_TEMPERATURE = 0.2                    # Lower = more deterministic
OLLAMA_NUM_PREDICT = 512 | 1024             # Max tokens
OLLAMA_REQUEST_TIMEOUT_SECONDS = 150 | 300 # Adaptive timeout
OLLAMA_THINK = false                        # Enable thinking tokens (advanced)
```

#### **YOLO26 Detection**
```python
YOLO_MODEL_NAME = "yolo26n.onnx"           # Nano ONNX for speed
YOLO_IMAGE_SIZE = 640                      # Input resolution
YOLO_CONFIDENCE_THRESHOLD = 0.5            # Detection confidence gate
YOLO_MAX_DETECTIONS = 10                   # Limit detections per frame
YOLO_EXPORT_ONNX = false                   # Auto-convert .pt to .onnx
```

#### **IMU Fusion**
```python
IMU_FUSION_ALPHA = 0.24                    # Complementary filter smoothing
IMU_MAX_STALENESS_SECONDS = 1.5            # IMU data freshness threshold
IMU_HIGH_MOTION_THRESHOLD = 2.2            # Trigger Grounding DINO
```

#### **Grounding DINO (Open-Vocabulary)**
```python
GROUNDING_DINO_ENABLED = false             # Toggle (requires GPU)
GROUNDING_DINO_MODEL_ID = "IDEA-Research/grounding-dino-tiny"
GROUNDING_DINO_BOX_THRESHOLD = 0.30        # Spatial confidence
GROUNDING_DINO_TEXT_THRESHOLD = 0.25       # Text matching confidence
GROUNDING_DINO_MAX_DETECTIONS = 12
GROUNDING_DINO_TRIGGER_CONFIDENCE = 0.55   # YOLO confidence floor to trigger
GROUNDING_DINO_TRIGGER_DIFF_SCORE = 18.0   # Frame diff floor to trigger
GROUNDING_DINO_MIN_TRIGGER_INTERVAL_SECONDS = 3.0

# Context-specific labels
GROUNDING_DINO_GYM_LABELS = "person,bench,barbell,dumbbell,kettlebell,weight plate,exercise machine,water bottle,towel"
GROUNDING_DINO_COOKING_LABELS = "person,knife,cutting board,pot,pan,bowl,plate,spoon,fork,bottle,vegetable,fruit"
GROUNDING_DINO_DEFAULT_LABELS = "person,bottle,door,chair,table,bench,barbell,dumbbell,kettlebell,phone,bag"
```

#### **Half 2: Copilot (UI Assistance)**
```python
COPILOT_LLM_PROVIDER = "ollama" | "openai" | "ui_tars"
COPILOT_USE_OLLAMA = true
COPILOT_OLLAMA_MODEL = "qwen3-vl:4b"
COPILOT_OPENAI_MODEL = "gpt-4o"
COPILOT_HF_MODEL_ID = "ByteDance-Seed/UI-TARS-1.5"
COPILOT_HF_ENDPOINT_URL = ""                # Optional HF endpoint
COPILOT_HF_API_TOKEN = ""                   # HF API key
COPILOT_SCREEN_WIDTH = 1920                 # Captured screen resolution
COPILOT_SCREEN_HEIGHT = 1080
COPILOT_JPEG_QUALITY = 65                   # Compression (lower = faster)
COPILOT_MAX_STEPS = 8                       # Max steps per guidance
```

#### **Persona System**
```python
DEFAULT_PERSONA = "gym_trainer"             # gym_trainer | chef | physiotherapist
VALID_PERSONAS = {"gym_trainer", "chef", "physiotherapist"}
# Each persona has a prompt file: prompts/persona_<id>.txt
# Loaded at runtime and prepended to VLM system message
```

#### **Roboflow Custom Detector**
```python
ROBOFLOW_API_KEY = ""                       # Custom model API key
ROBOFLOW_PROJECT = ""                       # Project ID
ROBOFLOW_VERSION = "1"
ROBOFLOW_CONFIDENCE = 40                    # Confidence % (0-100)
ROBOFLOW_OVERLAP = 30                       # NMS overlap
# Detects: Flat Bench Press, Incline Bench, Lat Pulldown, Leg Press machines
```

### 2. Data Models (schemas.py)

```python
TaskContext(BaseModel):
    use_case: str = "gym_coach"           # Context for label selection
    task: str = "general_guidance"
    step_number: int = 1
    total_steps: int = 1

DetectionObject(BaseModel):
    label: str                            # e.g., "person", "bench"
    confidence: float ∈ [0.0, 1.0]
    bbox: list[float]                     # [x1, y1, x2, y2] normalized
    source: str = "yolo26"                # or "grounding_dino", "roboflow"

SceneState(BaseModel):
    scene_id: str                         # Unique scene identifier
    task_context: TaskContext
    objects: list[DetectionObject]        # All detections
    scene_summary: str                    # Human readable
    system_confidence: float ∈ [0.0, 1.0]
    metadata: dict[str, any]              # Extensible debug info

GuidancePayload(BaseModel):
    task: str = "general_guidance"
    instruction_text: str                 # Short, actionable instruction
    visual_type: str = "highlight"        # "highlight" or "arrow"
    location_3d: list[float]              # [x, y, z] normalized coords
    objects_detected: list[str]           # Which objects relevant
    step_number: int = 1
    total_steps: int = 1
    confidence: float ∈ [0.0, 1.0]
    reasoning_source: str                 # "rule_based_yolo26", "vlm_fallback", etc.
    debug: dict[str, any]                 # Metrics & intermediate results
```

### 3. Models Loaded at Runtime

| Model | Size | Format | Purpose | Optional |
|-------|------|--------|---------|----------|
| YOLO26 Nano | 6 MB | ONNX | Object detection | No (core) |
| Grounding DINO | ~1 GB | PyTorch | Open-vocab detection | Yes (config-gated) |
| FastSAM-x | ~380 MB | PyTorch | Segmentation | Yes (not actively used) |
| Ollama Models | 2-30 GB | GGUF | VLM/LLM | Yes (external service) |
| OpenAI/HF Models | N/A | API | Cloud inference | Yes (alternative provider) |

---

## Backend main.py — API & WebSocket Flow

### 1. FastAPI Server Initialization

```python
app = FastAPI(title="NeuroGuide XR Backend")

# CORS: Allow all origins for MVP
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)

# Singletons (shared across connections)
pipeline_service = PipelineService()       # Orchestrator
demo_vlm_service = VlmService()            # Direct snapshot analysis
_copilot_llm = LLMCopilotService(...)      # UI automation
_copilot_screen = ScreenCapture(...)       # Screen capture
```

### 2. REST Endpoints

#### **GET /health**
```python
Response: {"status": "ok"}
Purpose: Liveness probe
```

#### **GET /**
```python
Response: {"message": "NeuroGuide XR Backend is running"}
Purpose: Root status endpoint
```

### 3. WebSocket Endpoint: /stream

**Client:** Mobile Unity app (WebSocketManager)  
**Protocol:** JSON messages + base64-encoded JPEG frames  
**Auto-reconnect:** Yes (3s backoff)

#### **Message Types**

##### **3.1 Type: "frame"** — Real-time Guidance Request
```json
{
  "type": "frame",
  "image_data": "<base64-encoded JPEG>",
  "imu_data": {
    "accel": [0.0, 0.0, 9.81],
    "gyro": [0.0, 0.0, 0.0],
    "attitude": [0.0, 0.0, 0.0, 1.0],
    "device_orientation": "Portrait",
    "sent_at_ms": 1715556789000
  },
  "use_case": "gym_coach",
  "task": "barbell_squat",
  "step_number": 2,
  "total_steps": 5
}
```

**Processing Flow:**
1. Extract IMU, fuse with motion state
2. Decode base64 JPEG → OpenCV image
3. Frame differ check (cached if no change)
4. YOLO detection
5. Decide Grounding DINO trigger
6. Build scene state
7. Generate guidance (rule-based or VLM)
8. Send response

**Response:**
```json
{
  "type": "guidance",
  "task": "gym_coach",
  "instruction_text": "Focus on depth and control.",
  "visual_type": "highlight",
  "location_3d": [0.0, 0.0, 1.3],
  "objects_detected": ["person", "barbell"],
  "step_number": 2,
  "total_steps": 5,
  "confidence": 0.76,
  "reasoning_source": "rule_based_yolo26",
  "debug": {
    "cache_hit": false,
    "diff_score": 42.3,
    "detection_count": 2,
    "yolo_detection_count": 2,
    "open_vocab_detection_count": 0,
    "scene_id": "scene_20260513_154623_123456",
    "detector_error": "",
    "open_vocab_triggered": false,
    "object_hints": [
      {"label": "person", "bbox": [0.1, 0.2, 0.9, 0.8], "confidence": 0.92, "source": "yolo26"},
      {"label": "barbell", "bbox": [0.3, 0.4, 0.7, 0.6], "confidence": 0.88, "source": "yolo26"}
    ]
  }
}
```

**Cache Hit (low diff):**
```json
{
  "type": "guidance",
  ...previous response...,
  "debug": {
    "cache_hit": true,
    "diff_score": 3.2
  }
}
```

##### **3.2 Type: "snapshot"** — Deep Scene Analysis
```json
{
  "type": "snapshot",
  "image_data": "<base64-encoded JPEG>",
  "imu_data": { ... },
  "use_case": "gym_coach",
  "task": "posture_check"
}
```

**Processing Flow:**
1. Decode image
2. Run YOLO (persisted for context)
3. **Call VlmService.analyze_snapshot()** with YOLO context
4. Extract JSON response (with recovery for truncation)
5. Return enriched guidance

**Response:**
```json
{
  "type": "guidance",
  "task": "posture_assessment",
  "instruction_text": "Your shoulders are rounded. Retract scapula, engage lats.",
  "visual_type": "arrow",
  "location_3d": [0.2, 0.15, 1.4],
  "objects_detected": ["person"],
  "step_number": 1,
  "total_steps": 1,
  "confidence": 0.82,
  "reasoning_source": "vlm_snapshot",
  "debug": { ... }
}
```

##### **3.3 Type: "imu"** — IMU-Only Update
```json
{
  "type": "imu",
  "timestamp": 1715556789000,
  "imu": {
    "accel": [...],
    "gyro": [...],
    "attitude": [...],
    "device_orientation": "Portrait"
  }
}
```

**No Response.** Server updates motion state internally.

##### **3.4 Type: "step_action"** — Step Navigation
```json
{
  "type": "step_action",
  "action": "next" | "previous" | "complete" | "reset"
}
```

**Processing:**
- Updates step_guidance state machine
- Re-sends updated step_guidance response

**Response:**
```json
{
  "type": "step_update",
  "action": "next",
  "step_guidance": {
    "current_step": 3,
    "total_steps": 5,
    "is_complete": false,
    "completed_steps": [1, 2],
    ...
  }
}
```

### 4. Error Handling

**Frame decode fails:**
```json
{"type": "error", "message": "Invalid image encoding"}
```

**Timeout:**
```json
{
  "type": "guidance",
  "task": "general_guidance",
  "instruction_text": "AI timeout. Keep camera steady and retry.",
  "confidence": 0.0,
  "reasoning_source": "timeout_fallback",
  "debug": {}
}
```

### 5. Roboflow Gym Machine Alert

If custom Roboflow detector identifies gym equipment:
```json
{
  "type": "guidance",
  ...standard fields...,
  "yolo_machine_alert": {
    "label": "Flat Bench Press Machine",
    "display_name": "Flat Bench Press Machine",
    "confidence": 0.87,
    "cx_norm": 0.5,
    "cy_norm": 0.4,
    "bbox_norm": [0.2, 0.15, 0.8, 0.85]
  }
}
```

---

## Unity Project Structure

### 1. Scene Organization

```
Assets/Scenes/
├── MainScene.unity              # Original Half 1 (Live Guidance)
├── ModeSelect.unity             # [NEW] Entry point (Half 1 vs Half 2 selector)
└── CopilotAR.unity              # [NEW] Half 2 (Software UI Assistance)
```

### 2. Scripts Organization

#### **Networking Layer**

[WebSocketManager.cs](My%20project%20(1)/Assets/Scripts/Networking/WebSocketManager.cs)
- **Role:** WebSocket client singleton for backend communication
- **Key Features:**
  - Auto-reconnect with configurable backoff (default 2s)
  - Thread-safe send/receive via semaphore
  - Events: `MessageReceived`, `ConnectionStateChanged`
  - Default endpoint: `ws://192.168.0.102:8000/stream`
- **Lifecycle:** Persists across scenes (DontDestroyOnLoad)

[MainThreadDispatcher.cs](My%20project%20(1)/Assets/Scripts/Networking/MainThreadDispatcher.cs)
- **Role:** Thread-safe queue for marshaling async callbacks to Unity main thread
- **Use Case:** WebSocket receive runs on background thread; must update UI on main thread

#### **AR Layer**

[ARCameraCapture.cs](My%20project%20(1)/Assets/Scripts/AR/ARCameraCapture.cs)
- **Role:** Captures AR camera frames and encodes to JPEG
- **Key Methods:**
  - `CaptureAndSendFrame()` — Acquire CPU image, scale, compress, send via WebSocket
  - Cooldown throttling (default 1.5s between captures)
- **Config:**
  - `captureScale`: 0.5 (50% resolution for bandwidth)
  - `jpegQuality`: 60 (JPEG compression)
  - `minCaptureIntervalSeconds`: 1.5

[IMUSensorStreamer.cs](My%20project%20(1)/Assets/Scripts/AR/IMUSensorStreamer.cs)
- **Role:** Continuously streams device motion sensors (accelerometer, gyroscope, attitude)
- **Config:**
  - `sendIntervalSeconds`: 0.12 (≈8 Hz sample rate)
  - `sendWhenDisconnected`: false
  - `pauseStreaming`: manual pause control
- **Data:** Input.acceleration, Input.gyro, Input.gyro.attitude

[AROverlayManager.cs](My%20project%20(1)/Assets/Scripts/AR/AROverlayManager.cs)
- **Role:** Renders world-space AR overlays (arrows, highlights, step cards)
- **Features:**
  - Multiple overlay types (arrow prefab, highlight prefab, step card)
  - Hint tracking with smoothing (alpha blending for stability)
  - Confidence-gated rendering (won't show below threshold)
  - Calibration mode for tuning
- **Config:**
  - `defaultDistance`: 1.2 m (default AR depth)
  - `hintConfidenceThreshold`: 0.55 (show hints if confidence > this)
  - `hintSmoothingAlpha`: 0.3 (smoothing strength)
  - `maxHintMovePerUpdate`: 0.18 (max movement per frame)
  - `overlayOpacity`: 0.35 (transparency)

[AttentionGate.cs](My%20project%20(1)/Assets/Scripts/AR/AttentionGate.cs)
- **Role:** (Placeholder/minimal) Framework for attention-aware frame gating
- **Use Case:** Could implement eye-tracking or saliency filtering

#### **Core / Control**

[NeuroGuideController.cs](My%20project%20(1)/Assets/Scripts/Core/NeuroGuideController.cs)
- **Role:** Scene bootstrap glue
- **Responsibilities:**
  - Find/cache WebSocketManager and AROverlayManager
  - Initialize logging
  - Handle missing component warnings

#### **UI Layer**

[SnapDemoUI.cs](My%20project%20(1)/Assets/Scripts/UI/SnapDemoUI.cs) — Half 1
- **Purpose:** Main UI panel for Live Scene Assistance
- **Controls:**
  - "Snap" button → capture frame
  - "Ask" button → deep snapshot analysis
  - Step controls: Next, Previous, Reset
  - Status display

[CopilotUI.cs](My%20project%20(1)/Assets/Scripts/UI/CopilotUI.cs) — Half 2
- **Purpose:** UI panel for Software UI Assistance
- **Controls:**
  - Query input field
  - App selector (Word, Excel, Notepad, Chrome, PowerPoint)
  - "Ask" button → send query to backend
  - Step navigation (Prev, Next)
  - Status bar + instruction display
- **Built Programmatically:** All UI elements created at runtime (no prefabs)

[ModeSelectUI.cs](My%20project%20(1)/Assets/Scripts/UI/ModeSelectUI.cs) — Half 1→2 Router
- **Purpose:** Entry-point scene with two large buttons
- **Buttons:**
  1. "🌍 Live Scene Assistance" → Load MainScene (Half 1)
  2. "🖥️ Software UI Help" → Load CopilotAR (Half 2)

#### **Copilot (Half 2) Layer**

[CopilotWebSocketClient.cs](My%20project%20(1)/Assets/Scripts/Copilot/CopilotWebSocketClient.cs)
- **Role:** Dedicated WebSocket client for `/copilot` endpoint (separate from Half 1's `/stream`)
- **Features:**
  - Try localhost in editor, fallback to IP in build
  - Auto-reconnect logic
  - Separate from WebSocketManager (no conflict)
  - Binary frame support for screen capture streaming

[CopilotStepController.cs](My%20project%20(1)/Assets/Scripts/Copilot/CopilotStepController.cs)
- **Role:** State machine for step-by-step UI guidance
- **State:**
  - Current step index
  - List of steps (action, target, pixel coords)
  - Step completeness tracking
- **Public API:**
  - `SendQuery(query, appName)` → Send to backend
  - `NextStep()`, `PrevStep()` → Navigation
  - `RequestScreenFrame()` → Refresh PC screen capture
- **Message Handling:** Listens for `copilot_steps` and `screen_frame` from backend

[CopilotOverlayManager.cs](My%20project%20(1)/Assets/Scripts/Copilot/CopilotOverlayManager.cs)
- **Role:** Renders AR overlays on top of virtual screen quad
- **Features:**
  - Places arrows/highlights at pixel coordinates from pywinauto
  - Resolves pixel coords to 3D world positions
  - Animated transitions between steps

[VirtualScreenManager.cs](My%20project%20(1)/Assets/Scripts/Copilot/VirtualScreenManager.cs)
- **Role:** Creates and manages the virtual AR screen quad showing live PC capture
- **Features:**
  - Anchors screen in world space (default: 2m away, eye level)
  - Updates screen texture as JPEG frames arrive
  - Configurable size + scaling

### 3. Component Connections

```
NeuroGuideController (Bootstrap)
  │
  ├─→ WebSocketManager (networking singleton)
  │    └─→ MainThreadDispatcher (thread marshaling)
  │
  ├─→ AROverlayManager (Half 1)
  │    └─→ (Listens to WebSocketManager.MessageReceived)
  │
  └─→ CopilotWebSocketClient (Half 2)
       ├─→ CopilotStepController
       │    ├─→ VirtualScreenManager
       │    ├─→ CopilotOverlayManager
       │    └─→ CopilotUI
       └─→ (Sends to /copilot WebSocket endpoint)

Scene Flow:
ModeSelectUI (startup)
  ├─→ [Live Guidance] → MainScene + SnapDemoUI
  └─→ [Software Help] → CopilotAR + CopilotUI
```

---

## Models & Assets

### 1. Computer Vision Models

| Model | File | Size | Format | Provider | Purpose | GPU? |
|-------|------|------|--------|----------|---------|------|
| YOLO26 Nano | yolo26n.onnx | 6 MB | ONNX | Ultralytics | Fast object detection | Optional |
| YOLO26 Nano | yolo26n.pt | 12 MB | PyTorch | Ultralytics | Training checkpoint | Optional |
| Grounding DINO Tiny | (HF download) | 1 GB | PyTorch | IDEA-Research | Open-vocab detection | Recommended |
| FastSAM-x | FastSAM-x.pt | 380 MB | PyTorch | MetaAI | Segmentation masks | Optional |

### 2. LLM Models (External)

#### **Ollama (Local or Cloud)**
- **Local Setup:** Run `ollama pull qwen3-vl:4b` on backend machine
- **Models Available:**
  - qwen3-vl:4b (default, ~2.5 GB)
  - llama3.2 (text-only)
  - Custom fine-tuned models
- **Cloud Alternative:** Ollama Cloud API (slower, serverless)

#### **OpenAI**
- **Model:** gpt-4o (vision-capable)
- **Requires:** OPENAI_API_KEY environment variable
- **Cost:** Pay-per-token

#### **Hugging Face**
- **UI-TARS Model:** ByteDance-Seed/UI-TARS-1.5
- **Use Case:** Screenshot → UI action step conversion
- **Requires:** HF_TOKEN for gated access

### 3. Model Loading Strategy

**At Startup (main.py):**
```python
pipeline_service = PipelineService()
# ↓ Lazily loads on first request
detection_service._ensure_model_loaded()  # YOLO26
open_vocab_service._ensure_model_loaded()  # Grounding DINO (if enabled)

demo_vlm_service = VlmService()
# ↓ Connects to Ollama on first call

_copilot_llm = LLMCopilotService(...)
# ↓ Connects to LLM provider on first call

_copilot_screen = ScreenCapture(...)
# ↓ Ready to capture PC screen
```

**Lazy Loading:** Models downloaded on first use, cached in `~/.cache/huggingface/`

---

## Data Flow Architecture

### **Flow 1: Frame → Guidance (Real-time Loop)**

```
Mobile (Unity)
  │
  1. ARCameraCapture acquires latest camera frame
  2. IMUSensorStreamer captures device sensors (parallel)
  3. Encode frame to base64 JPEG
  │
  ├─→ WebSocketManager sends {"type": "frame", "image_data": ..., "imu_data": ...}
  │
Backend (Python/FastAPI)
  │
  4. Receive JSON on /stream WebSocket
  5. Extract image_data (base64) + imu_data
  6. ImuFusionService.update() → smooth motion state
  │
  7. pipeline_service.decode_frame(base64) → np.ndarray
  8. frame_differ.should_process() → check diff_score
  │
  ├─ Cache hit? → Send cached guidance (low diff)
  │
  ├─ Cache miss?
  │   │
  │   9. detection_service.detect(bgr_image) → YOLO26 → list[DetectionObject]
  │   │
  │   10. Check trigger conditions for Grounding DINO:
  │       - YOLO confidence < 0.55?
  │       - diff_score > 18.0?
  │       - IMU motion > 2.2?
  │       - >3s since last trigger?
  │   │
  │   ├─ Trigger? → open_vocab_service.detect(image_bytes, labels) → Grounding DINO
  │   │
  │   11. scene_fusion_service.build_scene() → merge detections
  │   12. reasoning_service.generate_guidance() → rule-based logic
  │       - If barbell/bench/dumbbell → posture focus
  │       - Else if person → alignment focus
  │       - Else → VLM fallback (if enabled)
  │   │
  │   13. Enrich debug info (metrics, detections, errors)
  │   14. Send GuidancePayload as JSON
  │
  ├─→ WebSocketManager receives response on main thread
  │
Mobile (Unity)
  │
  15. AROverlayManager parses GuidanceMessage
  16. Render overlay (arrow or highlight) at location_3d
  17. Display instruction_text + confidence
  18. Update step counter (current_step/total_steps)
  │
  └─→ Repeat every ~1-2s or on manual "Snap"
```

**Latency Budget (example):**
- Frame capture: ~50 ms
- Frame diff: ~20 ms
- YOLO26: ~100 ms
- Scene fusion: ~10 ms
- Reasoning: ~50 ms
- Serialize + send: ~30 ms
- Network + receive: ~100-300 ms
- **Total:** 360-650 ms (real-time, acceptable for AR)

---

### **Flow 2: Snapshot → Deep Analysis**

```
Mobile (Unity)
  │
  1. User taps "Ask" button
  2. Capture current frame
  │
  ├─→ WebSocketManager sends {"type": "snapshot", "image_data": ...}
  │
Backend (Python/FastAPI)
  │
  3. Receive on /stream WebSocket
  4. Decode frame → bgr_image
  5. Run YOLO (quick) → persisted for context
  6. demo_vlm_service.analyze_snapshot(image_bytes, yolo_detections)
     ├─→ Connect to Ollama
     ├─→ Send gym_coach.txt prompt + base64 image
     ├─→ Parse VLM response (JSON recovery if truncated)
     └─→ Return detailed scene analysis
  │
  7. Send response with deeper insight
  │
Mobile (Unity)
  │
  8. AROverlayManager receives richer guidance
  9. Display detailed instruction + confidence
  │
  └─→ Persist scene state for next step progression
```

**Key Difference:** Snapshot uses full VLM power (no shortcuts), slower but more detailed.

---

### **Flow 3: UI Assistance (Half 2)**

```
Mobile (Unity) — CopilotAR scene
  │
  1. User types query: "How do I insert a table in Word?"
  2. Select target app: "Word"
  │
  ├─→ CopilotWebSocketClient sends {"type": "query", "query": "...", "app": "Word"}
  │
Backend (Python/FastAPI)
  │
  3. Receive on /copilot WebSocket endpoint
  4. llm_service.generate_steps(query, app_name)
     ├─→ Connect to Ollama/OpenAI
     ├─→ System prompt: Convert natural language → UI steps
     ├─→ Return JSON: [{"action": "click", "target": "Insert", ...}, ...]
     │
  5. For each step:
     ├─→ ui_detector.connect(app_name) → pywinauto UIA Automation
     ├─→ ui_detector.get_element_rect(target) → pixel coords (x, y, width, height)
     ├─→ Capture PC screen (full resolution)
     │
  6. screen_capture.crop_to_bounds(x, y, width, height) → small JPEG
  7. Send {"type": "copilot_steps", "steps": [...resolved...], "screen_frame": base64_jpeg}
  │
Mobile (Unity)
  │
  8. CopilotStepController receives steps
  9. VirtualScreenManager.UpdateScreen(frame_jpeg) → display PC screen as AR quad
  10. CopilotOverlayManager renders arrows at pixel coords → world-space 3D
  11. CopilotUI displays step instructions
  │
  12. User taps "Next" → backend sends next step + screen region
  13. Arrows guide user through each click/type action
  │
  └─→ Continue until task complete
```

---

## Key Features Implemented

### **Half 1: Live Scene Assistance** ✅

#### 1. **Multi-Modal Scene Understanding**
- YOLO26 fast detection (real-time)
- Grounding DINO open-vocabulary (on-demand)
- VLM snapshot analysis (deep dive)
- Rule-based reasoning fallback

#### 2. **Persona System**
- Gym Trainer: Focus on posture, form, safety
- Chef: Focus on ingredients, techniques, timing
- Physiotherapist: Focus on mobility, alignment, rehabilitation
- Persona switched via config or API
- Custom prompts loaded from `prompts/persona_*.txt`

#### 3. **Motion-Aware Triggering**
- IMU sensor fusion (accelerometer + gyroscope smoothing)
- High-motion detection → triggers Grounding DINO for precision
- Frame diffing → only process on scene change

#### 4. **AR Overlays**
- World-anchored step card (distance: 1.1-2.2m)
- Object-linked arrows (direction hint)
- Highlight overlays (focus hint)
- Smoothed transitions (avoid jitter)
- Confidence-gated rendering

#### 5. **Step Progression**
- Manual next/previous navigation
- Step completion tracking
- Auto-advance option (on verification)
- Reset capability

#### 6. **Device-Aware Responses**
- Normalized 3D coordinates (device-agnostic)
- Adaptive overlay opacity
- Terrain-aware anchor placement

---

### **Half 2: Software UI Assistance** 🚀 (In Progress)

#### 1. **Query → Steps Conversion**
- Natural language → JSON action list
- Supports: Click, Type, Scroll, Double-click, Right-click
- Multiple LLM providers (Ollama, OpenAI, Hugging Face)

#### 2. **Windows UI Automation**
- pywinauto + UIA Automation API
- Resolve UI element labels to pixel coordinates
- Handles: Buttons, Menus, Text fields, Tabs, Combo boxes

#### 3. **Live Screen Streaming**
- PC screen capture → mobile
- JPEG compression (configurable quality)
- Regions-of-interest (crop around active element)

#### 4. **AR Guidance Overlays**
- Virtual screen quad in AR space
- Pixel coords → 3D world arrows/highlights
- Step-by-step visual guidance

#### 5. **Multi-App Support**
- Word, Excel, Notepad, PowerPoint, Chrome
- App detection via pywinauto window title
- Context-specific step generation

---

## Implementation Patterns

### **1. Service Layer Pattern**
Each service is independently instantiable, with clear input/output contracts:
```python
# Detection service
detections = await detection_service.detect(bgr_image)

# Scene fusion
scene = scene_fusion_service.build_scene(detections, task_context=...)

# Reasoning
guidance = await reasoning_service.generate_guidance(scene, image_bytes)
```

**Benefits:**
- Testable in isolation
- Replaceable implementations
- Async support for blocking operations

### **2. Async/Sync Boundary**
Heavy compute (model inference) runs in thread pool to prevent FastAPI event loop blocking:
```python
async def detect(self, bgr_image):
    return await asyncio.to_thread(self._detect_sync, bgr_image)
```

### **3. Configuration Management**
All runtime parameters via environment variables (12-factor app principle):
```bash
YOLO_CONFIDENCE_THRESHOLD=0.5 \
OLLAMA_MODEL=qwen3-vl:4b \
GROUNDING_DINO_ENABLED=false \
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### **4. Error Recovery**
- Fallback logic when models unavailable
- JSON repair (truncation recovery in VLM responses)
- Timeout with graceful degradation

### **5. Lazy Initialization**
Models not loaded until first use:
```python
def _ensure_model_loaded(self):
    if self._model is not None:
        return
    # Load on first request only
```

### **6. State Machine for Steps**
```
Idle → Scanned → Planning → Step Active → Step Done → [Replan or Complete]
```
Supports navigation: next, previous, complete, reset.

### **7. Thread-Safe UI Updates (Unity)**
WebSocket receives on background thread, main thread dispatcher queues updates:
```csharp
MainThreadDispatcher.Enqueue(() => {
    overlayManager.UpdateOverlay(position, text);
});
```

### **8. WebSocket Reconnection**
Exponential backoff with jitter:
```csharp
private async Task ScheduleReconnectAsync()
{
    await Task.Delay(reconnectDelaySeconds * 1000);
    await ConnectAsync();  // retry
}
```

---

## Integration Points

### **1. Mobile → Backend Communication**

**Protocol:** WebSocket (JSON over ws://)  
**Endpoints:**
- `/stream` (Half 1, guidance loop)
- `/copilot` (Half 2, UI automation)

**Data Encoding:**
- Images: Base64-encoded JPEG
- IMU: float arrays (accelerometer, gyroscope, attitude)
- Text: JSON strings

**Error Handling:**
- Validation on both sides (Pydantic schemas)
- Timeout fallbacks (15s default for AI)
- Retry logic with backoff

### **2. Backend → Model Inference**

**Local Models (Ollama):**
- HTTP POST to Ollama API (`http://localhost:11434/api/chat`)
- Model auto-download on first use
- GPU acceleration if available

**Remote Models (OpenAI):**
- HTTPS POST to OpenAI API
- Requires API key (env var)
- Streaming responses (batched)

**HuggingFace:**
- Inference Client API
- Fine-tuned models (UI-TARS)
- Requires HF token (env var)

### **3. Backend → Windows UI (Half 2)**

**Technology:** pywinauto (UIA Automation on Windows)  
**Workflow:**
1. LLM generates action steps (JSON)
2. UI Detector connects to Windows app by title
3. Resolves each UI element by label + control type
4. Returns pixel coordinates
5. Screen captured at element location

**Limitations:**
- Windows-only
- Requires UAC permissions (sometimes)
- Element detection by exact label match

### **4. Model Storage & Caching**

**YOLO26 (local file):**
```
backend/yolo26n.onnx (6 MB)
```

**Grounding DINO (HF cache):**
```
~/.cache/huggingface/hub/models--IDEA-Research--grounding-dino-tiny/
```

**Ollama models (Ollama storage):**
```
~/.ollama/models/
```

**Persistence:** Models cached on first download, reused on subsequent runs

---

## Deployment Architecture

### **Current Setup (Development)**

```
Mobile Device (Android)
  └─→ ws://192.168.0.102:8000/stream
        (Hard-coded IP, configurable in WebSocketManager)

Backend Server (Windows PC)
  ├─→ FastAPI + uvicorn (http://0.0.0.0:8000)
  ├─→ Ollama service (http://localhost:11434)
  ├─→ OpenAI API (https://api.openai.com, if configured)
  └─→ Hugging Face API (https://api-inference.huggingface.co, if configured)

Models (cached locally on backend):
  ├─→ yolo26n.onnx (6 MB)
  ├─→ Grounding DINO weights (~1 GB, downloaded on demand)
  └─→ Ollama models (downloaded via `ollama pull`)
```

### **Production Considerations**

1. **Networking:**
   - Use domain names instead of hardcoded IPs
   - SSL/TLS for WebSocket (wss://)
   - Reverse proxy (nginx) for load balancing

2. **Model Serving:**
   - Multi-GPU inference (vLLM for LLMs)
   - Model caching layer (Redis for intermediate results)
   - Async model queue (for high concurrency)

3. **Monitoring:**
   - Prometheus metrics on /metrics
   - Structured logging (JSON)
   - Model latency tracking

4. **Scaling:**
   - Containerize backend (Docker)
   - Kubernetes orchestration
   - Model sharding (split across GPUs)

---

## Summary: Key Takeaways

| Aspect | Details |
|--------|---------|
| **Architecture** | Modular service layer + async FastAPI + WebSocket protocol |
| **ML Pipeline** | YOLO26 (fast) + Grounding DINO (triggered) + VLM (fallback) |
| **Mobile** | Unity AR Foundation, real-time camera capture, IMU streaming |
| **Models** | 3 CV models (YOLO, Grounding DINO, FastSAM) + external LLMs |
| **Personas** | Gym Trainer, Chef, Physiotherapist (configurable prompts) |
| **AR** | World-space overlays, step cards, confidence-gated rendering |
| **Half 1** | Live scene assistance with step guidance (COMPLETE) |
| **Half 2** | Software UI guidance via pywinauto + LLM (IN PROGRESS) |
| **Config** | Environment-driven, 40+ tunable parameters |
| **Error Recovery** | Graceful fallbacks, JSON repair, timeout handling |
| **Deployment** | Local dev setup, production containerization path clear |

---

## Next Steps / Recommended Reading

1. **Backend Setup:** Check `backend/BACKEND_IMPLEMENTATION_GUIDE.md` and `backend/VLLM_SETUP.md` for Ollama/VLLM installation
2. **Frontend Development:** Refer to `AR_LIVE_GUIDANCE_PHASE1_PLAN.md` for AR overlay patterns
3. **Model Optimization:** `backend/export_yolo26_to_onnx.py` for model export workflows
4. **Testing:** Run individual services in isolation before integration
5. **Deployment:** Reference `FINAL_PROJECT_ROADMAP.md` for phased rollout strategy

---

*Generated: 2026-05-13*  
*Analysis covers: Python backend (17 files), C# Unity (14 files), 40+ config parameters, 5 ML models, 2 deployment modes*
