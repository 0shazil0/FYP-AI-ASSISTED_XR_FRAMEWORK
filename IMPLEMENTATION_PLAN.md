# NeuroGuide XR — Final Implementation Plan

## AI-Powered Extended Reality Assistive Guidance System

**Group 19 | FYP 2026**
**Date:** March 1, 2026

---

## Critical Analysis of Existing Resources

### What Already Exists

| Asset | Status | Notes |
|---|---|---|
| Unity 6 Project (`My project (1)`) | ✅ Working | ARFoundation 6.3.3, ARCore, XRI 3.3.1, URP, MCP server connected |
| Android Build | ✅ Running | Default Hello AR template on device |
| FastAPI Backend (`backend/main.py`) | ⚠️ Scaffold only | WebSocket endpoint exists, returns mock data — no AI integration |
| UnityClient Scripts | ⚠️ Separate | `WebSocketManager`, `ARCameraCapture`, `AttentionGate`, `AROverlayManager` exist in `/UnityClient/` but are **NOT** integrated into the main project |
| MCP Server (Unity) | ✅ Connected | `com.ivanmurzak.unity.mcp` v0.51.3 — Copilot can interact with Unity scene |
| AI/Vision Pipeline | ❌ Missing | No VLM, no object detection, no reasoning engine |
| AR Overlays / Prefabs | ❌ Missing | No arrow, ghost-hand, or highlight prefabs created |

### Critical Issues in Previous Plans

| Issue | Problem | Resolution in This Plan |
|---|---|---|
| **4 use cases simultaneously** | Gym + Cooking + Elderly + Disaster is extreme scope creep for an FYP | **Focus on 1 primary (Gym Coach) + 1 secondary (Cooking Assistant)** — others become stretch goals |
| **Local vLLM / edge inference** | Requires NVIDIA GPU server, complex setup, fragile | **Use cloud VLM API (Google Gemini 1.5 Flash)** — cheapest, fastest multimodal model. Fallback: GPT-4o mini |
| **Grounding DINO + SAM 2 pipeline** | Over-engineered for an FYP; massive setup overhead | **Let the VLM return bounding box coordinates directly** (Gemini and GPT-4o support this natively). Add YOLO only if needed for speed |
| **Immersal SDK / Niantic Lightship** | Extra SDKs add complexity with minimal gain for phone AR | **Use ARFoundation's built-in plane detection + raycasting** — already working in project |
| **Disconnected codebases** | `UnityClient/` scripts are separate from `My project (1)/` | **Merge scripts into main project** in Phase 1 |
| **No incremental testing** | Previous plans jump to complex systems without validation | **Each phase ends with a testable deliverable** |

---

## Final Architecture Decision: Pragmatic Hybrid

