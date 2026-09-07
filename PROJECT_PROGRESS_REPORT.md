# NeuroGuide XR — Full Project Progress Report

**Project:** NeuroGuide XR  
**Scope:** Final Year Project progress summary and technical report  
**Updated:** May 13, 2026  
**Current Status:** Active development, with the live scene guidance pipeline working and the software UI copilot path in progress

---

## 1. Executive Summary

NeuroGuide XR is an AI-assisted extended reality guidance system built around two complementary experiences:

1. Live scene assistance for real-world tasks such as gym and cooking guidance.
2. Software UI assistance for guiding a user through Windows application steps using a copilot-style workflow.

The project evolved from planning documents and a Unity prototype into a modular Python + Unity system with a FastAPI backend, WebSocket transport, AR client rendering, and a layered AI pipeline. The implementation emphasizes practical deliverables, lower-risk model choices, and a path that preserves the working scene-guidance flow while adding the newer copilot mode.

Key progress so far:

- Built a backend that serves scene guidance over WebSocket.
- Defined configuration, schemas, and a service-based AI pipeline.
- Integrated object detection, scene fusion, motion sensing, reasoning, and VLM support.
- Extended the Unity project with AR, networking, UI, and copilot-related scripts.
- Created backup archives for the backend and a restoreable Unity project subset.
- Produced analysis and implementation documents to track the project architecture and roadmap.

---

## 2. Technology Stack

### Backend

- Python 3
- FastAPI
- Uvicorn
- WebSocket transport
- OpenCV / Pillow for image handling
- Pydantic for structured schemas
- ONNX Runtime / model wrappers for detection and inference

### Unity Client

- Unity 2022.3 LTS / Unity 6 project assets already present in the workspace
- C# scripts for networking, AR overlays, camera capture, IMU streaming, and copilot UI
- AR Foundation / ARCore integration
- UI and world-space rendering for guidance overlays

### AI / ML

- YOLO26 Nano for lightweight object detection
- Grounding DINO for open-vocabulary detection when triggered
- VLM support through Ollama, OpenAI, and Hugging Face endpoints
- LLM-based instruction generation for copilot and reasoning workflows
- IMU fusion and frame differencing for smarter trigger control

### Project Artifacts

- Implementation plans and roadmap documents
- Generated progress analysis report
- Backup archives for backend and Unity restore files

---

## 3. What Was Built

### 3.1 Backend Core

The backend is centered on [backend/main.py](backend/main.py), which sets up the FastAPI app, config-driven model initialization, and the WebSocket entry points for live guidance.

Major backend files now present:

- [backend/main.py](backend/main.py)
- [backend/config.py](backend/config.py)
- [backend/schemas.py](backend/schemas.py)
- [backend/requirements.txt](backend/requirements.txt)
- [backend/services/](backend/services)

The backend service layer is split into focused modules rather than one large monolith. The current service inventory includes:

- [backend/services/frame_differ.py](backend/services/frame_differ.py)
- [backend/services/detection_service.py](backend/services/detection_service.py)
- [backend/services/open_vocab_service.py](backend/services/open_vocab_service.py)
- [backend/services/vlm_service.py](backend/services/vlm_service.py)
- [backend/services/llm_service.py](backend/services/llm_service.py)
- [backend/services/reasoning_service.py](backend/services/reasoning_service.py)
- [backend/services/scene_fusion_service.py](backend/services/scene_fusion_service.py)
- [backend/services/imu_fusion_service.py](backend/services/imu_fusion_service.py)
- [backend/services/pipeline_service.py](backend/services/pipeline_service.py)
- [backend/services/ui_detector.py](backend/services/ui_detector.py)
- [backend/services/screen_capture.py](backend/services/screen_capture.py)
- [backend/services/workout_service.py](backend/services/workout_service.py)
- [backend/services/roboflow_detection_service.py](backend/services/roboflow_detection_service.py)

### 3.2 Unity Client

The Unity project now contains a more complete script structure for both the live guidance and copilot flows.

Current script inventory under [My project (1)/Assets/Scripts](My%20project%20(1)/Assets/Scripts):