```
┌──────────────────────────────────────────────────────────────┐
│                    ANDROID PHONE (AR Client)                 │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ AR Camera   │→ │ Attention    │→ │ WebSocket          │──┼──→ To Backend
│  │ (ARFounda-  │  │ Gate (IMU    │  │ Manager            │  │
│  │  tion 6.3)  │  │ threshold)   │  │ (send frame)       │  │
│  └─────────────┘  └──────────────┘  └────────────────────┘  │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ AR Overlay Manager                                      │ │
│  │ • Receives JSON guidance from backend                   │ │
│  │ • Raycasts 2D coords → 3D world position               │ │
│  │ • Instantiates overlays (arrows, highlights, text)      │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌──────────────────────────┐  ┌──────────────────────────┐ │
│  │ Voice Input Manager      │  │ UI Panel (instructions,  │ │
│  │ (mic → speech-to-text)   │  │  status, task progress)  │ │
│  └──────────────────────────┘  └──────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                          │ WebSocket (Wi-Fi)
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                 PYTHON BACKEND (PC / Laptop)                 │
│                                                              │
│  ┌─────────────┐  ┌──────────────────────────────────────┐  │
│  │ FastAPI      │→ │ Vision-Language Model (VLM) Client   │  │
│  │ WebSocket    │  │ • Google Gemini 1.5 Flash API        │  │
│  │ Server       │  │ • System prompt per use-case         │  │
│  └─────────────┘  │ • Returns structured JSON             │  │
│                    └──────────────────────────────────────┘  │
│                                                              │
│  ┌─────────────────────────┐  ┌───────────────────────────┐ │
│  │ Task State Manager      │  │ Difference Checker         │ │
│  │ (SQLite: steps, DAG)    │  │ (skip duplicate frames)    │ │
│  └─────────────────────────┘  └───────────────────────────┘ │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Optional: YOLOv8 local detection (speed optimization)   │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## Technology Stack (Finalized)

### Backend (Python)
| Component | Technology | Justification |
|---|---|---|
| Web Framework | FastAPI + WebSockets | Already scaffolded; async, fast |
| VLM / AI | Google Gemini 1.5 Flash API | Cheapest multimodal model; accepts images; returns JSON. Free tier: 15 RPM |
| Fallback VLM | OpenAI GPT-4o mini | Backup if Gemini quota hit |
| Object Detection | YOLOv8 (ultralytics) | Optional local speed layer — detect objects in <50ms |
| Task State | SQLite | Lightweight DAG-based step tracking |
| Image Processing | OpenCV + Pillow | Frame differencing, preprocessing |

### AR Client (Unity)
| Component | Technology | Justification |
|---|---|---|
| Engine | Unity 6 (6000.3.10f1) | Already installed and building |
| XR SDK | AR Foundation 6.3.3 + ARCore | Already configured |
| Interaction | XR Interaction Toolkit 3.3.1 | Already imported with samples |
| Networking | System.Net.WebSockets (C#) | Already implemented in UnityClient scripts |
| JSON | Newtonsoft.Json | Standard; needs package import |
| Voice | Unity Microphone API + backend STT | Simple mic capture, server-side processing |
| UI | Unity UI Toolkit / Canvas | Floating world-space panels |

---

## Phased Implementation Roadmap

---

### PHASE 0: Project Consolidation (Week 1)
**Goal:** Merge all existing code into one working project. Establish end-to-end "ping" between phone and backend.

| # | Task | Details |
|---|---|---|
| 0.1 | **Merge UnityClient scripts into main project** | Copy `WebSocketManager.cs`, `ARCameraCapture.cs`, `AttentionGate.cs`, `AROverlayManager.cs` into `My project (1)/Assets/Scripts/` |
| 0.2 | **Add MainThreadDispatcher** | Included in `WebSocketManager.cs` — ensure it's attached to a GameObject |
| 0.3 | **Install Newtonsoft.Json package** | Package Manager → Add by git URL: `com.unity.nuget.newtonsoft-json` |
| 0.4 | **Create NeuroGuideManager GameObject** | Empty GO in scene with `WebSocketManager` + `AROverlayManager` scripts |
| 0.5 | **Attach camera scripts** | `ARCameraCapture` + `AttentionGate` on the AR Camera |
| 0.6 | **Configure WebSocket IP** | Set to your PC's local IP (e.g., `ws://192.168.x.x:8000/stream`) |
| 0.7 | **Test ping-pong** | Build to Android → hold phone still → verify Python terminal shows `Received message of type: frame` |
| 0.8 | **Create placeholder prefabs** | Simple sphere (red) for arrow, cube (yellow) for highlight — assign in `AROverlayManager` inspector |

**Deliverable:** Phone sends frames to backend, backend returns mock JSON, phone renders a red sphere 1m ahead.

---

### PHASE 1: AI Vision Integration (Weeks 2–3)
**Goal:** Backend receives a real camera frame, sends it to Gemini, returns structured guidance.

| # | Task | Details |
|---|---|---|
| 1.1 | **Set up Gemini API** AIzaSyDgVVwKLIy5XyPUmd3-pagJUpDOcVikfgE | Get API key from Google AI Studio (`aistudio.google.com`). Install `google-generativeai` Python package |
| 1.2 | **Implement VLM service** | Create `services/vlm_service.py` — accepts base64 image, sends to Gemini with system prompt, returns parsed JSON |
| 1.3 | **Design system prompt (Gym Coach)** | Prompt instructs the model to: identify gym equipment, assess user posture, return JSON `{task, instruction_text, visual_type, objects_detected, bounding_boxes}` |
| 1.4 | **Implement frame differencing** | Create `services/frame_differ.py` — compare incoming frame to last processed frame using pixel variance. Skip if difference < 15% to save API calls |
| 1.5 | **Wire VLM into WebSocket handler** | Replace mock response in `main.py` with actual Gemini call. Decode base64 → PIL Image → Gemini API → JSON response |
| 1.6 | **Add error handling & timeout** | Gemini call timeout (10s), graceful fallback if API fails |
| 1.7 | **Test with real camera** | Point phone at gym equipment (or print pictures). Verify backend returns meaningful guidance text |

**Backend JSON response schema:**
```json
{
  "type": "guidance",
  "task": "bench_press",
  "instruction_text": "Lower the barbell slowly to your chest, keeping elbows at 45 degrees",
  "visual_type": "arrow",
  "objects_detected": ["dumbbell", "barbell", "bench"],
  "bounding_boxes": [
    {"label": "barbell", "x": 0.35, "y": 0.20, "w": 0.30, "h": 0.10}
  ],
  "location_3d": [0.0, 0.2, 1.5],
  "step_number": 2,
  "total_steps": 5
}
```

**Deliverable:** Phone captures scene → Gemini analyzes it → returns real exercise guidance with object identification.

---

### PHASE 2: AR Visualization & Spatial Grounding (Weeks 4–5)
**Goal:** Render meaningful AR overlays anchored to real-world objects.

| # | Task | Details |
|---|---|---|
| 2.1 | **Implement 2D-to-3D raycasting** | When backend returns bounding box center `(x, y)` in normalized coords, fire a ray from camera through that screen point. Where it hits an AR plane, place the overlay anchor |
| 2.2 | **Create Arrow prefab** | 3D arrow model (can use ProBuilder or import free asset) with pulsing animation (scale ping-pong). Unlit shader for visibility |
| 2.3 | **Create Highlight prefab** | Semi-transparent colored quad/ring that hovers over target object. Particle effect border |
| 2.4 | **Create floating text panel** | World-space Canvas with `instruction_text` display. Billboard shader (always faces camera) |
| 2.5 | **Implement overlay lifecycle** | Overlays fade in, persist for N seconds or until next guidance, then fade out. Prevent overlay stacking |
| 2.6 | **Implement step progress UI** | Screen-space UI showing "Step 2 of 5" + current instruction text at bottom of screen |
| 2.7 | **Add AR anchor persistence** | Use `ARAnchorManager` to pin overlays to real-world positions so they don't drift |
| 2.8 | **Test spatial accuracy** | Place arrows on detected objects. Measure drift over 30 seconds. Target: < 5cm drift |

**Deliverable:** When Gemini identifies "barbell at (0.35, 0.20)", an arrow appears at the barbell's real-world position with instruction text floating beside it.

---

### PHASE 3: Task State & Multi-Step Guidance (Weeks 6–7)
**Goal:** System tracks exercise progress through a sequence of steps, not just single-frame analysis.

| # | Task | Details |
|---|---|---|
| 3.1 | **Design task DAG schema** | SQLite tables: `tasks(id, name, total_steps)`, `steps(id, task_id, order, instruction, visual_type, completion_criteria)`, `session(id, task_id, current_step, status)` |
| 3.2 | **Create task definitions** | Define 3-4 gym exercises as JSON task files: bench press (5 steps), squat (6 steps), deadlift (5 steps), dumbbell curl (4 steps) |
| 3.3 | **Implement TaskStateManager** | Python class that loads task DAG, tracks current step, advances on VLM confirmation |
| 3.4 | **VLM step verification** | Enhanced prompt: "Given the user is on step 2 of bench_press, analyze if they have completed this step. Return `{step_completed: true/false, feedback: '...'}` " |
| 3.5 | **Implement session continuity** | Backend maintains per-client session. Phone reconnection resumes from last step |
| 3.6 | **Unity: task selection UI** | Screen-space menu to select exercise (bench press, squat, etc.) before starting guidance |
| 3.7 | **Unity: step transition animations** | When step completes: green checkmark animation → fade → next step instruction |
| 3.8 | **Audio feedback** | Use Unity `AudioSource` for: step complete chime, error buzz, verbal instruction (TTS via backend) |

**Deliverable:** User selects "Bench Press" → system guides through 5 steps → checks completion visually → advances automatically with feedback.

---

### PHASE 4: Voice Interaction (Week 8)
**Goal:** Hands-free control via voice commands.