- [My project (1)/Assets/Scripts/Core/NeuroGuideController.cs](My%20project%20(1)/Assets/Scripts/Core/NeuroGuideController.cs)
- [My project (1)/Assets/Scripts/Networking/WebSocketManager.cs](My%20project%20(1)/Assets/Scripts/Networking/WebSocketManager.cs)
- [My project (1)/Assets/Scripts/Networking/MainThreadDispatcher.cs](My%20project%20(1)/Assets/Scripts/Networking/MainThreadDispatcher.cs)
- [My project (1)/Assets/Scripts/AR/ARCameraCapture.cs](My%20project%20(1)/Assets/Scripts/AR/ARCameraCapture.cs)
- [My project (1)/Assets/Scripts/AR/AROverlayManager.cs](My%20project%20(1)/Assets/Scripts/AR/AROverlayManager.cs)
- [My project (1)/Assets/Scripts/AR/AttentionGate.cs](My%20project%20(1)/Assets/Scripts/AR/AttentionGate.cs)
- [My project (1)/Assets/Scripts/AR/IMUSensorStreamer.cs](My%20project%20(1)/Assets/Scripts/AR/IMUSensorStreamer.cs)
- [My project (1)/Assets/Scripts/UI/SnapDemoUI.cs](My%20project%20(1)/Assets/Scripts/UI/SnapDemoUI.cs)
- [My project (1)/Assets/Scripts/UI/ModeSelectUI.cs](My%20project%20(1)/Assets/Scripts/UI/ModeSelectUI.cs)
- [My project (1)/Assets/Scripts/UI/CopilotUI.cs](My%20project%20(1)/Assets/Scripts/UI/CopilotUI.cs)
- [My project (1)/Assets/Scripts/UI/CoachHUD.cs](My%20project%20(1)/Assets/Scripts/UI/CoachHUD.cs)
- [My project (1)/Assets/Scripts/UI/ExerciseGifPanel.cs](My%20project%20(1)/Assets/Scripts/UI/ExerciseGifPanel.cs)
- [My project (1)/Assets/Scripts/UI/WorldSpaceFollow.cs](My%20project%20(1)/Assets/Scripts/UI/WorldSpaceFollow.cs)
- [My project (1)/Assets/Scripts/Copilot/VirtualScreenManager.cs](My%20project%20(1)/Assets/Scripts/Copilot/VirtualScreenManager.cs)
- [My project (1)/Assets/Scripts/Copilot/CopilotWebSocketClient.cs](My%20project%20(1)/Assets/Scripts/Copilot/CopilotWebSocketClient.cs)
- [My project (1)/Assets/Scripts/Copilot/CopilotStepController.cs](My%20project%20(1)/Assets/Scripts/Copilot/CopilotStepController.cs)
- [My project (1)/Assets/Scripts/Copilot/CopilotOverlayManager.cs](My%20project%20(1)/Assets/Scripts/Copilot/CopilotOverlayManager.cs)

### 3.3 Documentation and Support Files

The project now includes planning and analysis documents that capture the work from early architectural decisions through later implementation details:

- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
- [fyp_implementation_plan.md](fyp_implementation_plan.md)
- [Implementation_plan_2.0.md](Implementation_plan_2.0.md)
- [FINAL_PROJECT_ROADMAP.md](FINAL_PROJECT_ROADMAP.md)
- [AR_LIVE_GUIDANCE_PHASE1_PLAN.md](AR_LIVE_GUIDANCE_PHASE1_PLAN.md)
- [CODEBASE_ANALYSIS.md](CODEBASE_ANALYSIS.md)

Backup artifacts were also created to support restoration:

- [backups/backend_backup_2026-05-12_171649.zip](backups/backend_backup_2026-05-12_171649.zip)
- [backups/unity_backup_2026-05-12_171649.zip](backups/unity_backup_2026-05-12_171649.zip)
- [backups/backup_manifest_2026-05-12_171649.txt](backups/backup_manifest_2026-05-12_171649.txt)

---

## 4. How the System Was Built

### 4.1 Architecture Strategy

The codebase was intentionally structured in modular layers so each responsibility could be developed and verified independently:

- Unity captures input and renders overlays.
- The backend handles transport, configuration, and inference orchestration.
- Individual services isolate frame differencing, detection, reasoning, scene fusion, and AI calls.
- Shared schemas define the contracts between client and server.

This approach reduced coupling and made it easier to preserve the working live guidance path while extending the system toward UI copilot behavior.

### 4.2 Backend Flow

The backend pipeline is organized around the following pattern:

1. Accept a frame or request over WebSocket.
2. Use frame differencing and motion cues to decide whether the scene should be processed.
3. Run object detection with the configured model.
4. Optionally trigger open-vocabulary detection or VLM fallback when the scene is uncertain.
5. Merge results into a scene state.
6. Generate a guidance payload or step update.
7. Return structured JSON to the Unity client.

### 4.3 Unity Flow

The Unity side follows a similar separation of duties:

1. Capture camera or screen-related input.
2. Send data through the WebSocket manager.
3. Marshal responses back to the main thread.
4. Render AR overlays, follow-up panels, or copilot visuals.
5. Update the UI based on step progression and backend state.

### 4.4 Data Contracts

The main data structures are defined in [backend/schemas.py](backend/schemas.py):