| # | Task | Details |
|---|---|---|
| 4.1 | **Implement mic capture in Unity** | Use `Microphone.Start()` to record audio clip, encode to WAV bytes |
| 4.2 | **Send voice to backend** | New message type `{"type": "voice", "audio_data": "<base64 wav>"}` |
| 4.3 | **Backend STT** | Use Google Cloud Speech-to-Text or Whisper API to transcribe |
| 4.4 | **Intent parsing** | Feed transcribed text + current task state to Gemini: "User said: 'What do I do next?' Current step: 3. Respond with guidance." |
| 4.5 | **Voice commands** | Support: "next step", "repeat", "what am I doing wrong?", "start over", "help" |
| 4.6 | **Backend TTS response** | Generate speech audio for instruction_text using Google TTS. Send as base64 audio in response |
| 4.7 | **Unity audio playback** | Decode and play TTS audio through `AudioSource` |

**Deliverable:** User says "What do I do next?" → system responds with voice + AR overlay showing the next step.

---

### PHASE 5: Second Use Case — Cooking Assistant (Weeks 9–10)
**Goal:** Prove system generality by adding a second domain with minimal code changes.

| # | Task | Details |
|---|---|---|
| 5.1 | **Create cooking system prompts** | New prompt template: "You are a cooking assistant. Identify kitchen tools and ingredients. Return step-by-step recipe guidance..." |
| 5.2 | **Define cooking task DAGs** | 2-3 simple recipes as step sequences (e.g., making pasta, preparing salad) |
| 5.3 | **Create cooking-specific prefabs** | Timer widget (world-space countdown anchored to pot), ingredient highlight (green = ready, red = missing) |
| 5.4 | **Implement use-case selector** | Main menu in Unity: "Gym Coach" / "Cooking Assistant" → loads appropriate prompts and task library |
| 5.5 | **Backend prompt routing** | Route to correct system prompt based on `use_case` field from Unity |
| 5.6 | **Test with real kitchen items** | Validate on actual kitchen scene |

**Deliverable:** Same system, different domain. User selects "Cooking" → points at kitchen → gets recipe guidance.

---

### PHASE 6: Optimization & Polish (Week 11)
**Goal:** Production-quality performance and UX.

| # | Task | Details |
|---|---|---|
| 6.1 | **Latency optimization** | Measure end-to-end latency (frame capture → overlay render). Target: < 2 seconds. Optimize JPEG quality, frame size |
| 6.2 | **Add YOLOv8 fast detection** | Optional: run YOLOv8 on backend for instant bounding boxes (< 50ms) while waiting for Gemini response. Show "detecting..." overlay immediately |
| 6.3 | **Implement Kalman filter** | Smooth overlay positions to prevent jitter when tracking data updates |
| 6.4 | **Context window management** | Limit Gemini context to current step + last 2 frames to prevent context poisoning |
| 6.5 | **Offline graceful degradation** | If backend unreachable, show cached last instruction + "Reconnecting..." UI |
| 6.6 | **UI/UX polish** | Consistent color scheme, animations, loading states, error messages |
| 6.7 | **Battery & thermal management** | Reduce frame capture rate when idle. Monitor device temperature |

**Deliverable:** Smooth, responsive AR experience with < 2s guidance latency.

---

### PHASE 7: Evaluation & Thesis (Weeks 12–14)
**Goal:** Scientifically validate the system and write the thesis.

| # | Task | Details |
|---|---|---|
| 7.1 | **Technical benchmarks** | Measure: guidance latency, tracking drift (cm over 60s), frame processing rate, API token usage |
| 7.2 | **User study design** | Recruit 10-15 participants. Two conditions: (A) paper instructions vs (B) NeuroGuide XR. Tasks: complete a gym exercise sequence |
| 7.3 | **Dexterity test** | Modified Box & Block Test or task completion time comparison |
| 7.4 | **Cognitive load survey** | NASA-TLX questionnaire after each condition |
| 7.5 | **System Usability Scale (SUS)** | Standard 10-question usability survey |
| 7.6 | **Record demo video** | 3-5 minute video showing both use cases end-to-end |
| 7.7 | **Write thesis** | Introduction, Literature Review, Methodology, Implementation, Results, Conclusion |
| 7.8 | **Prepare defense presentation** | Slides + live demo |

**Deliverable:** Complete thesis with quantitative evaluation proving the system reduces task completion time and cognitive load vs. traditional instructions.

---

## Milestone Summary

| Phase | Duration | Key Milestone | Risk Level |
|---|---|---|---|
| **Phase 0** | Week 1 | Phone ↔ Backend ping working | 🟢 Low |
| **Phase 1** | Weeks 2–3 | Gemini returns real guidance from camera | 🟡 Medium (API setup) |
| **Phase 2** | Weeks 4–5 | AR overlays anchored to real objects | 🟡 Medium (raycasting accuracy) |
| **Phase 3** | Weeks 6–7 | Multi-step guided exercise flow | 🟡 Medium |
| **Phase 4** | Week 8 | Voice commands working | 🟢 Low |
| **Phase 5** | Weeks 9–10 | Second use case (Cooking) running | 🟢 Low (reuses existing infra) |
| **Phase 6** | Week 11 | Optimized & polished | 🟡 Medium |
| **Phase 7** | Weeks 12–14 | Evaluation complete, thesis written | 🟢 Low |

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| Gemini API rate limits / cost | High | Use free tier (15 RPM). Implement frame differencing to skip redundant calls. Cache responses for identical scenes |
| AR overlay spatial accuracy | Medium | Use AR plane raycasting (proven in ARFoundation). Add anchor persistence. Accept 5cm tolerance |
| WebSocket disconnections | Medium | Implement auto-reconnect with exponential backoff. Cache last guidance on device |
| VLM hallucinating incorrect guidance | High | Constrain output via structured JSON schema. Validate bounding boxes are within image bounds. Safety whitelist for gym exercises |
| Device overheating during extended use | Medium | Reduce camera capture to 0.5 FPS during attention-gated mode. Auto-pause if thermal throttling detected |
| Scope creep into 4 use cases | High | **Hard limit: Gym (primary) + Cooking (secondary). Elderly/Disaster are stretch goals only** |

---

## File Structure (Target End State)

```
d:\FYP Assisted AI with XR\
├── backend/
│   ├── main.py                      # FastAPI + WebSocket server
│   ├── requirements.txt
│   ├── config.py                    # API keys, constants
│   ├── services/
│   │   ├── vlm_service.py           # Gemini API integration
│   │   ├── frame_differ.py          # Frame change detection
│   │   ├── task_state_manager.py    # SQLite task DAG manager
│   │   ├── speech_service.py        # STT + TTS
│   │   └── yolo_service.py          # Optional YOLOv8 detection
│   ├── prompts/
│   │   ├── gym_coach.txt            # System prompt for gym use case
│   │   └── cooking_assistant.txt    # System prompt for cooking use case
│   ├── tasks/
│   │   ├── bench_press.json         # Task step definitions
│   │   ├── squat.json
│   │   └── pasta_recipe.json
│   └── neuroguide.db               # SQLite database (auto-created)
│
├── My project (1)/                  # Unity 6 AR Project
│   ├── Assets/
│   │   ├── Scripts/
│   │   │   ├── Networking/
│   │   │   │   ├── WebSocketManager.cs
│   │   │   │   └── MainThreadDispatcher.cs
│   │   │   ├── AR/
│   │   │   │   ├── ARCameraCapture.cs
│   │   │   │   ├── AROverlayManager.cs
│   │   │   │   ├── AttentionGate.cs
│   │   │   │   └── SpatialRaycaster.cs
│   │   │   ├── UI/
│   │   │   │   ├── TaskSelectionUI.cs
│   │   │   │   ├── StepProgressUI.cs
│   │   │   │   └── GuidancePanel.cs
│   │   │   ├── Voice/
│   │   │   │   └── VoiceInputManager.cs
│   │   │   └── Core/
│   │   │       └── NeuroGuideController.cs
│   │   ├── Prefabs/
│   │   │   ├── ArrowOverlay.prefab
│   │   │   ├── HighlightOverlay.prefab
│   │   │   ├── GuidancePanel.prefab
│   │   │   └── TimerWidget.prefab
│   │   ├── Materials/
│   │   ├── Scenes/
│   │   │   └── SampleScene.unity
│   │   └── ...existing template assets...
│   └── ...
│
├── MyResources/                     # Research & documentation
└── IMPLEMENTATION_PLAN.md           # This file
```

---

## Immediate Next Step

**Phase 0, Task 0.1:** Merge the four UnityClient scripts into `My project (1)/Assets/Scripts/` and verify the project compiles.

> When you're ready, say **"Let's start Phase 0"** and we will begin building step by step.