- `TaskContext`
- `DetectionObject`
- `SceneState`
- `GuidancePayload`
- `ImuSample`
- `StepControlPayload`

These schemas make the backend responses predictable and easier for the Unity client to consume.

---

## 5. Key Work Completed by Area

### 5.1 Live Scene Guidance Path

This is the working core of the project and the basis for the Phase 1 implementation.

Completed pieces include:

- Backend FastAPI server with WebSocket support.
- Frame-based guidance flow.
- YOLO-based detection layer.
- Scene fusion and reasoning services.
- Motion awareness through IMU fusion.
- Unity-side capture and overlay pipeline.

The result is a real-time assistance loop that can analyze a captured scene and send back structured guidance information.

### 5.2 Software UI Copilot Path

The project has also been extended toward a second use case that guides the user through Windows software interactions.

This path now has corresponding Unity-side and backend-side building blocks:

- UI-focused Unity scripts.
- Virtual screen and overlay management.
- Copilot-specific WebSocket client and step controller.
- Backend services for screen capture, UI detection, and LLM-driven step generation.

This work establishes the foundation for a dual-mode app without replacing the existing live guidance mode.

### 5.3 Backup and Recovery Work

To preserve the current project state, restoreable zip archives were created:

- Backend source and runtime assets backup.
- Unity project subset backup with source, settings, packages, solution files, and metadata.

This ensures the project can be recovered or transferred without carrying heavy generated folders like Library or Temp.

### 5.4 Analysis and Planning Work

In parallel with implementation, the project was documented through multiple planning artifacts that were refined into a clearer implementation story:

- Early implementation plans.
- Unified plan for both halves of the project.
- Roadmap documents.
- A comprehensive codebase analysis report.

That documentation tracks the transition from idea to working code and gives a paper trail for what was implemented, why it was implemented that way, and what remains.

---

## 6. Current Status

### Completed / Working

- Core backend structure in place.
- Configuration and schema layer in place.
- Modular AI and sensing services implemented.
- Unity networking, capture, and overlay scripts present.
- Project backup archives generated.
- Comprehensive analysis report generated.

### In Progress / Evolving

- Finalizing the software UI copilot experience.
- Continued refinement of Unity scene integration and screen-guidance UI.
- Further polish of task-flow behavior and overlay presentation.

---

## 7. Important Files and Entry Points

### Backend Entry Points

- [backend/main.py](backend/main.py)
- [backend/config.py](backend/config.py)
- [backend/schemas.py](backend/schemas.py)

### Backend Services

- [backend/services/pipeline_service.py](backend/services/pipeline_service.py)
- [backend/services/vlm_service.py](backend/services/vlm_service.py)
- [backend/services/detection_service.py](backend/services/detection_service.py)
- [backend/services/reasoning_service.py](backend/services/reasoning_service.py)
- [backend/services/scene_fusion_service.py](backend/services/scene_fusion_service.py)
- [backend/services/imu_fusion_service.py](backend/services/imu_fusion_service.py)

### Unity Entry Points

- [My project (1)/Assets/Scripts/Core/NeuroGuideController.cs](My%20project%20(1)/Assets/Scripts/Core/NeuroGuideController.cs)
- [My project (1)/Assets/Scripts/Networking/WebSocketManager.cs](My%20project%20(1)/Assets/Scripts/Networking/WebSocketManager.cs)
- [My project (1)/Assets/Scripts/AR/ARCameraCapture.cs](My%20project%20(1)/Assets/Scripts/AR/ARCameraCapture.cs)
- [My project (1)/Assets/Scripts/AR/AROverlayManager.cs](My%20project%20(1)/Assets/Scripts/AR/AROverlayManager.cs)
- [My project (1)/Assets/Scripts/UI/ModeSelectUI.cs](My%20project%20(1)/Assets/Scripts/UI/ModeSelectUI.cs)
- [My project (1)/Assets/Scripts/Copilot/CopilotWebSocketClient.cs](My%20project%20(1)/Assets/Scripts/Copilot/CopilotWebSocketClient.cs)

### Project Reports

- [CODEBASE_ANALYSIS.md](CODEBASE_ANALYSIS.md)
- [PROJECT_PROGRESS_REPORT.md](PROJECT_PROGRESS_REPORT.md)

---

## 8. Summary

The project has progressed from planning documents and a partial prototype into a structured end-to-end AR assistance system with a working backend pipeline, a richer Unity client, and a clear path for both live scene guidance and software UI copilot behavior.

The biggest technical achievement so far is the move to a modular architecture that keeps the already-working guidance flow intact while adding new capabilities around UI assistance, screen streaming, and step control. The codebase now has enough structure to support continued development without needing to restart from scratch.
